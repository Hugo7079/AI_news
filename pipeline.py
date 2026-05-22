"""
每日 AI 事件 pipeline（事件中心）
=================================

模型：以「事件」為單位，新聞作為「證據來源」。

流程：
  1) fetch_all_sources()           — RSS / vendor / community / podcast
  2) google_news_supplement()      — Google News 即時搜尋
  2.5) fetch_opensource_supplement() — HF / GitHub / Ollama / OpenRouter
  3) prefilter()                   — AI 關鍵字粗篩
  4) URL 去重
  5) extract_events_from_items()   — LLM 抽事件（一篇可拆 0..N 個）
  6) merge_events()                — fingerprint + LLM 邊界判定，合併同事件
  7) filter_events()                — 重要度 / 摘要長度硬篩
  8) attach_cover_images(top)      — 給 top 事件抓 og:image 或 HF 生圖
  9) 輸出 events.json + events.xlsx
"""

from __future__ import annotations
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, CATEGORIES, CATEGORY_LABEL_BY_ID, DEFAULT_DAYS_BACK, ENABLE_GOOGLE_NEWS_DEFAULT
from fetcher import fetch_all_sources, google_news_supplement, prefilter
from sources_extra import fetch_opensource_supplement
from events import extract_events_from_items, merge_events, filter_events
from cover_image import attach_cover_images


# 每類事件保留上限（資料庫）/ 精選
PER_CAT_DB = 25
TOP_PICKS = 3


def run(days_back: int = DEFAULT_DAYS_BACK,
        enable_google_news: bool = ENABLE_GOOGLE_NEWS_DEFAULT,
        only_kinds: set[str] | None = None) -> dict:
    today_date = date.today()
    today = today_date.isoformat()
    print(f"\n===== AI 事件爬搜 {today}（嚴格近 {days_back} 天）=====\n")

    # 1) 抓 RSS（fetch_rss 內部會用 cutoff = now - days_back；short window 時也丟無日期條目）
    items = fetch_all_sources(days_back=days_back, only_kinds=only_kinds)
    print(f"\nRSS 共 {len(items)} 則")

    # 2) Google News 補強（query 端帶 cutoff，pubDate 早於就丟）
    if enable_google_news:
        items.extend(google_news_supplement(days_back=days_back))

    # 2.5) 開源生態補強（嚴格 days_back；無 per-item 日期的整源略過）
    opensource_items = fetch_opensource_supplement(days_back=days_back)
    items.extend(opensource_items)
    print(f"開源生態補強：{len(opensource_items)} 則")

    # 3) 粗篩
    items = prefilter(items)
    print(f"AI 粗篩後：{len(items)} 則")

    # 4) URL 去重
    seen: set[str] = set()
    uniq: list[dict] = []
    for it in items:
        url = it.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        uniq.append(it)
    print(f"URL 去重後：{len(uniq)} 則新聞進入事件抽取階段")

    # 5) LLM 抽事件（一篇可展開為 0..N 個事件）
    raw_events = extract_events_from_items(uniq)

    # 6) 合併事件（fingerprint + LLM 邊界判定）
    print("事件合併中...")
    events = merge_events(raw_events)

    # 7) 品質過濾（含事件層時間 cutoff — when 欄位早於 cutoff 也丟）
    events = filter_events(events, days_back=days_back, today=today_date)

    # 8) 排序：依 importance 降序、其次 mention_count 降序
    events.sort(key=lambda e: (e.get("importance", 0), e.get("mention_count", 0)),
                reverse=True)

    # 按類別切：每類保留 PER_CAT_DB
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        by_cat[ev.get("category", "uncategorized")].append(ev)
    db_events: list[dict] = []
    top_events: list[dict] = []
    for cid in list(CATEGORIES.keys()) + ["uncategorized"]:
        rows = by_cat.get(cid, [])
        rows.sort(key=lambda e: (e.get("importance", 0), e.get("mention_count", 0)),
                  reverse=True)
        cat_db = rows[:PER_CAT_DB]
        cat_top = rows[:TOP_PICKS]
        db_events.extend(cat_db)
        top_events.extend(cat_top)
        if rows:
            label = CATEGORY_LABEL_BY_ID.get(cid, "未分類")
            print(f"    {label:14s}  共 {len(rows):3d} 個事件 → 保留 {len(cat_db):3d} / 精選 {len(cat_top)}")

    # 9) 封面圖（只給 top events）
    print(f"\n取得封面圖（共 {len(top_events)} 個精選事件）...")
    # cover_image 的 attach 函式以 item.url 抓 og:image；
    # 對事件，我們把第一個 source 的 url 暫存到 ev["url"] 給它用。
    for ev in top_events:
        if ev.get("sources"):
            ev["url"] = ev["sources"][0].get("url", "")
    attach_cover_images(top_events, today)
    # 同步封面到 db_events（同物件 by event_id）
    cover_by_id = {ev["event_id"]: ev.get("cover_image")
                   for ev in top_events if ev.get("event_id")}
    for ev in db_events:
        if ev.get("event_id") in cover_by_id and not ev.get("cover_image"):
            ev["cover_image"] = cover_by_id[ev["event_id"]]

    # 10) 輸出
    by_cat_label = defaultdict(int)
    for ev in db_events:
        by_cat_label[CATEGORY_LABEL_BY_ID.get(ev.get("category"), "未分類")] += 1

    json_top_path = OUTPUT_DIR / f"{today}_AI事件_精選.json"
    json_db_path = OUTPUT_DIR / f"{today}_AI事件_資料庫.json"
    xlsx_path = OUTPUT_DIR / f"{today}_AI事件_資料庫.xlsx"

    with json_top_path.open("w", encoding="utf-8") as f:
        json.dump({
            "date": today,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total": len(top_events),
            "events": top_events,
        }, f, ensure_ascii=False, indent=2)

    with json_db_path.open("w", encoding="utf-8") as f:
        json.dump({
            "date": today,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total": len(db_events),
            "by_category_label": dict(by_cat_label),
            "events": db_events,
        }, f, ensure_ascii=False, indent=2)

    # Excel：每行 = 一個事件，sources 拼成多行字串
    def _to_row(ev: dict) -> dict:
        srcs = ev.get("sources", [])
        sources_str = "\n".join(
            f"- {s.get('source_name','?')}: {s.get('url','')}" for s in srcs
        )
        return {
            "類別": CATEGORY_LABEL_BY_ID.get(ev.get("category"), "未分類"),
            "重要度": ev.get("importance", 0),
            "報導數": ev.get("mention_count", 1),
            "事件標題": ev.get("title", ""),
            "摘要": ev.get("summary", ""),
            "主體": "、".join(ev.get("who", [])),
            "動作": ev.get("what", ""),
            "時間": ev.get("when", ""),
            "地點": ev.get("where", ""),
            "證據來源": sources_str,
            "category_id": ev.get("category", ""),
        }

    df = pd.DataFrame([_to_row(ev) for ev in db_events])
    if df.empty:
        df = pd.DataFrame(columns=["類別", "重要度", "報導數", "事件標題", "摘要", "主體", "動作", "時間", "地點", "證據來源", "category_id"])

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.drop(columns="category_id", errors="ignore").to_excel(writer, sheet_name="全部事件", index=False)
        for cid, c in CATEGORIES.items():
            sub = df[df["category_id"] == cid]
            if len(sub):
                sub.drop(columns="category_id", errors="ignore").to_excel(writer,
                                                                          sheet_name=c["label"][:31],
                                                                          index=False)

    print(f"\n[done] 資料庫 JSON：{json_db_path}")
    print(f"[done] 精選 JSON：{json_top_path}")
    print(f"[done] Excel：{xlsx_path}")

    return {
        "date": today,
        "total_db": len(db_events),
        "total_top": len(top_events),
        "by_category": dict(by_cat_label),
        "output_db_json": str(json_db_path),
        "output_json": str(json_top_path),
        "output_xlsx": str(xlsx_path),
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AI 事件爬搜整理（事件中心）")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK)
    p.add_argument("--google", action="store_true",
                   help="啟用 Google News 即時搜尋補強")
    p.add_argument("--kinds", nargs="+",
                   choices=["media", "vendor", "community", "podcast"])
    args = p.parse_args()

    run(days_back=args.days,
        enable_google_news=args.google,
        only_kinds=set(args.kinds) if args.kinds else None)
