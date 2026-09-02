"""
事件全文彙整（full_content）
============================

用 LLM 把每個事件的零散資訊（標題 / 摘要 / 5W / 來源標題）彙整成一篇
通順、客觀、多段落的繁體中文新聞內文，存進 ev["full_content"]。

供 PDF 報表的「細節說明」區使用 —— 不再只是列出資料來源，而是 AI
產生的完整事件內容。

受 llm.py 的全域 RPM 限制保護，這裡用小型 ThreadPool 重疊網路延遲即可。
"""

from __future__ import annotations
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from llm import chat

# 受 llm.py 8 RPM 全域限制保護，worker 數只影響網路延遲重疊
FULL_CONTENT_WORKERS = 4

_SYSTEM = (
    "你是一位專業的科技新聞編輯。根據提供的事件資訊，撰寫通順、客觀的繁體中文新聞彙整。"
    "只輸出文章內文本身，不要任何前言、分析、要點符號、標題或結語。"
)


def _build_prompt(ev: dict) -> str:
    src_lines = "\n".join(
        f"- {s.get('source_name', '')}：{s.get('title', '')}"
        for s in (ev.get("sources") or []) if s.get("title")
    ) or "（無）"
    return f"""請根據以下事件資訊，彙整撰寫成 6 至 8 段、完整深入的繁體中文新聞內文（約 600-800 字）。

【事件標題】{ev.get('title', '')}
【一句摘要】{ev.get('summary', '')}
【主體】{'、'.join(ev.get('who', []) or [])}
【動作】{ev.get('what', '')}
【時間】{ev.get('when', '')}
【地點】{ev.get('where', '')}
【來源報導標題】
{src_lines}

要求：
1. 只根據上述資訊與你對該領域的常識背景撰寫，不得杜撰不存在的具體數據、引述或財務數字。
2. 結構：第一段點出事件核心；中間數段深入展開——技術/產品細節、相關背景脈絡、產業競爭格局、對使用者或市場的意義；最後一段談可能影響與後續觀察點。
3. 每段 3-5 句，內容要充實有資訊量，避免空泛重複；段落之間以空行分隔。
4. 直接輸出文章內文，不要標題，不要「以下是」「總結」之類的開場或收尾。"""


def _clean(text: str) -> str:
    """移除模型偶爾殘留的開場白 / 標記，保留乾淨內文。"""
    text = (text or "").strip()
    # 去掉常見開場白行
    bad_starts = ("以下是", "好的", "當然", "這是一篇", "新聞內文：", "彙整：")
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and (not lines[0].strip() or lines[0].strip().startswith(bad_starts)):
        lines.pop(0)
    # 壓掉連續空行成單一空行
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln.strip():
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _is_good(text: str, summary: str) -> bool:
    """判斷生成的全文是否合格：非空、不等於摘要、長度足夠（電子報細節要充實）。"""
    t = (text or "").strip()
    s = (summary or "").strip()
    if not t or t == s:
        return False
    # 至少 350 字，且比 summary 長 2.5 倍以上（要求深入的長內文，不能只比摘要長一點）
    if len(t) < 350 or len(t) < len(s) * 2.5:
        return False
    return True


def _generate_one(ev: dict, deadline: float | None = None) -> bool:
    if ev.get("full_content"):
        return False
    summary = ev.get("summary", "")
    # 時間預算保險：超過 deadline 就不再呼叫 LLM，直接用 summary 當內文，
    # 確保每則事件都有 full_content、報表能順利產出（CI 不被 cancel）。
    if deadline is not None and time.monotonic() > deadline:
        ev["full_content"] = summary
        return False
    text = ""
    # 最多 2 次：現在的模型（mistral-small-latest 等）多半是混合推理型：會先
    # 花 token 思考（reasoning_content），再寫文章。token 太小會在思考階段就被截斷，
    # 導致 content 為空 → 退回摘要 → 細節與摘要一模一樣。
    for attempt in range(2):
        try:
            raw = chat(_build_prompt(ev), system=_SYSTEM,
                       temperature=0.3 + attempt * 0.2,  # 第二次稍微提高 temperature
                       max_tokens=9000)  # 600-800 字長文 + 推理思考，需要更大預算
        except Exception as e:
            print(f"    [enrich error] {ev.get('title','')[:24]}…：{type(e).__name__}: {e}")
            raw = ""
        text = _clean(raw)
        if _is_good(text, summary):
            break
    # 失敗時退回摘要，確保 PDF 一定有內容
    ev["full_content"] = text or summary
    return _is_good(text, summary)


def generate_full_content(events: list[dict],
                          max_workers: int = FULL_CONTENT_WORKERS,
                          deadline: float | None = None) -> None:
    """為 events 逐一產生 full_content（就地寫入）。已有的會略過。
    deadline（time.monotonic() 時間點）過後的事件直接用 summary 當內文，
    確保 CI 90 分鐘預算內一定能寫出報表。"""
    targets = [ev for ev in events if not ev.get("full_content")]
    if not targets:
        return
    print(f"\n事件全文彙整中（共 {len(targets)} 個 / 平行 {max_workers}）...")

    done = {"n": 0, "ok": 0}
    lock = threading.Lock()

    def _worker(ev: dict):
        ok = _generate_one(ev, deadline=deadline)
        with lock:
            done["n"] += 1
            done["ok"] += int(ok)
            if done["n"] % 5 == 0 or done["n"] == len(targets):
                print(f"    進度 {done['n']}/{len(targets)}  成功 {done['ok']}", flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_worker, targets))

    print(f"全文彙整完成：{done['ok']}/{len(targets)} 成功")
