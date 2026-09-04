"""
LLM 呼叫工具（OpenAI 相容 endpoint）
====================================

只暴露 chat(prompt, system=None) -> str
"""

from __future__ import annotations
import json
import os
import re
import threading
import time

import requests

from config import LLM_CFG


# ─── 全域速率限制 ───
# Mistral 免費 Experiment tier 是 1 RPS（＝60 RPM）、500K TPM。
# 預設 30 RPM（＝2 秒一次）而不是貼著 60 跑：1 RPS 是硬限制，實測 45 RPM
# （1.33 秒間隔）在多 worker 並行時仍會零星撞 429。2 秒留足餘裕，代價只是
# 整趟多幾分鐘，遠比掉 batch 划算。換別家記得跟著調：
# Groq 免費版 30 RPM、OpenRouter free 20 RPM。可用 AINEWS_LLM_RPM 覆寫。
_RPM_LIMIT = int(os.getenv("AINEWS_LLM_RPM", "30"))


class _RateLimiter:
    """同時管「每分鐘上限」與「兩次請求的最小間隔」；thread-safe。

    只看每分鐘上限是不夠的：45 RPM 的滑動視窗允許瞬間連發 45 次，而 Mistral
    免費版限制是 1 RPS —— pipeline 用 ThreadPoolExecutor 平行送，一定會爆
    429。最小間隔直接由 rpm 推導（45 RPM → 1.33 秒），自然把請求攤平。
    """

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self.min_interval = 60.0 / self.rpm
        self.lock = threading.Lock()
        self.timestamps: list[float] = []
        self.last_sent = 0.0

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.timestamps = [t for t in self.timestamps if t > now - 60.0]

                # 距離上一次太近 → 等到間隔滿足
                gap = self.last_sent + self.min_interval - now
                if gap > 0:
                    wait = gap
                elif len(self.timestamps) >= self.rpm:
                    wait = self.timestamps[0] + 60.0 - now + 0.1
                else:
                    self.timestamps.append(now)
                    self.last_sent = now
                    return
            time.sleep(max(wait, 0.02))


_rate_limiter = _RateLimiter(_RPM_LIMIT)


# 一般瀏覽器 UA — 繞過 Cloudflare 對 Python 預設 UA 的封鎖（error code 1010）
_HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/event-stream",
    "Accept-Language": "en-US,en;q=0.9",
}

_HAS_VERSION_RE = re.compile(r"/v\d+\w*(/|$)")

# 用一個共用 session：keep-alive、共用 connection pool，行為更像真實瀏覽器
_session = requests.Session()
_logged_url = False


def _build_url(base: str) -> str:
    """根據 base_url 自動補上正確的 path：
    - 若 base 已含完整 /chat/completions → 直接用
    - 若 base 已含 /v1 或 /v1beta 等版本片段 → 補 /chat/completions
    - 否則（如 http://host:port/） → 補 /v1/chat/completions
    """
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if _HAS_VERSION_RE.search(base):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def chat(prompt: str, system: str | None = None, temperature: float = 0.0,
         max_tokens: int = 4000) -> str:
    """
    呼叫 OpenAI 相容 /v1/chat/completions；失敗回空字串。
    """
    global _logged_url
    api_key = LLM_CFG.get("api_key", "")
    base_url = LLM_CFG.get("base_url", "")
    model = LLM_CFG.get("model", "mistral-small-latest")
    if not api_key:
        if not _logged_url:
            print("  [LLM] api_key 為空 — 跳過所有 LLM 呼叫")
            _logged_url = True
        return ""
    if not base_url:
        if not _logged_url:
            print("  [LLM] base_url 為空 — 跳過所有 LLM 呼叫")
            _logged_url = True
        return ""

    url = _build_url(base_url)
    if not _logged_url:
        print(f"  [LLM] endpoint={url}  model={model}  "
                  f"rpm={_RPM_LIMIT} 最小間隔={_rate_limiter.min_interval:.2f}s")
        _logged_url = True

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        **_HEADERS_BASE,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 429 / 502 / 503 / 504：等一下再試最多 3 次（指數退避 + Retry-After）
    # 429 在 Mistral 上代表撞到 1 RPS 或 500K TPM，等一下就會過；5xx 是後端暫時
    # 不可用。這些一定要重試，否則 merge/enrich 的呼叫會直接放棄、整份報表變空。
    max_attempts = 4
    backoff = 4.0
    resp = None
    for attempt in range(1, max_attempts + 1):
        # 每次嘗試都重新排隊 —— 重試若繞過節流，就會直接撞在其他 worker
        # 的請求上，把原本只是暫時性的 429 變成連環 429。
        _rate_limiter.acquire()
        try:
            resp = _session.post(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                timeout=LLM_CFG.get("timeout", 30),
            )
        except requests.RequestException as e:
            print(f"  [LLM error] {type(e).__name__}: {e}")
            return ""

        if resp.status_code == 200:
            break
        if resp.status_code in (429, 502, 503, 504) and attempt < max_attempts:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else backoff
            except ValueError:
                wait = backoff
            wait = min(wait, 30.0)
            time.sleep(wait)
            backoff *= 2
            continue
        # 不可重試的錯誤 → 直接回
        body = (resp.text or "")[:300]
        print(f"  [LLM HTTPError] {resp.status_code}: {body}")
        return ""

    if resp is None or resp.status_code != 200:
        return ""

    try:
        obj = resp.json()
    except ValueError:
        print(f"  [LLM] 回應不是 JSON：{resp.text[:200]}")
        return ""

    # gateway（litellm proxy）即使後端模型掛掉，仍可能回 HTTP 200 + 錯誤內容，
    # 例如 {"status":"error","error_message":{...}} 或 {"detail":"Model ... not found"}。
    # 不在這裡攔截就會被誤判為「成功但沒事件」，整份報表默默變空。
    if isinstance(obj, dict) and (
        obj.get("status") == "error" or obj.get("error") or obj.get("detail")
        or ("choices" not in obj and "object" not in obj)
    ):
        body = json.dumps(obj, ensure_ascii=False)[:300]
        print(f"  [LLM gateway-error] HTTP200 但回傳錯誤內容：{body}")
        return ""

    choices = obj.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    reasoning = msg.get("reasoning_content") or ""
    # 推理型模型常把答案放在 reasoning_content；content 為 None
    if not content:
        content = reasoning
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict):
                parts.append(blk.get("text") or blk.get("content") or "")
            else:
                parts.append(str(blk))
        content = "".join(parts)
    return (content or "").strip()


def chat_json(prompt: str, system: str | None = None, max_tokens: int = 4000) -> dict | list | None:
    """要求模型輸出純 JSON，自動擷取第一個 JSON object/array。"""
    raw = chat(prompt, system=system, temperature=0.0, max_tokens=max_tokens)
    if not raw:
        return None
    # 1) 先試 ```json ... ```
    m = re.search(r"```json\s*(.*?)```", raw, flags=re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed
    # 2) 找出 raw 中所有 [...] 與 {...} 候選（最長優先）
    candidates: list[str] = []
    for open_c, close_c in (("[", "]"), ("{", "}")):
        depth = 0
        start = -1
        for i, ch in enumerate(raw):
            if ch == open_c:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == close_c and depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidates.append(raw[start:i+1])
                    start = -1
    # 最長的 JSON 候選通常是 final answer
    for cand in sorted(candidates, key=len, reverse=True):
        parsed = _try_parse(cand)
        if parsed is not None:
            return parsed
    return None


def _try_parse(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None
