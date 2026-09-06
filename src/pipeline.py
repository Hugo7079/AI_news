"""
每日 AI新聞 pipeline（新聞中心）
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
import os
import time
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, CATEGORIES, CATEGORY_LABEL_BY_ID, DEFAULT_DAYS_BACK, ENABLE_GOOGLE_NEWS_DEFAULT
from fetcher import fetch_all_sources, google_news_supplement, prefilter
from sources_extra import fetch_opensource_supplement
from events import extract_events_from_items, merge_events, filter_events
from cover_image import attach_cover_images, prefill_og_covers
from enrich import generate_full_content


# 每類事件保留上限（資料庫）
PER_CAT_DB = 25
# 精選總數（跨所有分類合計），依 importance / mention_count 取前 N
TOP_PICKS_TOTAL = 6

# 全程時間預算（秒）。GitHub Actions 的 crawl job 硬上限是 90 分鐘，超過會被 cancel
# → 整份報表消失。這裡設一個較早的軟性 deadline：一旦跑到這個時間，最花時間的兩個
# 尾段階段（封面生圖、全文彙整）就只對「還沒處理到的事件」直接落 fallback / summary，
# 立刻收尾去寫 JSON/Excel/Firestore，確保永遠有完整輸出。可用環境變數覆寫。
DEADLINE_SECONDS = int(os.getenv("AINEWS_DEADLINE_SECONDS", str(72 * 60)))


def run(days_back: int = DEFAULT_DAYS_BACK,
        enable_google_news: bool = ENABLE_GOOGLE_NEWS_DEFAULT,
        only_kinds: set[str] | None = None) -> dict:
    # 採用台灣時間 (UTC+8) 作為當日基準，避免 GitHub Actions 運行於 UTC 時區造成的日期偏差
    tz_taiwan = timezone(timedelta(hours=8))
    today_date = datetime.now(tz_taiwan).date()
    today = today_date.isoformat()
    # 全程時間預算：超過就讓尾段昂貴階段快速收尾，確保 CI 不被 90 分鐘上限 cancel
    deadline = time.monotonic() + DEADLINE_SECONDS
    print(f"\n===== AI新聞爬搜 {today}（嚴格近 {days_back} 天）=====")
    print(f"（時間預算 {DEADLINE_SECONDS // 60} 分鐘；超過則封面/全文改用 fallback 快速收尾）\n")

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

    # 按類別切：每類保留 PER_CAT_DB（資料庫只受每類上限影響）
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        by_cat[ev.get("category", "uncategorized")].append(ev)
    db_events: list[dict] = []
    for cid in list(CATEGORIES.keys()) + ["uncategorized"]:
        rows = by_cat.get(cid, [])
        rows.sort(key=lambda e: (e.get("importance", 0), e.get("mention_count", 0)),
                  reverse=True)
        cat_db = rows[:PER_CAT_DB]
        db_events.extend(cat_db)
        if rows:
            label = CATEGORY_LABEL_BY_ID.get(cid, "未分類")
            print(f"    {label:14s}  共 {len(rows):3d} 個事件 → 保留 {len(cat_db):3d}")

    # 精選：跨類別合計取 Top N（依 importance / mention_count 全域排序）
    db_sorted = sorted(db_events,
                       key=lambda e: (e.get("importance", 0), e.get("mention_count", 0)),
                       reverse=True)
    top_events: list[dict] = db_sorted[:TOP_PICKS_TOTAL]
    print(f"    今日精選           合計 {len(top_events)} / 上限 {TOP_PICKS_TOTAL}（跨類別 importance 排序）")

    # 9) 封面圖（給所有 db_events — PDF 報表每一則都要有文生圖封面）
    remaining = deadline - time.monotonic()
    print(f"\n用文生圖模型產生封面（共 {len(db_events)} 個事件；剩餘時間預算 {remaining/60:.1f} 分）...")
    # _build_image_prompt 用 title/summary 當提示；url 僅作為檔名 seed。
    for ev in db_events:
        if ev.get("sources"):
            ev["url"] = ev["sources"][0].get("url", "")
    # 先抓文章原圖，剩下的才生圖 —— 生圖額度與其他專案共用，不能整鍋吃光
    prefill_og_covers(db_events)
    attach_cover_images(db_events, today, deadline=deadline)

    # 9.5) 全文彙整（LLM 把每個事件擴寫成多段內文，供 PDF 報表細節區）
    #      只對保留下來的 db_events 產生（top_events 為其子集、同物件）。
    generate_full_content(db_events, deadline=deadline)

    # 9.9) 品質檢查：電子報每一則都該有「真圖 + 比 summary 長的 full_content」。
    #      不達標就在 log 警示（不 raise，避免 CI 失敗反而不出報）。
    real_imgs = sum(1 for ev in db_events
                    if (ev.get("cover_image") or {}).get("kind") in ("local", "remote"))
    bad_full = []
    for ev in db_events:
        fc = (ev.get("full_content") or "").strip()
        sm = (ev.get("summary") or "").strip()
        if not fc or fc == sm or len(fc) < max(80, len(sm) * 1.3):
            bad_full.append(ev.get("title", "?")[:30])
    print(f"\n[quality] 真圖 {real_imgs}/{len(db_events)}  全文良好 {len(db_events)-len(bad_full)}/{len(db_events)}")
    if len(db_events) and real_imgs / len(db_events) < 0.8:
        print(f"  [quality WARN] 真圖比例 {real_imgs/len(db_events):.0%} < 80% — gateway 可能不穩")
    if bad_full:
        print(f"  [quality WARN] {len(bad_full)} 則 full_content 過短或等於 summary：")
        for t in bad_full[:5]:
            print(f"      - {t}")

    # 10) 輸出
    by_cat_label = defaultdict(int)
    for ev in db_events:
        by_cat_label[CATEGORY_LABEL_BY_ID.get(ev.get("category"), "未分類")] += 1

    json_top_path = OUTPUT_DIR / f"{today}_AI新聞_精選.json"
    json_db_path = OUTPUT_DIR / f"{today}_AI新聞_資料庫.json"
    xlsx_path = OUTPUT_DIR / f"{today}_AI新聞_資料庫.xlsx"

    generated_at_str = datetime.now(tz_taiwan).isoformat(timespec="seconds")

    with json_top_path.open("w", encoding="utf-8") as f:
        json.dump({
            "date": today,
            "generated_at": generated_at_str,
            "total": len(top_events),
            "events": top_events,
        }, f, ensure_ascii=False, indent=2)

    with json_db_path.open("w", encoding="utf-8") as f:
        json.dump({
            "date": today,
            "generated_at": generated_at_str,
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

    # 11) 寫入資料庫（失敗不阻斷本地輸出）
    #
    #   AINEWS_STORE=local      只寫本地 store（output/store/*.json）— Docker 自架用
    #   AINEWS_STORE=firestore  只寫 Firestore（預設，維持 GitHub Actions 的行為）
    #   AINEWS_STORE=both       兩邊都寫
    #   舊的 AINEWS_SKIP_FIRESTORE=1 仍有效，等同 AINEWS_STORE=local
    skip_fs = os.getenv("AINEWS_SKIP_FIRESTORE", "").strip().lower() in ("1", "true", "yes")
    store = os.getenv("AINEWS_STORE", "").strip().lower()
    if store not in ("local", "firestore", "both"):
        store = "local" if skip_fs else "firestore"

    if store in ("local", "both"):
        try:
            from local_store import write_run as local_write
            local_write(today, db_events, top_events, dict(by_cat_label))
        except Exception as e:
            print(f"[local-store] 寫入失敗（本地 JSON 已完成）：{type(e).__name__}: {e}")

    if store in ("firestore", "both") and not skip_fs:
        try:
            from firestore_writer import write_run as firestore_write
            firestore_write(today, db_events, top_events, dict(by_cat_label))
        except Exception as e:
            print(f"[firestore] 寫入失敗（本地輸出已完成）：{type(e).__name__}: {e}")

    covers_ok = sum(1 for e in db_events
                    if isinstance(e.get("cover_image"), dict)
                    and e["cover_image"].get("kind") in ("remote", "local")
                    and e["cover_image"].get("url"))

    return {
        "date": today,
        "total_db": len(db_events),
        "total_top": len(top_events),
        "covers_ok": covers_ok,
        "by_category": dict(by_cat_label),
        "output_db_json": str(json_db_path),
        "output_json": str(json_top_path),
        "output_xlsx": str(xlsx_path),
    }


def _require_llm_key() -> None:
    """
    開跑前確認 LLM「有金鑰」而且「金鑰真的能用」。

    只檢查有沒有金鑰是不夠的 —— 2026-09-05 那天就是金鑰還在、但配額被降成 0
    （429 且 x-ratelimit-limit-req-minute: 0）。每一次抽事件都失敗，pipeline
    照樣跑完、exit 0、Actions 一片綠，最後寫進去 0 則。
    故障看起來跟「今天真的沒新聞」一模一樣，這種沉默失敗最難發現。
    """
    import json
    import urllib.error
    import urllib.request
    from config import LLM_CFG

    if not LLM_CFG.get("api_key"):
        raise SystemExit(
            "[錯誤] 找不到 LLM API key。\n"
            "  Docker  : 在專案根目錄的 .env 設定 AINEWS_LLM_API_KEY（可從 .env.example 複製）\n"
            "  本機開發: 設環境變數 AINEWS_LLM_API_KEY，或建立 .ainews_llm_config.json\n"
            "  Actions : 在 workflow 的 env / repository secrets 設定"
        )

    base = LLM_CFG["base_url"].rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps({
            "model": LLM_CFG["model"],
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {LLM_CFG['api_key']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45):
            return
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:200]
        hint = ""
        if e.code == 429:
            limit = e.headers.get("x-ratelimit-limit-req-minute")
            if limit == "0":
                hint = ("\n  這把金鑰的每分鐘配額是 0 —— 不是用量爆掉，"
                        "是這個帳號當下根本不被允許發請求。要去服務商後台看方案狀態。")
            else:
                hint = "\n  被限流。稍後再跑，或降低 AINEWS_LLM_RPM。"
        elif e.code in (401, 403):
            hint = "\n  金鑰無效或沒有這個模型的權限。"
        raise SystemExit(
            f"[錯誤] LLM 連線測試失敗：HTTP {e.code}\n"
            f"  端點：{base}\n  模型：{LLM_CFG['model']}\n"
            f"  回應：{detail}{hint}\n"
            f"  先停在這裡，不要抓完一整輪才發現每則都抽不出事件。"
        ) from e
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            f"[錯誤] LLM 連線測試失敗：{type(e).__name__}: {e}\n  端點：{base}"
        ) from e


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AI新聞爬搜整理（新聞中心）")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK)
    p.add_argument("--google", action="store_true",
                   help="啟用 Google News 即時搜尋補強")
    p.add_argument("--kinds", nargs="+",
                   choices=["media", "vendor", "community", "podcast"])
    args = p.parse_args()
    _require_llm_key()

    result = run(days_back=args.days,
                 enable_google_news=args.google,
                 only_kinds=set(args.kinds) if args.kinds else None)

    # 收尾檢查 —— 沉默地產出空白比直接失敗更糟：
    # 故障看起來會跟「今天真的沒新聞」一模一樣，網站照樣顯示、沒人會發現。
    # 2026-09-05 那天就是這樣：排程成功、Actions 綠燈、網站 0 則。
    problems = []
    if result["total_db"] == 0:
        problems.append("事件數 0 —— 正常日子不可能沒有新聞，這一定是故障")
    if result["total_db"] and result["covers_ok"] == 0:
        problems.append(f"{result['total_db']} 則事件全部沒有封面圖 —— "
                        f"生圖後端多半掛了（額度用盡或金鑰失效）")

    if problems:
        print("\n[失敗] 這次執行的產出不可用：")
        for x in problems:
            print(f"  ‣ {x}")
        raise SystemExit(1)

    print(f"\n[ok] {result['date']}：事件 {result['total_db']} 則 / "
          f"精選 {result['total_top']} 則 / 有封面 {result['covers_ok']} 則")
