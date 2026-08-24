"""
本地資料庫（不依賴 Firebase）
=============================

把每天的事件寫成一個 JSON 檔：

    output/store/{YYYY-MM-DD}.json
      {
        "summary": { date, total_db, total_top, by_category_label, generated_at },
        "events":  [ 事件文件（與 Firestore 同一份 schema）… ]
      }

封面圖沿用 pipeline 產生的 output/images/{date}/{file}，由 src/server.py 以
/media/images/... 提供，整套完全跑在自己的機器上。

檔案式儲存的理由：每天 60~80 筆事件、一年也才 3 萬筆，讀取一整個月只是掃 30 個
檔案；用純檔案就不用多裝資料庫、備份直接複製資料夾、出問題也能直接打開來看。
"""

from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path

from config import OUTPUT_DIR
from doc_model import build_docs, build_summary, keep_cover

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def store_dir() -> Path:
    d = Path(os.getenv("AINEWS_STORE_DIR", "").strip() or (OUTPUT_DIR / "store"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def day_path(date_str: str) -> Path:
    return store_dir() / f"{date_str}.json"


def write_day(date_str: str, events: list[dict], summary: dict) -> Path:
    """整天覆寫（與 Firestore writer 的「先清當天再寫」行為一致）。"""
    payload = {"summary": summary, "events": events}
    path = day_path(date_str)
    # 先寫暫存檔再 rename：避免 server 讀到寫到一半的檔案
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_run(date_str: str,
              db_events: list[dict],
              top_events: list[dict],
              by_category_label: dict[str, int]) -> Path:
    """主入口：把當日 pipeline 結果寫進本地 store。"""
    docs = build_docs(date_str, db_events, top_events, cover_resolver=keep_cover)
    summary = build_summary(date_str, db_events, top_events, by_category_label)
    path = write_day(date_str, docs, summary)
    print(f"[local-store] 寫入 {path}（events {len(docs)} 筆 / top {len(top_events)}）")
    return path


def list_dates() -> list[str]:
    """有資料的日期，新到舊。"""
    out = []
    for fp in store_dir().glob("*.json"):
        name = fp.stem
        if DATE_RE.match(name):
            out.append(name)
    out.sort(reverse=True)
    return out


def load_day(date_str: str) -> dict | None:
    fp = day_path(date_str)
    if not fp.exists():
        return None
    try:
        with fp.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[local-store] 讀取 {fp.name} 失敗：{type(e).__name__}: {e}")
        return None


def load_events(start: str, end: str) -> list[dict]:
    """讀出 [start, end] 這段日曆區間內的所有事件（含沒有資料的日期，直接略過）。"""
    events: list[dict] = []
    for d in sorted(x for x in list_dates() if start <= x <= end):
        day = load_day(d)
        if day:
            events.extend(day.get("events") or [])
    return events


def load_summaries() -> list[dict]:
    out = []
    for d in list_dates():
        day = load_day(d)
        if day and day.get("summary"):
            out.append(day["summary"])
    return out
