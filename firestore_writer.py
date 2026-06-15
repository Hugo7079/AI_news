"""
Firestore writer — 把每日 pipeline 跑出來的事件寫進 Firebase
=============================================================

Schema:
  events/{date}_{event_id}        每個事件一筆，含 sources / cover_image
  daily_summary/{date}            當日彙總（總數、分類分布、產生時間）

封面圖：
  - kind == "remote"   → 直接保留外站 URL
  - kind == "local"    → 把 output/images/{date}/{file} 上傳到 Firebase Storage
                         並改成 public download URL
  - kind == "fallback" → 不上傳，前端依 category 自畫色塊

憑證載入順序：
  1. GOOGLE_APPLICATION_CREDENTIALS 環境變數 → service account JSON 路徑
  2. FIREBASE_SERVICE_ACCOUNT_JSON 環境變數 → 整段 JSON 字串（CI/GitHub Actions 用）
  3. 本機 firebase-credentials.json（在 .gitignore 裡）
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import BASE_DIR, OUTPUT_DIR, CATEGORY_LABEL_BY_ID

FIREBASE_PROJECT_ID = "d8ainews"
FIREBASE_STORAGE_BUCKET = "d8ainews.firebasestorage.app"


_app = None
_db = None
_bucket = None


def _load_credentials():
    from firebase_admin import credentials

    env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if env_path and Path(env_path).exists():
        return credentials.Certificate(env_path)

    raw_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw_json:
        data = json.loads(raw_json)
        return credentials.Certificate(data)

    local_path = BASE_DIR / "firebase-credentials.json"
    if local_path.exists():
        return credentials.Certificate(str(local_path))

    raise RuntimeError(
        "找不到 Firebase service account 憑證。請設定 GOOGLE_APPLICATION_CREDENTIALS "
        "或 FIREBASE_SERVICE_ACCOUNT_JSON，或把 firebase-credentials.json 放在專案根目錄。"
    )


def _init():
    global _app, _db, _bucket
    if _app is not None:
        return
    import firebase_admin
    from firebase_admin import firestore, storage

    cred = _load_credentials()
    _app = firebase_admin.initialize_app(cred, {
        "projectId": FIREBASE_PROJECT_ID,
        "storageBucket": FIREBASE_STORAGE_BUCKET,
    })
    _db = firestore.client()
    _bucket = storage.bucket()


def _upload_cover(local_rel_url: str, date_str: str, overwrite: bool = True) -> Optional[str]:
    """把 output/images/{date}/{file} 上傳到 Storage，回傳 public URL。

    overwrite=True（預設）：永遠重新上傳本地檔。
      封面圖檔名是來源 URL 的 hash（固定）。若沿用「blob 已存在就跳過」的舊邏輯，
      重生（換 prompt）後的新圖會因同名舊 blob 仍在而不上傳，Storage 還是舊圖 —
      這正是「圖重生了但畫面還是有亂碼文字」的元兇。
    """
    local_path = OUTPUT_DIR / local_rel_url
    if not local_path.exists():
        # 有時候 cover_image.url 已經是 "images/YYYY-MM-DD/xxx.png" 相對路徑
        alt = OUTPUT_DIR / local_rel_url.lstrip("/")
        if alt.exists():
            local_path = alt
        else:
            print(f"  [storage] 找不到本地封面圖：{local_rel_url}")
            return None

    blob_name = f"covers/{date_str}/{local_path.name}"
    blob = _bucket.blob(blob_name)
    if overwrite or not blob.exists():
        blob.upload_from_filename(str(local_path), content_type="image/png")
    blob.make_public()
    return blob.public_url


def _normalize_cover(ev: dict, date_str: str) -> dict:
    cover = ev.get("cover_image")
    if not isinstance(cover, dict):
        return {"kind": "fallback", "category": ev.get("category", "uncategorized")}

    kind = cover.get("kind")
    if kind == "remote":
        return {"kind": "remote", "url": cover.get("url", "")}
    if kind == "local":
        public_url = _upload_cover(cover.get("url", ""), date_str)
        if public_url:
            return {"kind": "remote", "url": public_url}
        return {"kind": "fallback", "category": ev.get("category", "uncategorized")}
    return {"kind": "fallback", "category": ev.get("category", "uncategorized")}


def _event_to_doc(ev: dict, date_str: str, is_top: bool) -> dict:
    """事件 dict → Firestore document（純 JSON-safe 結構）。"""
    return {
        "event_id":       ev.get("event_id", ""),
        "date":           date_str,
        "title":          ev.get("title", ""),
        "summary":        ev.get("summary", ""),
        "full_content":   ev.get("full_content", ""),
        "category":       ev.get("category", "uncategorized"),
        "category_label": CATEGORY_LABEL_BY_ID.get(ev.get("category"), "未分類"),
        "importance":     int(ev.get("importance", 0) or 0),
        "mention_count":  int(ev.get("mention_count", 1) or 1),
        "who":            list(ev.get("who", []) or []),
        "what":           ev.get("what", ""),
        "when":           ev.get("when", ""),
        "where":          ev.get("where", ""),
        "sources":        [
            {
                "url":            s.get("url", ""),
                "title":          s.get("title", ""),
                "source_name":    s.get("source_name", ""),
                "source_kind":    s.get("source_kind", ""),
                "published":      s.get("published", ""),
                # 開源生態欄位（HF / GitHub / Ollama / OpenRouter 才有）
                "is_opensource":  bool(s.get("is_opensource", False)),
                "stars":          s.get("stars", "") or "",
                "pulls":          s.get("pulls", "") or "",
                "downloads":      int(s.get("downloads", 0) or 0),
                "likes":          int(s.get("likes", 0) or 0),
                "upvotes":        int(s.get("upvotes", 0) or 0),
                "context_length": int(s.get("context_length", 0) or 0),
                "task":           s.get("task", "") or "",
                "pricing":        s.get("pricing", {}) or {},
            }
            for s in (ev.get("sources") or [])
        ],
        "cover_image":    _normalize_cover(ev, date_str),
        "is_top":         bool(is_top),
        "generated_at":   datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def write_run(date_str: str,
              db_events: list[dict],
              top_events: list[dict],
              by_category_label: dict[str, int]) -> None:
    """主入口：把當日 pipeline 結果寫進 Firestore。"""
    _init()
    print(f"\n[firestore] 寫入 {date_str}：DB {len(db_events)} / Top {len(top_events)}")

    top_ids = {ev.get("event_id") for ev in top_events if ev.get("event_id")}

    batch = _db.batch()
    written = 0
    for ev in db_events:
        eid = ev.get("event_id")
        if not eid:
            continue
        doc_id = f"{date_str}_{eid}"
        doc = _event_to_doc(ev, date_str, is_top=eid in top_ids)
        batch.set(_db.collection("events").document(doc_id), doc)
        written += 1
        # Firestore batch 上限 500，分批 commit
        if written % 400 == 0:
            batch.commit()
            batch = _db.batch()

    batch.commit()

    summary_doc = {
        "date":               date_str,
        "total_db":           len(db_events),
        "total_top":          len(top_events),
        "by_category_label":  dict(by_category_label),
        "generated_at":       datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    _db.collection("daily_summary").document(date_str).set(summary_doc)
    print(f"[firestore] 完成 — events {written} 筆 / daily_summary/{date_str}")
