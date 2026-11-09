"""
跨日熱度加權
============

importance 是 LLM 看單篇文章打的分數，看不到「這件事已經連續吵了好幾天」。
新創或新模型剛冒出來時，每天往往只有一兩篇報導，mention_count 只有 1–2，
再加上 LLM 對沒聽過的名字容易低估，整個話題就一直沉在資料庫底部。
2026-09 的 Jev（TypeSafe AI）就是這樣：09-17、09-21、09-22 都有進資料庫，
但重要度只有 5–6，從沒上過精選。

這裡用「新興主體」判斷：
  ‣ 事件的主體（who 前兩個）在近 RECENT_DAYS 天、跨多天、被多個來源提到
  ‣ 但在更早的 RECENT_DAYS..BASELINE_DAYS 天內從沒出現過
後者是為了排除 OpenAI、Nvidia 這種天天都在新聞裡的名字 —— 它們的熱度
早就反映在 importance 上，不需要再加。

符合的事件 importance +1（≥3 個來源）或 +2（≥5 個來源），並標上 trending。
"""

from __future__ import annotations
import os
import re
from datetime import date, timedelta

RECENT_DAYS = 7
BASELINE_DAYS = 30
MIN_SOURCES = 3
STRONG_SOURCES = 5
MAX_BOOSTED = 9


def load_history(today: date, days: int = BASELINE_DAYS) -> list[dict]:
    """讀今天以前 days 天的事件（跟 pipeline 寫入時用同一個 store）。失敗回空。"""
    start = (today - timedelta(days=days)).isoformat()
    end = (today - timedelta(days=1)).isoformat()
    skip_fs = os.getenv("AINEWS_SKIP_FIRESTORE", "").strip().lower() in ("1", "true", "yes")
    store = os.getenv("AINEWS_STORE", "").strip().lower()
    if store not in ("local", "firestore", "both"):
        store = "local" if skip_fs else "firestore"
    try:
        if store == "local":
            from local_store import load_events
            return load_events(start, end)
        from firestore_writer import load_events_for_trending
        return load_events_for_trending(start, end)
    except Exception as e:
        print(f"  [trending] 讀歷史事件失敗，略過熱度加權：{type(e).__name__}: {e}")
        return []


def _text(ev: dict) -> str:
    return " ".join([ev.get("title", ""), ev.get("summary", ""),
                     " ".join(ev.get("who") or [])]).lower()


def _matcher(entity: str):
    ent = entity.lower().strip()
    # 太短的名字（AI、X）會亂配
    if len(ent) < 3:
        return None
    return re.compile(r"(?<![a-z0-9])" + re.escape(ent) + r"(?![a-z0-9])")


def apply_trending_boost(events: list[dict], history: list[dict], today: date) -> int:
    """就地調整 events 的 importance；回傳被加權的事件數。"""
    if not history:
        return 0
    recent_cut = (today - timedelta(days=RECENT_DAYS)).isoformat()
    recent = [(e, _text(e)) for e in history if e.get("date", "") >= recent_cut]
    base = [_text(e) for e in history if e.get("date", "") < recent_cut]

    boosted = 0
    for ev in events:
        best: tuple[str, int, int] | None = None
        for entity in (ev.get("who") or [])[:2]:
            pat = _matcher(entity)
            if pat is None or any(pat.search(t) for t in base):
                continue
            hits = [e for e, t in recent if pat.search(t)]
            if not hits:
                continue
            srcs = {s.get("source_name") for x in hits + [ev] for s in (x.get("sources") or [])}
            days = {x.get("date") for x in hits} | {today.isoformat()}
            if len(srcs) >= MIN_SOURCES and len(days) >= 2:
                if best is None or len(srcs) > best[1]:
                    best = (entity, len(srcs), len(days))
        if best is None:
            continue
        bump = 2 if best[1] >= STRONG_SOURCES else 1
        old = int(ev.get("importance", 0) or 0)
        ev["importance"] = max(old, min(MAX_BOOSTED, old + bump))
        ev["trending"] = {"entity": best[0], "sources": best[1], "days": best[2]}
        boosted += 1
        print(f"    [trending] {best[0]}（{best[1]} 來源 / {best[2]} 天）"
              f" {old}→{ev['importance']}  {ev.get('title', '')}")
    print(f"  跨日熱度加權：{boosted} 個事件")
    return boosted
