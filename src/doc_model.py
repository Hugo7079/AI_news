"""
事件文件模型（Firestore / 本地 store 共用）
==========================================

pipeline 跑出來的 event dict 欄位比較鬆散，這裡統一收斂成一份「文件」結構，
Firestore 與本地 JSON store 都用同一份，前端就不必分辨資料來自哪裡。

封面圖的處理方式由呼叫端決定（cover_resolver）：
  - Firestore：把 output/images/... 上傳到 Storage，換成 public URL
  - 本地 store：原樣保留 {"kind": "local", "url": "images/{date}/{file}"}
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Callable

from config import CATEGORY_LABEL_BY_ID
from tags import TAGS_VERSION, normalize_tags

# cover_resolver(event, date_str) -> cover_image dict
CoverResolver = Callable[[dict, str], dict]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def keep_cover(ev: dict, date_str: str) -> dict:
    """本地 store 用：原樣保留封面資訊（相對路徑之後由 server 轉成 /media/...）。"""
    cover = ev.get("cover_image")
    if not isinstance(cover, dict):
        return {"kind": "fallback", "category": ev.get("category", "uncategorized")}
    kind = cover.get("kind")
    if kind in ("remote", "local") and cover.get("url"):
        return {"kind": kind, "url": cover.get("url", "")}
    return {"kind": "fallback", "category": ev.get("category", "uncategorized")}


def source_to_doc(s: dict) -> dict:
    return {
        "url":            s.get("url", ""),
        "title":          s.get("title", ""),
        "source_name":    s.get("source_name", ""),
        "source_kind":    s.get("source_kind", ""),
        "source_region":  s.get("source_region", ""),
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


def event_to_doc(ev: dict, date_str: str, is_top: bool,
                 cover_resolver: CoverResolver = keep_cover) -> dict:
    """事件 dict → 文件（純 JSON-safe 結構）。"""
    return {
        "event_id":       ev.get("event_id", ""),
        "date":           date_str,
        "title":          ev.get("title", ""),
        "summary":        ev.get("summary", ""),
        "full_content":   ev.get("full_content", ""),
        "category":       ev.get("category", "uncategorized"),
        "category_label": CATEGORY_LABEL_BY_ID.get(ev.get("category"), "其他"),
        # 第二層主題標籤（0-3 個）；tags_by 標明來源，回溯補標的資料可與每日抽取的分開分析。
        # 沒有 tags 欄位的是 v1 之前的舊事件，標 none 以免被當成 LLM 抽取結果
        "tags":           normalize_tags(ev.get("tags")),
        "tags_by":        ev.get("tags_by") or ("extract" if "tags" in ev else "none"),
        "tags_version":   ev.get("tags_version") or TAGS_VERSION,
        "importance":     int(ev.get("importance", 0) or 0),
        "mention_count":  int(ev.get("mention_count", 1) or 1),
        "who":            list(ev.get("who", []) or []),
        "what":           ev.get("what", ""),
        "when":           ev.get("when", ""),
        "where":          ev.get("where", ""),
        "sources":        [source_to_doc(s) for s in (ev.get("sources") or [])],
        "cover_image":    cover_resolver(ev, date_str),
        "is_top":         bool(is_top),
        # 跨日熱度加權的依據（trending.py）；沒被加權的是 None
        "trending":       ev.get("trending") or None,
        "generated_at":   utc_now_iso(),
    }


def build_docs(date_str: str,
               db_events: list[dict],
               top_events: list[dict],
               cover_resolver: CoverResolver = keep_cover) -> list[dict]:
    top_ids = {ev.get("event_id") for ev in top_events if ev.get("event_id")}
    docs = []
    for ev in db_events:
        eid = ev.get("event_id")
        if not eid:
            continue
        docs.append(event_to_doc(ev, date_str, is_top=eid in top_ids,
                                 cover_resolver=cover_resolver))
    return docs


def tag_stats(events: list[dict]) -> dict:
    """主題標籤統計：一則事件可掛多個標籤，加總會大於事件數。"""
    by_tag: dict[str, int] = {}
    mentions: dict[str, int] = {}
    high: dict[str, int] = {}
    for ev in events:
        mc = int(ev.get("mention_count") or len(ev.get("sources") or []) or 1)
        imp = int(ev.get("importance") or 0)
        for t in dict.fromkeys(ev.get("tags") or []):
            by_tag[t] = by_tag.get(t, 0) + 1
            mentions[t] = mentions.get(t, 0) + mc
            if imp >= 8:
                high[t] = high.get(t, 0) + 1
    return {"by_tag": by_tag, "mentions_by_tag": mentions,
            "high_importance_by_tag": high, "tags_version": TAGS_VERSION}


def build_summary(date_str: str,
                  db_events: list[dict],
                  top_events: list[dict],
                  by_category_label: dict[str, int]) -> dict:
    return {
        "date":              date_str,
        "total_db":          len(db_events),
        "total_top":         len(top_events),
        "by_category_label": dict(by_category_label),
        **tag_stats(db_events),
        "generated_at":      utc_now_iso(),
    }
