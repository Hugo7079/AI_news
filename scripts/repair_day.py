"""
一鍵修復某一天的 Firestore 電子報資料
=====================================

同時補兩件事，讓電子報每一則都完整：
  1. full_content 缺失/太短/等於 summary → 重新用 LLM 生成
  2. cover_image 不是真圖（fallback）→ 用文生圖模型重生（順序 + 重試）

用法：
  python scripts/repair_day.py                      # 修今天，只補缺的
  python scripts/repair_day.py --date 2026-06-15
  python scripts/repair_day.py --force-image         # 連已有圖的也用新 prompt 重生
  python scripts/repair_day.py --only image|text     # 只修一種
  python scripts/repair_day.py --limit 5             # 測試
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
from cover_image import _gateway_generate, _build_image_prompt
from enrich import _generate_one, _is_good
from config import OUTPUT_DIR


def _today_taiwan() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _short_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def _needs_text(ev: dict) -> bool:
    fc = (ev.get("full_content") or "").strip()
    sm = (ev.get("summary") or "").strip()
    return not _is_good(fc, sm)


def _needs_image(ev: dict, force: bool) -> bool:
    if force:
        return True
    cover = ev.get("cover_image") or {}
    return cover.get("kind") != "remote" or not cover.get("url")


def _fix_text(col, doc_id: str, ev: dict) -> bool:
    """就地重生 full_content 並寫回 Firestore。回傳是否成功。"""
    ev.pop("full_content", None)  # 強制重生
    _generate_one(ev)             # enrich 內含品質驗證 + 重試
    fc = ev.get("full_content", "")
    if _is_good(fc, ev.get("summary", "")):
        col.document(doc_id).update({"full_content": fc})
        return True
    # 仍不合格也寫回（至少有 summary 當底），但回報失敗
    if fc:
        col.document(doc_id).update({"full_content": fc})
    return False


def _fix_image(col, doc_id: str, ev: dict, date_str: str, img_dir: Path) -> bool:
    prompt = _build_image_prompt(
        ev.get("title", ""), ev.get("summary", ""), ev.get("category", "uncategorized")
    )
    img_bytes = _gateway_generate(prompt)
    if not img_bytes:
        return False
    seed = (ev.get("sources", [{}]) or [{}])[0].get("url", "") or ev.get("title", "") or doc_id
    fname = f"{_short_id(seed)}.png"
    fpath = img_dir / fname
    fpath.write_bytes(img_bytes)
    public_url = fw._upload_cover(f"images/{date_str}/{fname}", date_str)
    if not public_url:
        return False
    col.document(doc_id).update({"cover_image": {"kind": "remote", "url": public_url}})
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=_today_taiwan())
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force-image", action="store_true", help="連已有圖的也重生（換新 prompt）")
    ap.add_argument("--only", choices=["image", "text"], help="只修一種")
    args = ap.parse_args()

    fw._init()
    db = fw._db
    col = db.collection("events")
    docs = list(col.where("date", "==", args.date).stream())
    print(f"Firestore events {args.date}：共 {len(docs)} 筆")

    do_text = args.only != "image"
    do_image = args.only != "text"

    rows = [(d.id, d.to_dict() or {}) for d in docs]
    if args.limit:
        rows = rows[: args.limit]

    text_targets = [r for r in rows if do_text and _needs_text(r[1])]
    image_targets = [r for r in rows if do_image and _needs_image(r[1], args.force_image)]
    print(f"待補：full_content {len(text_targets)} 筆 / 封面圖 {len(image_targets)} 筆")

    img_dir = OUTPUT_DIR / "images" / args.date
    img_dir.mkdir(parents=True, exist_ok=True)

    # ── 文字 ──
    if text_targets:
        print(f"\n=== 補 full_content（{len(text_targets)} 筆）===")
        ok = 0
        for i, (doc_id, ev) in enumerate(text_targets, 1):
            good = _fix_text(col, doc_id, ev)
            ok += int(good)
            flag = "ok" if good else "weak"
            print(f"  [{i}/{len(text_targets)}] [{flag}] {ev.get('title','')[:34]}", flush=True)
        print(f"  full_content 完成：合格 {ok}/{len(text_targets)}")

    # ── 圖片（順序 + 多輪重試掃尾）──
    if image_targets:
        print(f"\n=== 重生封面圖（{len(image_targets)} 筆，順序）===")
        pending = list(image_targets)
        for round_no in range(1, 4):  # 最多 3 輪
            if not pending:
                break
            if round_no > 1:
                print(f"  --- 第 {round_no} 輪重試：{len(pending)} 筆待補 ---")
            still = []
            for i, (doc_id, ev) in enumerate(pending, 1):
                t0 = time.monotonic()
                good = _fix_image(col, doc_id, ev, args.date, img_dir)
                dt = time.monotonic() - t0
                tag = "ok" if good else "FAIL"
                print(f"  [{i}/{len(pending)}] [{tag}] {dt:.0f}s {ev.get('title','')[:30]}", flush=True)
                if not good:
                    still.append((doc_id, ev))
                else:
                    time.sleep(0.5)
            pending = still
            if pending:
                print(f"  本輪後仍有 {len(pending)} 筆失敗，等 30s 再重試...")
                time.sleep(30)
        done = len(image_targets) - len(pending)
        print(f"  封面圖完成：成功 {done}/{len(image_targets)}"
              + (f"，仍失敗 {len(pending)}" if pending else ""))

    print("\n[repair] 完成。")


if __name__ == "__main__":
    main()
