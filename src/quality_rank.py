"""
品質過濾 + 重要度評分
=====================

接在 classifier.dedup() 之後：
  1) 短內容硬篩：summary < MIN_SUMMARY_CHARS 直接淘汰
  2) LLM 評分：
       - specificity: 是否有具體事實（公司/產品/數字/日期）
       - importance:  1–10 的重要度分數
  3) 每類保留 PER_CAT_DB（10–20 則）進 Excel 資料庫
  4) 每類取 TOP_PICKS（3 則）作為前端精選
"""

from __future__ import annotations
import re
from collections import defaultdict

from config import CATEGORIES, CATEGORY_LABEL_BY_ID, LLM_BATCH_SIZE
from llm import chat_json


MIN_SUMMARY_CHARS = 40       # 摘要少於此字數直接砍
PER_CAT_DB = 20              # 每類進 Excel 的上限
TOP_PICKS = 3                # 每類前端精選


_RANK_SYSTEM = (
    "你是 AI 新聞主編，正在替每日 AI 新聞做品質把關與重要度評分。\n"
    "對每則新聞，請判斷：\n"
    "  1) keep（bool）：是否值得保留。以下情況請 keep=false 並寫明 reason：\n"
    "     - 標題與摘要過於空泛、只是評論或預測（例如「AI 將改變一切」、「專家說 AI 很重要」）\n"
    "     - 沒有提到具體公司名、產品名、數字、事件或日期\n"
    "     - 看不出在報導什麼具體事件\n"
    "     - 純廣告文、贊助內容、付費牆預覽片段\n"
    "  2) importance（1–10 整數）：重要度。評分依據：\n"
    "     - 新穎性（首次發布 > 後續報導）\n"
    "     - 影響規模（大公司、大金額、大規模採用 > 小事）\n"
    "     - 對讀者實用性（產業重要 > 個案趣聞）\n"
    "  3) reason（≤ 20 字）：分數理由\n\n"
    "輸出純 JSON array，與輸入順序對應，每筆 {\"idx\":int,\"keep\":bool,\"importance\":int,\"reason\":str}。"
    "不要輸出 JSON 以外的文字。"
)


def _build_payload(batch: list[dict], category_label: str) -> str:
    rows = []
    for i, it in enumerate(batch):
        title = (it.get("title") or "")[:200]
        summary = (it.get("summary") or "")[:400]
        rows.append(f"[{i}] 標題：{title}\n摘要：{summary}")
    return (
        f"類別：{category_label}\n\n"
        f"請評估以下 {len(batch)} 則新聞：\n\n" + "\n\n".join(rows)
    )


def _rank_batch(batch: list[dict], category_label: str) -> list[dict]:
    """回傳 [{idx, keep, importance, reason}, ...]，失敗回 []"""
    result = chat_json(_build_payload(batch, category_label),
                       system=_RANK_SYSTEM, max_tokens=4000)
    if isinstance(result, list) and result:
        return result
    # 拆半重試
    if len(batch) > 1:
        half = len(batch) // 2
        r1 = chat_json(_build_payload(batch[:half], category_label),
                       system=_RANK_SYSTEM, max_tokens=3000)
        r2 = chat_json(_build_payload(batch[half:], category_label),
                       system=_RANK_SYSTEM, max_tokens=3000)
        if isinstance(r1, list) and isinstance(r2, list):
            for r in r2:
                if isinstance(r, dict) and "idx" in r:
                    r["idx"] = int(r["idx"]) + half
            return r1 + r2
    # 單筆 fallback
    out: list[dict] = []
    for i, single in enumerate(batch):
        r = chat_json(_build_payload([single], category_label),
                      system=_RANK_SYSTEM, max_tokens=2000)
        if isinstance(r, list) and r:
            r[0]["idx"] = i
            out.append(r[0])
        else:
            out.append({"idx": i, "keep": True, "importance": 5,
                        "reason": "LLM 失敗，預設保留"})
    return out


def rank_and_filter(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    回傳 (db_items, top_items)：
      db_items  — 每類保留 ≤ PER_CAT_DB 則（按 importance 降序）
      top_items — 每類前 TOP_PICKS 則
    每筆 item 會新增 importance / quality_reason 欄位。
    """
    # 1) 先做硬篩
    survived: list[dict] = []
    dropped_short = 0
    for it in items:
        if len((it.get("summary") or "").strip()) < MIN_SUMMARY_CHARS:
            dropped_short += 1
            continue
        survived.append(it)
    if dropped_short:
        print(f"  短摘要剔除：{dropped_short} 則（summary < {MIN_SUMMARY_CHARS} 字）")

    # 2) 按類別分組
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for it in survived:
        by_cat[it.get("category", "uncategorized")].append(it)

    db_items: list[dict] = []
    top_items: list[dict] = []
    print("  類別品質評分：")
    for cid in list(CATEGORIES.keys()) + ["uncategorized"]:
        rows = by_cat.get(cid, [])
        if not rows:
            continue
        label = CATEGORY_LABEL_BY_ID.get(cid, "未分類")

        # 3) 分批送 LLM 評分
        scores_by_local_i: dict[int, dict] = {}
        for start in range(0, len(rows), LLM_BATCH_SIZE):
            batch = rows[start: start + LLM_BATCH_SIZE]
            rs = _rank_batch(batch, label)
            for r in rs:
                if not isinstance(r, dict) or "idx" not in r:
                    continue
                local_i = int(r["idx"]) + start
                scores_by_local_i[local_i] = r

        # 4) 套用評分
        ranked: list[dict] = []
        for i, it in enumerate(rows):
            r = scores_by_local_i.get(i, {"keep": True, "importance": 5, "reason": "LLM 漏判，預設保留"})
            it["importance"] = int(r.get("importance", 5)) if str(r.get("importance", "")).strip() else 5
            it["quality_keep"] = bool(r.get("keep", True))
            it["quality_reason"] = str(r.get("reason", ""))[:60]
            if it["quality_keep"]:
                ranked.append(it)

        ranked.sort(key=lambda x: x.get("importance", 0), reverse=True)
        cat_db = ranked[:PER_CAT_DB]
        cat_top = ranked[:TOP_PICKS]
        db_items.extend(cat_db)
        top_items.extend(cat_top)
        dropped = len(rows) - len(ranked)
        print(f"    {label:14s} 總 {len(rows):3d} → 保留 {len(cat_db):3d}（剔除 {dropped:3d}）→ 精選 {len(cat_top)}")

    return db_items, top_items
