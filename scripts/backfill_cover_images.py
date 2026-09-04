"""
回填封面圖到既有 Firestore events
==================================

pipeline 只在當天跑的時候生圖；封面後端換掉（或壞掉）期間留下的事件會一直是
fallback 底圖。這支只補圖、不重跑整個 pipeline。

生圖後端沿用 src/cover_image.py 的設定（AINEWS_IMAGE_BACKEND），預設是
Cloudflare Workers AI 的 FLUX.1 [schnell]。

⚠ 免費額度：Cloudflare 每天 10,000 neurons（以 UTC 日計），一張約 83。
   每天的排程跑在 UTC 20:40，跟台灣白天的手動補圖是**同一個 UTC 日** ——
   補太多會把排程的額度吃光，隔天早上整份報表就都是 fallback 底圖。
   所以預設會自動限制張數並替排程留 6,000 neurons，不必自己算。

用法：
  # 補最近 14 天（自動限制在安全張數內，跑幾天就補完了）
  python scripts/backfill_cover_images.py --days 14 --yes

  # 只補某一天
  python scripts/backfill_cover_images.py --date 2026-08-28

  # 先試 3 張看看成品
  python scripts/backfill_cover_images.py --date 2026-08-28 --limit 3

  # 連已經有圖的也重生
  python scripts/backfill_cover_images.py --date 2026-08-28 --force

  # 確定今晚排程已經跑完，把剩餘額度全用掉
  python scripts/backfill_cover_images.py --days 14 --no-reserve --yes
"""

from __future__ import annotations
import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import firestore_writer as fw
import r2_storage
from cover_image import (_build_image_prompt, _cf_generate, _gateway_generate,
                         cf_quota_exhausted,
                         _hf_generate, _load_hf_token, check_cf_config, verify_cf_token, image_ext,
                         postprocess_cover)
from config import OUTPUT_DIR, IMAGE_CFG

# 實測值：2026-09-01 跑了 121 張就把 10,000 neurons 用完 → 約 82/張。
# （官方計價表推算是 4 tiles × 4.80 + 4 steps × 9.60 = 57.6，但實際更高，
#  所以這裡用實測數字抓，寧可保守。）
NEURONS_PER_IMAGE = 83.0
CF_DAILY_FREE_NEURONS = 10_000
# 每天留給排程的額度。排程跑在 UTC 20:40（台灣隔天 04:40），跟台灣白天的
# 手動補圖是同一個 UTC 日 —— 不留量的話白天補圖會把隔天早上的圖吃光。
CF_RESERVE_FOR_CRON = 6_000


def _today_taiwan() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _short_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def _pick_generator():
    """依 IMAGE_CFG['backend'] 決定生圖函式；回傳 (fn, 標籤)。"""
    backend = (IMAGE_CFG.get("backend") or "cloudflare").lower()
    if backend == "cloudflare":
        # 先本地檢查格式，再跟 Cloudflare 確認 token 真的有效 ——
        # 憑證錯的話一張都不要開始跑
        problem = verify_cf_token()
        if problem:
            sys.exit(f"Cloudflare 設定有問題：{problem}")
        return _cf_generate, f"Cloudflare {IMAGE_CFG.get('cf_model')}"
    if backend == "gateway":
        if not IMAGE_CFG.get("api_key"):
            sys.exit("backend=gateway 但沒有 API key")
        return _gateway_generate, f"d8ai gateway {IMAGE_CFG.get('model')}"
    if backend == "hf":
        tok = _load_hf_token()
        if not tok:
            sys.exit("backend=hf 但沒有 HF_TOKEN")
        return (lambda p: _hf_generate(p, tok)), "HuggingFace FLUX"
    sys.exit(f"未知的 AINEWS_IMAGE_BACKEND：{backend}")


def _needs_cover(ev: dict, force: bool) -> bool:
    if force:
        return True
    cover = ev.get("cover_image") or {}
    return cover.get("kind") not in ("remote", "local") or not cover.get("url")


def _collect(db, dates: list[str], top: int, force: bool, limit: int):
    """回傳 [(date, doc_id, event)]，每天依重要度取前 top 則。"""
    jobs = []
    for d in dates:
        docs = list(db.collection("events").where("date", "==", d).stream())
        rows = [(doc.id, doc.to_dict() or {}) for doc in docs]
        pending = [(i, ev) for i, ev in rows if _needs_cover(ev, force)]
        # 重要度高、被報導多的優先 —— 頭版與電子報用得到的就是這些
        pending.sort(key=lambda t: (t[1].get("importance", 0), t[1].get("mention_count", 0)),
                     reverse=True)
        if top:
            pending = pending[:top]
        print(f"  {d}：{len(rows):3d} 則，待補 {len(pending):3d}")
        jobs.extend((d, doc_id, ev) for doc_id, ev in pending)
    if limit and len(jobs) > limit:
        jobs = jobs[:limit]
        print(f"--limit：只處理前 {len(jobs)} 張")
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="只處理某一天（YYYY-MM-DD）")
    ap.add_argument("--days", type=int, default=0,
                    help="從今天往回算 N 天（與 --date 二選一）")
    ap.add_argument("--top", type=int, default=0,
                    help="每天最多補幾則（依重要度排序，0=不限）")
    ap.add_argument("--limit", type=int, default=0,
                    help="總張數上限。不給的話自動用安全上限（見 --no-reserve）")
    ap.add_argument("--no-reserve", action="store_true",
                    help="不保留排程用的額度，把當日剩餘額度全部用掉。"
                         "只有確定今晚排程已經跑完才該用")
    ap.add_argument("--force", action="store_true", help="連已有圖的也重生")
    ap.add_argument("--yes", action="store_true", help="不詢問直接開跑")
    args = ap.parse_args()

    generate, backend_label = _pick_generator()

    # 上傳目的地也先檢查 —— 生完圖才發現傳不上去最浪費
    if r2_storage.is_configured():
        problem = r2_storage.check_config()
        if problem:
            sys.exit(f"R2 設定有問題：{problem}")
        if not r2_storage.ensure_bucket():
            sys.exit("R2 bucket 不可用，先處理再重跑。")
        store_label = f"Cloudflare R2 ({r2_storage.config()['bucket']})"
    else:
        store_label = "Firebase Storage（需要 Blaze 方案）"

    # 預設就替排程留量。之前只是「印出建議」，沒加 --limit 就會照跑，
    # 結果補圖把當晚排程的額度吃光、隔天早上整份報表都是 fallback 底圖。
    # 現在把安全的做法變成預設，要覆寫得明講。
    reserve_cap = int((CF_DAILY_FREE_NEURONS - CF_RESERVE_FOR_CRON) // NEURONS_PER_IMAGE)
    auto_limited = False
    if (backend_label.startswith("Cloudflare") and not args.no_reserve
            and (args.limit == 0 or args.limit > reserve_cap)):
        args.limit = reserve_cap
        auto_limited = True

    if args.days:
        today = datetime.now(timezone(timedelta(hours=8))).date()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(args.days)]
    else:
        dates = [args.date or _today_taiwan()]

    fw._init()
    db = fw._db
    col = db.collection("events")

    print(f"生圖：{backend_label}")
    print(f"儲存：{store_label}")
    print(f"掃描 {len(dates)} 天：")
    jobs = _collect(db, dates, args.top, args.force, args.limit)

    if not jobs:
        print("\n沒有需要補圖的事件。")
        return

    est = len(jobs) * NEURONS_PER_IMAGE
    print(f"\n總計要生 {len(jobs)} 張")
    if backend_label.startswith("Cloudflare"):
        print(f"預估耗用 {est:,.0f} neurons"
              f"（每日免費額度 {CF_DAILY_FREE_NEURONS:,}，約占 {est / CF_DAILY_FREE_NEURONS:.0%}）")
        if auto_limited:
            print(f"  已自動限制為 {reserve_cap} 張 —— 排程跑在 UTC 20:40，跟你現在"
                  f"是同一個 UTC 日，要留 {CF_RESERVE_FOR_CRON:,} neurons 給它，"
                  f"否則隔天早上整份報表都會是 fallback 底圖。\n"
                  f"  （確定今晚排程已經跑完了才用 --no-reserve 解除）")
        elif args.no_reserve:
            print("  --no-reserve：不留額度給排程")

    if not args.yes:
        try:
            if input("繼續？[y/N] ").strip().lower() not in ("y", "yes"):
                print("取消。")
                return
        except EOFError:
            print("\n非互動環境，請加 --yes。")
            return

    ok = fail = 0
    consecutive_fail = 0
    # 憑證錯的話每一張都會失敗，而且每張失敗前都先燒一次 LLM 呼叫去產視覺提示。
    # 連續失敗就停手，不要把整批額度浪費在同一個設定錯誤上。
    ABORT_AFTER = 3

    for i, (date_str, doc_id, ev) in enumerate(jobs, 1):
        title = (ev.get("title") or "")[:36]
        print(f"[{i}/{len(jobs)}] {date_str} {title}", flush=True)

        img_dir = OUTPUT_DIR / "images" / date_str
        img_dir.mkdir(parents=True, exist_ok=True)

        prompt = _build_image_prompt(
            ev.get("title", ""),
            ev.get("summary", ""),
            ev.get("category", "uncategorized"),
        )
        t0 = time.monotonic()
        img_bytes = generate(prompt)
        dt = time.monotonic() - t0
        if not img_bytes:
            print(f"  [skip] 生圖失敗 ({dt:.1f}s)", flush=True)
            fail += 1
            consecutive_fail += 1
            if cf_quota_exhausted():
                print(f"\n[abort] Cloudflare 當日免費額度已用完 —— "
                      f"UTC 隔日 00:00（台灣早上 8 點）重置後再跑同一行即可續補。\n"
                      f"        本次已完成 {ok} 張。")
                break
            if consecutive_fail >= ABORT_AFTER:
                print(f"\n[abort] 連續 {ABORT_AFTER} 張生圖失敗 —— 多半是設定問題"
                      f"（account id / token / 模型名稱），先修好再重跑。\n"
                      f"        已完成的不會重做，直接重跑同一行指令即可續補。")
                break
            continue
        consecutive_fail = 0

        img_bytes = postprocess_cover(img_bytes)
        seed = (ev.get("sources") or [{}])[0].get("url", "") or ev.get("title", "") or doc_id
        fname = f"{_short_id(seed)}.{image_ext(img_bytes)}"
        fpath = img_dir / fname
        fpath.write_bytes(img_bytes)

        public_url = fw._upload_cover(f"images/{date_str}/{fname}", date_str)
        if not public_url:
            print("  [skip] Storage 上傳失敗", flush=True)
            fail += 1
            continue

        col.document(doc_id).update({"cover_image": {"kind": "remote", "url": public_url}})
        ok += 1
        print(f"  [ok] {dt:.1f}s → {public_url[:76]}", flush=True)

    print(f"\n[done] 成功 {ok} / 失敗 {fail}（共 {len(jobs)}）")
    if ok and backend_label.startswith("Cloudflare"):
        print(f"本次約耗用 {ok * NEURONS_PER_IMAGE:,.0f} neurons")


if __name__ == "__main__":
    main()
