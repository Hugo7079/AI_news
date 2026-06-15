"""
回填封面圖到既有 Firestore events
==================================

之前 pipeline 用 parallel=4 呼叫 gateway 文生圖，41/43 都 504。改成 sequential
+ retry 後沒問題，但 Firestore 裡的 cover_image 還是 fallback。這支只補圖、
不重跑整個 pipeline。

用法：
  python scripts/backfill_cover_images.py                    # 補今天
  python scripts/backfill_cover_images.py --date 2026-06-15  # 指定日期
  python scripts/backfill_cover_images.py --limit 5          # 測試
  python scripts/backfill_cover_images.py --force            # 連已有圖的也重生
"""

from __future__ import annotations
import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firestore_writer as fw
from cover_image import _gateway_generate, _build_image_prompt
from config import OUTPUT_DIR


def _today_taiwan() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _short_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=_today_taiwan(), help="處理某一天（YYYY-MM-DD）")
    ap.add_argument("--limit", type=int, default=0, help="最多處理幾筆（0=不限）")
    ap.add_argument("--force", action="store_true", help="連已有 remote 圖的也重生")
    args = ap.parse_args()

    fw._init()
    db = fw._db

    col = db.collection("events")
    docs = list(col.where("date", "==", args.date).stream())
    print(f"Firestore events {args.date}：共 {len(docs)} 筆")

    targets = []
    for d in docs:
        data = d.to_dict() or {}
        cover = data.get("cover_image") or {}
        if args.force or cover.get("kind") != "remote" or not cover.get("url"):
            targets.append((d.id, data))
    print(f"待補圖：{len(targets)} 筆")

    if args.limit and len(targets) > args.limit:
        targets = targets[: args.limit]
        print(f"--limit：只處理前 {len(targets)} 筆")
    if not targets:
        print("沒有需要補圖的事件。")
        return

    img_dir = OUTPUT_DIR / "images" / args.date
    img_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    fail = 0
    for i, (doc_id, ev) in enumerate(targets, 1):
        title = (ev.get("title") or "")[:40]
        print(f"[{i}/{len(targets)}] {title}", flush=True)
        prompt = _build_image_prompt(
            ev.get("title", ""),
            ev.get("summary", ""),
            ev.get("category", "uncategorized"),
        )
        t0 = time.monotonic()
        img_bytes = _gateway_generate(prompt)
        dt = time.monotonic() - t0
        if not img_bytes:
            print(f"  [skip] 生圖失敗 ({dt:.1f}s)", flush=True)
            fail += 1
            continue

        seed = ev.get("sources", [{}])[0].get("url", "") or ev.get("title", "") or doc_id
        fname = f"{_short_id(seed)}.png"
        fpath = img_dir / fname
        fpath.write_bytes(img_bytes)

        public_url = fw._upload_cover(f"images/{args.date}/{fname}", args.date)
        if not public_url:
            print(f"  [skip] Storage 上傳失敗", flush=True)
            fail += 1
            continue

        col.document(doc_id).update({"cover_image": {"kind": "remote", "url": public_url}})
        ok += 1
        print(f"  [ok] {dt:.1f}s → {public_url[:80]}", flush=True)
        # gateway 順序測試證明每張 15s 內，但保險起見讓 server 喘一下
        time.sleep(1.0)

    print(f"\n[done] 成功 {ok} / 失敗 {fail}（共 {len(targets)}）")


if __name__ == "__main__":
    main()
