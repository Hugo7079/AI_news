"""
一次性 migration：把 output/*_AI事件_*.json 灌進 Firestore。

用法：
    python3 scripts/migrate_legacy.py
    python3 scripts/migrate_legacy.py --dates 2026-05-20 2026-05-21
    python3 scripts/migrate_legacy.py --dry-run

需要本機放好 firebase-credentials.json 或設 GOOGLE_APPLICATION_CREDENTIALS。
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# 讓 scripts/ 底下也找得到專案根目錄的模組
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import OUTPUT_DIR  # noqa: E402

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_AI事件_資料庫\.json$")


def collect_dates() -> list[str]:
    dates: list[str] = []
    for fp in sorted(OUTPUT_DIR.glob("*_AI事件_資料庫.json")):
        m = DATE_RE.match(fp.name)
        if m:
            dates.append(m.group(1))
    return dates


def load_day(date_str: str) -> tuple[list[dict], list[dict], dict[str, int]]:
    db_path = OUTPUT_DIR / f"{date_str}_AI事件_資料庫.json"
    top_path = OUTPUT_DIR / f"{date_str}_AI事件_精選.json"

    with db_path.open(encoding="utf-8") as f:
        db_blob = json.load(f)
    db_events = db_blob.get("events", [])
    by_cat = db_blob.get("by_category_label", {})

    top_events: list[dict] = []
    if top_path.exists():
        with top_path.open(encoding="utf-8") as f:
            top_blob = json.load(f)
        top_events = top_blob.get("events", [])

    return db_events, top_events, by_cat


def main() -> None:
    parser = argparse.ArgumentParser(description="把舊 JSON 灌進 Firestore")
    parser.add_argument("--dates", nargs="+",
                        help="只匯入指定日期（YYYY-MM-DD），不指定就全部匯")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出會匯入哪些日期，不真的寫 Firestore")
    args = parser.parse_args()

    all_dates = collect_dates()
    targets = args.dates if args.dates else all_dates

    print(f"output/ 找到 {len(all_dates)} 天資料：{', '.join(all_dates) or '(空)'}")
    print(f"準備匯入 {len(targets)} 天：{', '.join(targets)}")

    if args.dry_run:
        for d in targets:
            db, top, by_cat = load_day(d)
            print(f"  {d}: DB {len(db)} / Top {len(top)} / by_cat {by_cat}")
        return

    from firestore_writer import write_run

    for d in targets:
        db, top, by_cat = load_day(d)
        write_run(d, db, top, by_cat)

    print("\n全部匯入完成。")


if __name__ == "__main__":
    main()
