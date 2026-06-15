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
    return f"""請根據以下事件資訊，彙整撰寫成 3 至 4 段、完整通順的繁體中文新聞內文。

【事件標題】{ev.get('title', '')}
【一句摘要】{ev.get('summary', '')}
【主體】{'、'.join(ev.get('who', []) or [])}
【動作】{ev.get('what', '')}
【時間】{ev.get('when', '')}
【地點】{ev.get('where', '')}
【來源報導標題】
{src_lines}

要求：
1. 只根據上述資訊撰寫，不得杜撰不存在的數據、引述或細節。
2. 第一段點出事件核心；後續段落補充背景、細節與可能影響。
3. 每段 2-4 句，段落之間以空行分隔。
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


def _generate_one(ev: dict) -> bool:
    if ev.get("full_content"):
        return False
    try:
        # gateway 上的模型（gemma-4-31B-it / Qwen 等）現在都是推理型：會先花 token
        # 思考（reasoning_content），再寫文章。token 太小會在思考階段就被截斷，
        # 導致 content 為空 → 退回摘要 → 細節與摘要一模一樣。
        raw = chat(_build_prompt(ev), system=_SYSTEM, temperature=0.3, max_tokens=6000)
    except Exception as e:
        print(f"    [enrich error] {ev.get('title','')[:24]}…：{type(e).__name__}: {e}")
        raw = ""
    text = _clean(raw)
    # 失敗時退回摘要，確保 PDF 一定有內容
    ev["full_content"] = text or ev.get("summary", "")
    return bool(text)


def generate_full_content(events: list[dict],
                          max_workers: int = FULL_CONTENT_WORKERS) -> None:
    """為 events 逐一產生 full_content（就地寫入）。已有的會略過。"""
    targets = [ev for ev in events if not ev.get("full_content")]
    if not targets:
        return
    print(f"\n事件全文彙整中（共 {len(targets)} 個 / 平行 {max_workers}）...")

    done = {"n": 0, "ok": 0}
    lock = threading.Lock()

    def _worker(ev: dict):
        ok = _generate_one(ev)
        with lock:
            done["n"] += 1
            done["ok"] += int(ok)
            if done["n"] % 5 == 0 or done["n"] == len(targets):
                print(f"    進度 {done['n']}/{len(targets)}  成功 {done['ok']}", flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_worker, targets))

    print(f"全文彙整完成：{done['ok']}/{len(targets)} 成功")
