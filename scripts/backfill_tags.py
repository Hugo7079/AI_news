#!/usr/bin/env python3
"""
替歷史事件回溯補上 tags（雙層分類第二層）
=========================================

只補寫事件的 tags / tags_by / tags_version 三個欄位，以及每日彙總的 by_tag 統計；
不動 category、importance 或任何其他欄位。每日 pipeline 抽出的 tags（tags_by=extract）
永遠不會被覆寫。

    # 預設是試跑（dry-run）：只印統計，不寫回
    python3 scripts/backfill_tags.py
    python3 scripts/backfill_tags.py --start 2026-08-01 --end 2026-08-31

    # 用 LLM 批次標註（較準，會呼叫 LLM；每 20 則一次）
    python3 scripts/backfill_tags.py --mode llm --start 2026-11-01

    # 確認統計沒問題再加 --write 寫回
    python3 scripts/backfill_tags.py --write
    python3 scripts/backfill_tags.py --store firestore --write   # 雲端版（需 Firebase 憑證）

    # 字典改版後重標「之前回溯補的」事件（extract 的仍不動）
    python3 scripts/backfill_tags.py --redo-backfill --write

    # 抽樣比較規則與 LLM 的一致程度（不寫回）
    python3 scripts/backfill_tags.py --compare 150 --start 2026-10-01

--mode rules：tags.rule_tags() 關鍵詞規則，不花 LLM 額度，幾秒跑完半年資料。
--mode llm   ：與每日抽事件同一份字典與規則，品質接近每日標註。
"""

from __future__ import annotations
import argparse
import json
import random
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tags import (MAX_TAGS, TAG_IDS, TAG_LABEL_BY_ID, TAGS_VERSION,  # noqa: E402
                  normalize_tags, rule_tags, tag_spec_for_prompt)

LLM_BATCH = 20
LLM_WORKERS = 2

_LLM_SYSTEM = (
    "你是科技新聞編輯，替已經整理好的事件標上主題標籤（tags）。\n"
    f"每個事件 0-{MAX_TAGS} 個，只能從下列字典挑 id，依關聯強度排序、最核心的放第一個。\n"
    "tags 描述事件『涉及的主題』，跟事件的主分類（category）互補、可以跨分類。\n"
    "字典裡沒有真正符合的主題就給 []，不要硬套最接近的標籤。\n"
    f"{tag_spec_for_prompt()}\n"
    "\n"
    "輸入是 JSON array of {idx, title, summary, category}。\n"
    "輸出純 JSON array：每筆 {\"idx\": int, \"tags\": [\"tag_id\", ...]}，輸入幾筆就回幾筆。\n"
    "不要輸出 JSON 以外的任何文字。"
)


# ─────────────────────────────────────────────────────────────
# 標註
# ─────────────────────────────────────────────────────────────
def _rules(ev: dict) -> list[str]:
    return rule_tags(ev.get("title", ""), ev.get("summary", ""), ev.get("what", ""))


def _llm_batch(batch: list[dict]) -> dict[int, list[str]]:
    from llm import chat_json
    rows = [{"idx": i, "title": ev.get("title", ""),
             "summary": (ev.get("summary") or "")[:300],
             "category": ev.get("category", "")} for i, ev in enumerate(batch)]
    payload = "請替下列事件標上主題標籤：\n\n" + json.dumps(rows, ensure_ascii=False)
    for _ in range(2):
        res = chat_json(payload, system=_LLM_SYSTEM, max_tokens=6000)
        if isinstance(res, list):
            out: dict[int, list[str]] = {}
            for r in res:
                if isinstance(r, dict) and "idx" in r:
                    try:
                        out[int(r["idx"])] = normalize_tags(r.get("tags"))
                    except (TypeError, ValueError):
                        continue
            return out
    return {}


def tag_events(events: list[dict], mode: str) -> list[list[str] | None]:
    """回傳與 events 對齊的 tags；LLM 失敗的那筆為 None（不寫回，下次再補）。"""
    if mode == "rules":
        return [_rules(ev) for ev in events]

    results: list[list[str] | None] = [None] * len(events)
    batches = [list(range(i, min(i + LLM_BATCH, len(events))))
               for i in range(0, len(events), LLM_BATCH)]
    lock = threading.Lock()
    done = {"n": 0}

    def _work(idxs: list[int]) -> None:
        got = _llm_batch([events[i] for i in idxs])
        with lock:
            for local, gi in enumerate(idxs):
                if local in got:
                    results[gi] = got[local]
            done["n"] += 1
            if done["n"] % 10 == 0 or done["n"] == len(batches):
                print(f"    LLM 標註進度 {done['n']}/{len(batches)}", flush=True)

    with ThreadPoolExecutor(max_workers=LLM_WORKERS) as ex:
        list(ex.map(_work, batches))
    return results


def _tag_stats(events: list[dict]) -> dict:
    by_tag: Counter = Counter()
    mentions: Counter = Counter()
    high: Counter = Counter()
    for ev in events:
        mc = int(ev.get("mention_count") or len(ev.get("sources") or []) or 1)
        imp = int(ev.get("importance") or 0)
        for t in dict.fromkeys(ev.get("tags") or []):
            by_tag[t] += 1
            mentions[t] += mc
            if imp >= 8:
                high[t] += 1
    return {"by_tag": dict(by_tag), "mentions_by_tag": dict(mentions),
            "high_importance_by_tag": dict(high), "tags_version": TAGS_VERSION}


def _needs_tags(ev: dict, redo_backfill: bool) -> bool:
    by = ev.get("tags_by") or ""
    if by == "extract":
        return False
    if by.startswith("backfill"):
        return redo_backfill
    return True


# ─────────────────────────────────────────────────────────────
# 儲存層：本地 store（output/store/*.json）與 Firestore
# ─────────────────────────────────────────────────────────────
def _iter_local_days(start: str, end: str):
    import local_store
    for d in sorted(local_store.list_dates()):
        if (start and d < start) or (end and d > end):
            continue
        day = local_store.load_day(d)
        if day:
            yield d, day


def _write_local_day(date_str: str, day: dict) -> None:
    import local_store
    local_store.write_day(date_str, day.get("events") or [], day.get("summary") or {})


def _load_firestore(start: str, end: str) -> dict[str, list]:
    import firestore_writer as fw
    fw._init()
    col = fw._db.collection("events")
    if start:
        col = col.where("date", ">=", start)
    if end:
        col = col.where("date", "<=", end)
    by_date: dict[str, list] = defaultdict(list)
    for doc in col.stream():
        d = doc.to_dict() or {}
        if d.get("date"):
            by_date[d["date"]].append((doc.reference, d))
    return by_date


def _write_firestore(by_date: dict[str, list], changed: dict[str, set]) -> None:
    import firestore_writer as fw
    db = fw._db
    batch, n = db.batch(), 0
    for d, items in by_date.items():
        for ref, ev in items:
            if id(ev) not in changed.get(d, set()):
                continue
            batch.update(ref, {"tags": ev["tags"], "tags_by": ev["tags_by"],
                               "tags_version": ev["tags_version"]})
            n += 1
            if n % 400 == 0:
                batch.commit()
                batch = db.batch()
    batch.commit()
    for d in changed:
        stats = _tag_stats([ev for _, ev in by_date[d]])
        db.collection("daily_summary").document(d).set(stats, merge=True)
    print(f"[firestore] 已更新 {n} 筆事件、{len(changed)} 天彙總")


# ─────────────────────────────────────────────────────────────
def _report(all_events: list[dict], label: str) -> None:
    n = len(all_events)
    if not n:
        print("沒有事件。")
        return
    dist = Counter(len(ev.get("tags") or []) for ev in all_events)
    cnt = Counter(t for ev in all_events for t in (ev.get("tags") or []))
    print(f"\n=== {label}：{n} 則事件 ===")
    print("每則標籤數：" + "、".join(f"{k} 個 {dist[k]} 則（{100*dist[k]/n:.1f}%）"
                                 for k in sorted(dist)))
    for t in TAG_IDS:
        if cnt[t]:
            print(f"  {t:22s} {TAG_LABEL_BY_ID[t]:12s} {cnt[t]:6d}  {100*cnt[t]/n:5.1f}%")
    unused = [t for t in TAG_IDS if not cnt[t]]
    if unused:
        print("  未出現：" + ", ".join(unused))


def _compare(events: list[dict], k: int) -> None:
    random.seed(42)
    sample = random.sample(events, min(k, len(events)))
    rule = [_rules(ev) for ev in sample]
    llm = tag_events(sample, "llm")
    tp = fp = fn = 0
    per_tag: dict[str, Counter] = defaultdict(Counter)
    exact = 0
    usable = 0
    for ev, r, l in zip(sample, rule, llm):
        if l is None:
            continue
        usable += 1
        rs, ls = set(r), set(l)
        exact += rs == ls
        for t in rs & ls:
            tp += 1
            per_tag[t]["tp"] += 1
        for t in rs - ls:
            fp += 1
            per_tag[t]["fp"] += 1
        for t in ls - rs:
            fn += 1
            per_tag[t]["fn"] += 1
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    print(f"\n=== 規則 vs LLM（{usable} 則有效樣本，以 LLM 為基準）===")
    print(f"規則準確率（precision）{prec:.1%}、召回率（recall）{rec:.1%}、完全一致 {exact/usable:.1%}")
    worst = sorted(per_tag.items(), key=lambda x: -(x[1]["fp"] + x[1]["fn"]))[:12]
    for t, c in worst:
        print(f"  {t:22s} 一致 {c['tp']:3d}  規則多標 {c['fp']:3d}  規則漏標 {c['fn']:3d}")
    out = [{"title": ev.get("title"), "category": ev.get("category"), "rules": r, "llm": l}
           for ev, r, l in zip(sample, rule, llm)]
    path = Path("backfill_tags_compare.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"逐筆對照已存到 {path.resolve()}")


def main() -> None:
    ap = argparse.ArgumentParser(description="替歷史事件回溯補上 tags")
    ap.add_argument("--store", choices=["local", "firestore"], default="local")
    ap.add_argument("--mode", choices=["rules", "llm"], default="rules")
    ap.add_argument("--start", default="", help="起日 YYYY-MM-DD（含）")
    ap.add_argument("--end", default="", help="迄日 YYYY-MM-DD（含）")
    ap.add_argument("--write", action="store_true", help="寫回（不加就是試跑）")
    ap.add_argument("--redo-backfill", action="store_true",
                    help="之前回溯補的也重標（每日抽取 tags_by=extract 的永遠不動）")
    ap.add_argument("--compare", type=int, default=0,
                    help="抽樣 N 則比較規則與 LLM 的一致程度（不寫回）")
    args = ap.parse_args()

    tags_by = f"backfill_{args.mode}"

    if args.store == "local":
        days = dict(_iter_local_days(args.start, args.end))
        day_events = {d: (day.get("events") or []) for d, day in days.items()}
    else:
        fs_days = _load_firestore(args.start, args.end)
        day_events = {d: [ev for _, ev in items] for d, items in fs_days.items()}

    all_events = [ev for d in sorted(day_events) for ev in day_events[d]]
    print(f"[backfill] 讀到 {len(day_events)} 天、{len(all_events)} 則事件（{args.store}）")

    if args.compare:
        _compare(all_events, args.compare)
        return

    todo = [(d, ev) for d in sorted(day_events) for ev in day_events[d]
            if _needs_tags(ev, args.redo_backfill)]
    print(f"[backfill] 需要補標 {len(todo)} 則（模式 {args.mode}，字典 {TAGS_VERSION}）")
    results = tag_events([ev for _, ev in todo], args.mode)

    changed: dict[str, set] = defaultdict(set)
    failed = 0
    for (d, ev), tags in zip(todo, results):
        if tags is None:
            failed += 1
            continue
        ev["tags"] = tags
        ev["tags_by"] = tags_by
        ev["tags_version"] = TAGS_VERSION
        changed[d].add(id(ev))
    if failed:
        print(f"[backfill] {failed} 則 LLM 沒有回應，未標（下次執行會再補）")

    _report(all_events, "補標後全部事件" if args.write else "試跑結果（未寫回）")

    if not args.write:
        print("\n這是試跑，沒有寫回。確認無誤後加 --write。")
        return

    if args.store == "local":
        for d in changed:
            day = days[d]
            summary = dict(day.get("summary") or {})
            summary.update(_tag_stats(day.get("events") or []))
            day["summary"] = summary
            _write_local_day(d, day)
        print(f"[local-store] 已更新 {sum(len(v) for v in changed.values())} 筆事件、{len(changed)} 天")
    else:
        _write_firestore(fs_days, changed)


if __name__ == "__main__":
    main()
