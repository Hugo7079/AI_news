"""
LLM 呼叫工具（OpenAI 相容 endpoint）
====================================

只暴露 chat(prompt, system=None) -> str
"""

from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

from config import LLM_CFG


# 一般瀏覽器 UA — 繞過 Cloudflare 對 Python-urllib 的封鎖（error code 1010）
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_HAS_VERSION_RE = re.compile(r"/v\d+\w*(/|$)")


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
    if not LLM_CFG.get("api_key"):
        return ""

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": LLM_CFG.get("model", "gemma-4-31B-it"),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    url = _build_url(LLM_CFG["base_url"])
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_CFG['api_key']}",
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_CFG.get("timeout", 30)) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
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
        text = (content or "").strip()
        # 若 content 與 reasoning 不同（一般模型 finalize 過），優先 content；
        # 若 content 為空但 reasoning 有 JSON，回傳 reasoning（已落在 content 變數中）。
        return text
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")[:200]
        except Exception:
            pass
        print(f"  [LLM HTTPError] {e.code}: {body}")
        return ""
    except Exception as e:
        print(f"  [LLM error] {type(e).__name__}: {e}")
        return ""


def chat_json(prompt: str, system: str | None = None, max_tokens: int = 4000) -> dict | list | None:
    """要求模型輸出純 JSON，自動擷取第一個 JSON object/array。"""
    raw = chat(prompt, system=system, temperature=0.0, max_tokens=max_tokens)
    if not raw:
        return None
    import re
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
