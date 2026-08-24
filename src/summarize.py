"""
繁體中文摘要重寫（同時處理新聞與開源生態項目）
================================================

在 rank_and_filter 之後、attach_cover_images 之前呼叫一次。

  ‣ source_kind != "opensource"
      → 視為新聞，重寫成 2-3 句繁體中文摘要、120-180 字、保留具體事實
  ‣ source_kind == "opensource"
      → 視為「平台新發/熱門上架」報導，根據 metadata 改寫成新聞式 1-2 句介紹

  ‣ 原文保留到 item["summary_original"]
  ‣ 重寫後寫回 item["summary"]
  ‣ 失敗保留原摘要、流程繼續

精選 top_items 與資料庫 db_items 共用 dict reference，
所以對 db_items 跑一次即可、兩邊都會更新。
"""

from __future__ import annotations
import json

from llm import chat_json


_SUMMARIZE_SYSTEM = (
    "你是 AI 新聞編輯。對每則項目，依其 kind 欄位用不同寫法輸出繁體中文摘要。\n"
    "\n"
    "● kind = \"news\"（一般新聞）：\n"
    "  - 2 到 3 句話，120–180 個繁體中文字。\n"
    "  - 保留所有具體事實：公司名、產品名、版本號、金額、日期、數字、地名。\n"
    "  - 用書面繁體中文與台灣慣用詞（如「人工智慧」「半導體」「程式碼」），"
    "不要出現簡體字，也不要整段英文。\n"
    "  - 不要評論、不要預測、不要套話。\n"
    "\n"
    "● kind = \"opensource\"（HF / GitHub / Ollama / OpenRouter 上的模型或專案）：\n"
    "  把元資料改寫成「平台動態」的新聞句，1–2 句、80–140 字：\n"
    "  - HF Trending Model：說明是哪個機構/開發者釋出的什麼模型、主打任務、"
    "下載與 likes 數所反映的社群熱度。\n"
    "  - HF Daily Papers：論文主題與貢獻、upvote 數。\n"
    "  - GitHub Trending：repo 用途、開發語言、本週新增 star 數。\n"
    "  - Ollama Library：哪個模型出現在 Ollama 上、可做什麼、最近更新與下載量。\n"
    "  - OpenRouter Models：新上架模型來自哪家公司、context 長度、價格亮點。\n"
    "  - 保留原文中的具體數字與專有名詞，不用評論性語言。\n"
    "\n"
    "輸入是 JSON array，每筆有 idx / kind / title / summary。\n"
    "輸出『純 JSON array』，與輸入一一對應，每筆 {\"idx\": int, \"summary\": str}。\n"
    "不要輸出 JSON 以外的任何文字。"
)


def _kind_of(it: dict) -> str:
    return "opensource" if it.get("source_kind") == "opensource" else "news"


def _build_payload(batch: list[dict]) -> str:
    rows = []
    for i, it in enumerate(batch):
        rows.append({
            "idx": i,
            "kind": _kind_of(it),
            "title": (it.get("title") or "")[:200],
            "summary": (it.get("summary") or "")[:900],
        })
    return (
        f"請替下列 {len(batch)} 則項目各寫一段繁體中文摘要：\n\n"
        + json.dumps(rows, ensure_ascii=False)
    )


def rewrite_summaries_zh(items: list[dict], batch_size: int = 8) -> None:
    """
    in-place 更新 items：
      ‣ item["summary_original"] = 原摘要（首次重寫前才寫）
      ‣ item["summary"]          = 繁體中文重寫版（成功時）
    """
    if not items:
        return

    print(f"  繁體中文摘要重寫：{len(items)} 則（包含新聞與開源生態 metadata）")

    total_batches = (len(items) + batch_size - 1) // batch_size
    ok_count = 0
    fail_count = 0

    for b in range(total_batches):
        batch = items[b * batch_size: (b + 1) * batch_size]
        result = chat_json(
            _build_payload(batch),
            system=_SUMMARIZE_SYSTEM,
            max_tokens=4000,
        )

        if not isinstance(result, list) or not result:
            # 拆半重試一次
            if len(batch) > 1:
                half = len(batch) // 2
                r1 = chat_json(_build_payload(batch[:half]),
                               system=_SUMMARIZE_SYSTEM, max_tokens=3000)
                r2 = chat_json(_build_payload(batch[half:]),
                               system=_SUMMARIZE_SYSTEM, max_tokens=3000)
                merged: list = []
                if isinstance(r1, list):
                    merged.extend(r1)
                if isinstance(r2, list):
                    for r in r2:
                        if isinstance(r, dict) and "idx" in r:
                            try:
                                r["idx"] = int(r["idx"]) + half
                            except Exception:
                                pass
                    merged.extend(r2)
                result = merged

        by_idx: dict[int, dict] = {}
        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict) and "idx" in r and r.get("summary"):
                    try:
                        by_idx[int(r["idx"])] = r
                    except Exception:
                        continue

        for local_i, it in enumerate(batch):
            r = by_idx.get(local_i)
            if r:
                new_summary = str(r["summary"]).strip()[:400]
                if new_summary:
                    if "summary_original" not in it:
                        it["summary_original"] = it.get("summary", "")
                    it["summary"] = new_summary
                    ok_count += 1
                    continue
            fail_count += 1

        if (b + 1) % 5 == 0 or b + 1 == total_batches:
            print(f"    進度 {b + 1}/{total_batches}  累計 ok={ok_count}, fail={fail_count}", flush=True)

    print(f"  繁體中文摘要重寫完成：ok={ok_count}, fail={fail_count}（失敗保留原摘要）")
