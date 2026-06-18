"""一次性：用新的無文字 prompt 重生某天 is_top 事件的封面圖並更新 Firestore。
用法： python scripts/regen_top.py --date 2026-06-18
"""
from __future__ import annotations
import argparse, hashlib, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firestore_writer as fw
from cover_image import _gateway_generate, _build_image_prompt
from config import OUTPUT_DIR


def _short_id(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    args = ap.parse_args()
    date = args.date

    fw._init()
    col = fw._db.collection("events")
    rows = [(d.id, d.to_dict() or {}) for d in col.where("date", "==", date).stream()]
    tops = [(i, e) for i, e in rows if e.get("is_top")]
    print(f"{date} is_top：{len(tops)} 則待重生", flush=True)

    img_dir = OUTPUT_DIR / "images" / date
    img_dir.mkdir(parents=True, exist_ok=True)

    pending = list(tops)
    for round_no in range(1, 5):
        if not pending:
            break
        if round_no > 1:
            print(f"--- 第 {round_no} 輪：{len(pending)} 則待補 ---", flush=True)
        still = []
        for doc_id, ev in pending:
            t0 = time.monotonic()
            prompt = _build_image_prompt(ev.get("title", ""), ev.get("summary", ""),
                                         ev.get("category", "uncategorized"))
            img = _gateway_generate(prompt)
            if not img:
                still.append((doc_id, ev))
                print(f"  [FAIL] {ev.get('category')} | {ev.get('title','')[:28]}", flush=True)
                continue
            seed = (ev.get("sources", [{}]) or [{}])[0].get("url", "") or ev.get("title", "") or doc_id
            fname = f"{_short_id(seed)}.png"
            (img_dir / fname).write_bytes(img)
            url = fw._upload_cover(f"images/{date}/{fname}", date)
            if not url:
                still.append((doc_id, ev))
                print(f"  [UPLOAD-FAIL] {ev.get('title','')[:28]}", flush=True)
                continue
            col.document(doc_id).update({"cover_image": {"kind": "remote", "url": url}})
            dt = time.monotonic() - t0
            print(f"  [OK] {dt:.0f}s {ev.get('category')} | {fname} | {ev.get('title','')[:26]}", flush=True)
            time.sleep(0.5)
        pending = still
        if pending:
            print(f"  本輪後仍 {len(pending)} 失敗，等 20s...", flush=True)
            time.sleep(20)

    print(f"完成：成功 {len(tops) - len(pending)}/{len(tops)}"
          + (f"，仍失敗 {len(pending)}" if pending else ""), flush=True)


if __name__ == "__main__":
    main()
