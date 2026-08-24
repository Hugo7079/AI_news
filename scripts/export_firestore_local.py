#!/usr/bin/env python3
"""
把 Firestore 上的歷史資料倒回本地 store
=======================================

搬到自架（AINEWS_STORE=local）之後，本地一開始是空的；用這支把雲端既有的
events / daily_summary 匯出成 output/store/{date}.json，網站就有完整歷史。

    python3 scripts/export_firestore_local.py                    # 全部
    python3 scripts/export_firestore_local.py --start 2026-08-01 # 指定區間
    python3 scripts/export_firestore_local.py --download-images  # 順便把封面圖抓下來

--download-images 會把 Firebase Storage 上的封面圖下載到 output/images/{date}/，
並把 cover_image 改成本地路徑；不加的話封面仍指向雲端網址（需要外網才看得到）。
需要 firebase-credentials.json（或 FIREBASE_SERVICE_ACCOUNT_JSON）。
"""

from __future__ import annotations
import argparse
import hashlib
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import firestore_writer as fw          # noqa: E402
import local_store                     # noqa: E402
from config import OUTPUT_DIR          # noqa: E402
from doc_model import build_summary    # noqa: E402

UA = "Mozilla/5.0 (compatible; ainews-export/1.0)"


def _download_cover(url: str, date_str: str) -> str | None:
    """下載封面圖到 output/images/{date}/，回傳相對路徑（失敗回 None）。"""
    img_dir = OUTPUT_DIR / "images" / date_str
    img_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:10] + ".png"
    dest = img_dir / name
    rel = f"images/{date_str}/{name}"
    if dest.exists() and dest.stat().st_size > 0:
        return rel
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        if len(raw) < 512:
            return None
        dest.write_bytes(raw)
        return rel
    except Exception as e:
        print(f"    [warn] 封面下載失敗 {type(e).__name__}: {e}")
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Firestore → 本地 store")
    ap.add_argument("--start", default="", help="起日 YYYY-MM-DD（含）")
    ap.add_argument("--end", default="", help="迄日 YYYY-MM-DD（含）")
    ap.add_argument("--download-images", action="store_true",
                    help="把封面圖一起抓到本地 output/images/")
    ap.add_argument("--overwrite", action="store_true",
                    help="已存在的本地檔案也重新匯出")
    args = ap.parse_args()

    fw._init()
    db = fw._db

    col = db.collection("events")
    if args.start:
        col = col.where("date", ">=", args.start)
    if args.end:
        col = col.where("date", "<=", args.end)

    print("[export] 從 Firestore 讀取 events…")
    by_date: dict[str, list[dict]] = defaultdict(list)
    for doc in col.stream():
        d = doc.to_dict() or {}
        date_str = d.get("date") or ""
        if date_str:
            by_date[date_str].append(d)
    print(f"[export] 取得 {sum(len(v) for v in by_date.values())} 筆事件 / {len(by_date)} 天")

    # daily_summary 拿來還原統計數字（沒有的話從事件重算）
    summaries: dict[str, dict] = {}
    for doc in db.collection("daily_summary").stream():
        summaries[doc.id] = doc.to_dict() or {}

    written = 0
    for date_str in sorted(by_date):
        if not args.overwrite and local_store.day_path(date_str).exists():
            print(f"  [skip] {date_str}（已存在，加 --overwrite 可覆寫）")
            continue

        events = sorted(
            by_date[date_str],
            key=lambda e: (-(e.get("importance") or 0), -(e.get("mention_count") or 0)),
        )

        if args.download_images:
            for ev in events:
                cover = ev.get("cover_image") or {}
                if cover.get("kind") == "remote" and cover.get("url", "").startswith("http"):
                    rel = _download_cover(cover["url"], date_str)
                    if rel:
                        ev["cover_image"] = {"kind": "local", "url": rel}

        summary = summaries.get(date_str)
        if not summary:
            by_cat: dict[str, int] = defaultdict(int)
            for ev in events:
                by_cat[ev.get("category_label") or "其他"] += 1
            tops = [e for e in events if e.get("is_top")]
            summary = build_summary(date_str, events, tops, dict(by_cat))

        local_store.write_day(date_str, events, summary)
        written += 1
        print(f"  [ok] {date_str}：{len(events)} 筆")

    print(f"\n[export] 完成，共寫入 {written} 天 → {local_store.store_dir()}")


if __name__ == "__main__":
    main()
