"""
LLM 呼叫工具（OpenAI 相容 endpoint）
====================================

只暴露 chat(prompt, system=None) -> str
"""

from __future__ import annotations
import json
import re

import requests

from config import LLM_CFG


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
    model = LLM_CFG.get("model", "gemma-4-31B-it")
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
        print(f"  [LLM] endpoint={url}  model={model}")
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

    if resp.status_code != 200:
        body = (resp.text or "")[:300]
        print(f"  [LLM HTTPError] {resp.status_code}: {body}")
        return ""

    try:
        obj = resp.json()
    except ValueError:
        print(f"  [LLM] 回應不是 JSON：{resp.text[:200]}")
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
