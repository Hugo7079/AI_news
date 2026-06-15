"""
回填 full_content 到既有 Firestore events
=========================================

前端 PDF 報表的「細節說明」改用 AI 產生的 full_content。既有 Firestore
事件沒有這個欄位，跑這支把它補上（沒有 full_content 的才處理）。

用法：
  python scripts/backfill_full_content.py            # 補所有缺 full_content 的事件
  python scripts/backfill_full_content.py --date 2026-05-27
  python scripts/backfill_full_content.py --limit 20 # 只處理前 20 筆（測試用）
  python scripts/backfill_full_content.py --dry-run  # 只統計，不呼叫 LLM、不寫入
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firestore_writer as fw
from enrich import generate_full_content


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="只處理某一天（YYYY-MM-DD）")
    ap.add_argument("--limit", type=int, default=0, help="最多處理幾筆（0=不限）")
    ap.add_argument("--dry-run", action="store_true", help="只統計，不呼叫 LLM/不寫入")
    args = ap.parse_args()

    fw._init()
    db = fw._db

    col = db.collection("events")
    query = col.where("date", "==", args.date) if args.date else col
    docs = list(query.stream())
    print(f"Firestore events 共 {len(docs)} 筆"
          + (f"（date={args.date}）" if args.date else ""))

    # 找出缺 full_content 的
    targets = []
    for d in docs:
        data = d.to_dict() or {}
        if not (data.get("full_content") or "").strip():
            targets.append((d.id, data))
    print(f"缺 full_content：{len(targets)} 筆")

    if args.limit and len(targets) > args.limit:
        targets = targets[: args.limit]
        print(f"--limit：只處理前 {len(targets)} 筆")

    if not targets:
        print("沒有需要回填的事件。")
        return
    if args.dry_run:
        print("[dry-run] 不呼叫 LLM、不寫入。")
        return

    # generate_full_content 就地寫入 ev["full_content"]
    events = [data for _, data in targets]
    generate_full_content(events)

    # 逐筆 update（只更新 full_content 欄位）
    batch = db.batch()
    n = 0
    for (doc_id, _), ev in zip(targets, events):
        fc = ev.get("full_content", "")
        if not fc:
            continue
        batch.update(col.document(doc_id), {"full_content": fc})
        n += 1
        if n % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"[done] 已回填 {n} 筆 full_content")


if __name__ == "__main__":
    main()
