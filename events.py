"""
事件中心模型
============

新聞只是「證據來源」，真正的單位是事件。

事件 schema：
{
    "event_id":    "hash",
    "title":       "Google 發布 Gemini 3.5 Flash",        # 8-20 字繁體中文
    "summary":     "...",                                    # 2-3 句繁體中文 80-150 字
    "category":    "tech_research" | ... ,                  # 5 類之一
    "importance":  1..10,
    # 5W1H / 人事時地物
    "who":         ["Google", "Sundar Pichai"],              # 主體 list
    "what":        "發布新模型",                              # 動作短語 4-10 字
    "when":        "2026-05-19",                             # YYYY-MM-DD 或「近期」
    "where":       "Mountain View" | "" ,                    # 可空
    # 證據來源（多則新聞報導同一事件 → 多個 source）
    "sources":     [
        {"url": "...", "title": "...", "source_name": "...",
         "source_region": "...", "published": "...", "source_kind": "..."},
        ...
    ],
    "mention_count": 3,   # = len(sources)
    "cover_image": {...}, # 後續 attach
}
"""

from __future__ import annotations
import hashlib
import json
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from config import CATEGORY_IDS, CATEGORIES, LLM_BATCH_SIZE
from llm import chat_json


# 平行度。LLM server 通常能扛 4-8 個並發；若伺服器吃緊就調降。
EVENT_EXTRACT_WORKERS = 4
EVENT_BATCH_SIZE = 8           # 8 則 / 次 LLM call
MERGE_LLM_WORKERS = 4


# ─────────────────────────────────────────────────────────────
# 1. 從新聞抽取事件
# ─────────────────────────────────────────────────────────────
_EXTRACT_SYSTEM = (
    "你是 AI 新聞編輯，從每則新聞抽出「AI 相關事件」。\n"
    "\n"
    "事件定義：必須是『具體可驗證的單一動作』，"
    "且與 AI / 機器學習 / 生成式 AI / AI 半導體與資料中心 / 機器人 / 開源模型直接相關。\n"
    "排除以下情境（這類新聞請回傳空陣列）：\n"
    "  ‣ 純評論、預測、觀點文章（沒有具體動作）\n"
    "  ‣ 與 AI 無實質關聯\n"
    "  ‣ 沒有可指認的主體（公司、人物、產品）\n"
    "\n"
    "一則新聞可能描述多個獨立事件——請全部列出，不要合併。\n"
    "範例：一則 Google I/O 報導可能同時包含「Gemini 3.5 Flash 發布」、"
    "「Veo 4 公開」、「Antigravity 工具上線」三個事件，請拆成 3 筆。\n"
    "\n"
    "每個事件用以下 JSON 結構：\n"
    "{\n"
    '  "title":       "8-20 字繁體中文事件標題（直述、無前綴）",\n'
    '  "summary":     "2-3 句繁體中文摘要，80-150 字，含具體事實",\n'
    f'  "category":   "{ " | ".join(CATEGORY_IDS) }",\n'
    '  "importance":  1-10 整數,\n'
    '  "who":         ["主體 1", "主體 2"],   // 公司/人物/產品名；'
    '若是產品/模型發布類事件，第一個放產品名（例：「Gemini 3.5 Flash」），公司名放後面；'
    '若是公司動作（融資、收購、訴訟），第一個放主體公司名。\n'
    '  "what":        "動作短語（4-10 字，例如 推出新模型 / 收購 / 融資 / 訴訟 / 評測）",\n'
    '  "when":        "YYYY-MM-DD 或 近期",\n'
    '  "where":       "地點或空字串"\n'
    "}\n"
    "\n"
    "輸入是 JSON array of {idx, title, summary, source}。\n"
    "輸出純 JSON array：每筆 {\"idx\": int, \"events\": [event, ...]}。\n"
    "若該新聞不含 AI 事件，events 為 []。\n"
    "不要輸出 JSON 以外的任何文字。"
)


def _build_extract_payload(batch: list[dict]) -> str:
    rows = []
    for i, it in enumerate(batch):
        rows.append({
            "idx": i,
            "title": (it.get("title") or "")[:200],
            "summary": (it.get("summary") or "")[:600],
            "source": it.get("source_name") or "",
        })
    return (
        f"請從下列 {len(batch)} 則新聞中各抽出 AI 相關事件：\n\n"
        + json.dumps(rows, ensure_ascii=False)
    )


def _normalize_event(ev: dict, src_item: dict) -> dict | None:
    """單一事件正規化；不合格回 None。"""
    if not isinstance(ev, dict):
        return None
    title = (ev.get("title") or "").strip()
    summary = (ev.get("summary") or "").strip()
    cat = ev.get("category") or "uncategorized"
    if cat not in CATEGORY_IDS:
        cat = "uncategorized"
    if not title or not summary:
        return None
    try:
        importance = int(ev.get("importance") or 5)
    except Exception:
        importance = 5
    importance = max(1, min(10, importance))

    who_raw = ev.get("who") or []
    if isinstance(who_raw, str):
        who = [w.strip() for w in re.split(r"[、,，/]", who_raw) if w.strip()]
    elif isinstance(who_raw, list):
        who = [str(w).strip() for w in who_raw if str(w).strip()]
    else:
        who = []

    return {
        "title": title[:80],
        "summary": summary[:400],
        "category": cat,
        "importance": importance,
        "who": who[:6],
        "what": (ev.get("what") or "").strip()[:20],
        "when": (ev.get("when") or "").strip()[:20],
        "where": (ev.get("where") or "").strip()[:40],
        # 第一個 source（合併時會 append 更多）
        "sources": [_source_record(src_item)],
    }


def _source_record(it: dict) -> dict:
    return {
        "url": it.get("url", ""),
        "title": it.get("title", ""),
        "source_name": it.get("source_name", ""),
        "source_region": it.get("source_region", ""),
        "source_kind": it.get("source_kind", ""),
        "published": it.get("published", ""),
        # 擴充開源模型與生態 metadata
        "is_opensource": it.get("is_opensource", False),
        "stars": it.get("stars", ""),
        "pulls": it.get("pulls", ""),
        "context_length": it.get("context_length", 0),
        "pricing": it.get("pricing", {}),
        "task": it.get("task", ""),
        "downloads": it.get("downloads", 0),
        "upvotes": it.get("upvotes", 0),
    }


def _process_extract_batch(batch: list[dict]) -> tuple[list[dict], int, int]:
    """
    處理單一 batch：呼叫 LLM、拆半重試、normalize。
    回傳 (events, n_empty_items_in_batch, n_multi_items_in_batch)
    """
    result = chat_json(_build_extract_payload(batch),
                       system=_EXTRACT_SYSTEM, max_tokens=4000)

    # 拆半重試
    if not isinstance(result, list) and len(batch) > 1:
        half = len(batch) // 2
        r1 = chat_json(_build_extract_payload(batch[:half]),
                       system=_EXTRACT_SYSTEM, max_tokens=3000)
        r2 = chat_json(_build_extract_payload(batch[half:]),
                       system=_EXTRACT_SYSTEM, max_tokens=3000)
        merged: list = []
        if isinstance(r1, list):
            merged.extend(r1)
        if isinstance(r2, list):
            for r in r2:
                if isinstance(r, dict) and "idx" in r:
                    try:
                        r["idx"] = int(r["idx"]) + half
                    except Exception:
                        pass
            merged.extend(r2)
        result = merged if merged else None

    if not isinstance(result, list):
        return [], len(batch), 0

    by_idx: dict[int, list] = {}
    for r in result:
        if isinstance(r, dict) and "idx" in r:
            try:
                by_idx[int(r["idx"])] = r.get("events") or []
            except Exception:
                continue

    events_out: list[dict] = []
    n_empty = 0
    n_multi = 0
    for local_i, it in enumerate(batch):
        evs = by_idx.get(local_i, [])
        if not evs:
            n_empty += 1
            continue
        if len(evs) > 1:
            n_multi += 1
        for ev in evs:
            norm = _normalize_event(ev, it)
            if norm:
                events_out.append(norm)
    return events_out, n_empty, n_multi


def extract_events_from_items(items: list[dict],
                              batch_size: int = EVENT_BATCH_SIZE,
                              max_workers: int = EVENT_EXTRACT_WORKERS) -> list[dict]:
    """
    平行版：把 items 切 batch，用 ThreadPoolExecutor 同時送多個 LLM 請求。
    """
    if not items:
        return []
    batches = [items[i: i + batch_size] for i in range(0, len(items), batch_size)]
    print(f"  LLM 抽取事件（共 {len(items)} 則 / {len(batches)} 個 batch / "
          f"batch={batch_size} / 平行 {max_workers}）...")

    out: list[dict] = []
    out_lock = threading.Lock()
    progress = {"done": 0, "events": 0, "empty": 0, "multi": 0, "fail_batches": 0}

    def _worker(b_idx_batch: tuple[int, list[dict]]):
        b_idx, batch = b_idx_batch
        try:
            ev_list, n_empty, n_multi = _process_extract_batch(batch)
        except Exception as e:
            print(f"    [error] batch {b_idx+1}: {type(e).__name__}: {e}")
            ev_list, n_empty, n_multi = [], len(batch), 0
        with out_lock:
            if not ev_list and n_empty == len(batch):
                progress["fail_batches"] += 1
            out.extend(ev_list)
            progress["done"] += 1
            progress["events"] = len(out)
            progress["empty"] += n_empty
            progress["multi"] += n_multi
            done = progress["done"]
            if done % 3 == 0 or done == len(batches):
                print(f"    進度 {done}/{len(batches)}  累計事件 {progress['events']}",
                      flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_worker, list(enumerate(batches))))

    if progress["fail_batches"]:
        print(f"    [warn] {progress['fail_batches']} 個 batch 失敗（已跳過）")
    print(f"  事件抽取完成：{len(out)} 個事件（"
          f"{progress['empty']} 則無事件、{progress['multi']} 則含多事件）")
    return out


# ─────────────────────────────────────────────────────────────
# 2. 事件合併（去重 2.0 — 連通元件語意去重）
# ─────────────────────────────────────────────────────────────
_PUNCT_RE = re.compile(r"[，。、！？!?,.;:：；\"'`()【】\[\]｜\|—\-－—‘’“”·…．、　\s]+")


def _norm_token(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"['’]s\b", "", s)
    s = _PUNCT_RE.sub("", s)
    return s


def _who_set(ev: dict) -> set[str]:
    return {_norm_token(w) for w in (ev.get("who") or []) if w}


def _what_norm(ev: dict) -> str:
    return _norm_token(ev.get("what", ""))


def _event_fingerprint(ev: dict) -> str:
    """同主體 + 同動作 → 同 fingerprint。"""
    who = "+".join(sorted(_who_set(ev)))
    return f"{who}|{_what_norm(ev)}"


# 語意化主體對齊 dictionary
_WHO_ALIASES = {
    "微軟": "microsoft", "microsoftcorp": "microsoft", "microsoftcloud": "microsoft",
    "谷歌": "google", "googlecloud": "google", "alphabet": "google",
    "蘋果": "apple", "appleinc": "apple",
    "輝達": "nvidia", "nvidacorp": "nvidia",
    "臉書": "meta", "facebook": "meta", "metaplatforms": "meta",
    "openai": "openai", "chatgpt": "openai",
    "anthropic": "anthropic", "claude": "anthropic",
    "github": "github",
    "huggingface": "huggingface", "hf": "huggingface",
    "bytedance": "bytedance", "字节跳动": "bytedance", "抖音": "bytedance"
}


def _align_who(w: str) -> str:
    w_norm = _norm_token(w)
    for alias, target in _WHO_ALIASES.items():
        if alias in w_norm or w_norm in alias:
            return target
    return w_norm


def _jaccard_similarity(s1: str, s2: str) -> float:
    s1_norm = _norm_token(s1)
    s2_norm = _norm_token(s2)
    if not s1_norm or not s2_norm:
        return 0.0
    set1 = set(s1_norm)
    set2 = set(s2_norm)
    intersection = set1.intersection(set2)
    union = set1.union(set2)
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _is_suspiciously_similar(a: dict, b: dict) -> bool:
    """判斷兩個事件是否疑似重複，若疑似則在無向圖中相連。"""
    sim = _jaccard_similarity(a.get("title", ""), b.get("title", ""))
    
    # A) 極高相似度：標題字元 Jaccard 相似度高於 0.65，直接連通
    if sim >= 0.65:
        return True

    # 提取語意對齊後的 who 集合
    who_a = {_align_who(w) for w in (a.get("who") or []) if w}
    who_b = {_align_who(w) for w in (b.get("who") or []) if w}
    who_a = {w for w in who_a if w and len(w) > 1}
    who_b = {w for w in who_b if w and len(w) > 1}
    has_who_overlap = bool(who_a and who_b and who_a.intersection(who_b))

    if has_who_overlap:
        # B) 中度相似度且主體重疊：Jaccard >= 0.38 且 who 有重疊
        if sim >= 0.38:
            return True

        title_a = (a.get("title") or "").lower()
        title_b = (b.get("title") or "").lower()

        # C) 低相似度且主體重疊但有特異主題關鍵字：Jaccard >= 0.18 且 who 重疊 且 包含相同主題關鍵字
        topic_keywords_groups = [
            ["ipo", "上市", "公開募股"],
            ["erdős", "erdos", "幾何", "數學", "猜想", "單位距離"],
            ["genie", "世界模型"],
            ["mix-quant", "量化", "prefilling"],
            ["mtp", "multi-token"],
            ["自駕", "自動駕駛", "marl"],
            ["llm", "大模型", "推理", "微調"],
            ["150億", "150 億", "15 billion", "12.5億", "12.5 億", "算力", "數據中心", "資料中心", "招股", "colossus"]
        ]

        has_common_topic = False
        for group in topic_keywords_groups:
            has_a = any(kw in title_a for kw in group)
            has_b = any(kw in title_b for kw in group)
            if has_a and has_b:
                has_common_topic = True
                break

        if has_common_topic and sim >= 0.18:
            return True

        # D) 標題包含高度特異的模型名稱且 who 重疊
        model_keywords = ["gemini 3.5", "gpt-4o", "veo", "sora", "deepseek-v3", "llama-3", "mistral", "qwen", "ollama", "openrouter"]
        for kw in model_keywords:
            if kw in title_a and kw in title_b:
                return True

    return False


def _find_connected_components(events: list[dict]) -> list[list[dict]]:
    """找出事件列表中的所有連通元件。"""
    n = len(events)
    visited = [False] * n
    adj = defaultdict(list)
    for i in range(n):
        for j in range(i + 1, n):
            if _is_suspiciously_similar(events[i], events[j]):
                adj[i].append(j)
                adj[j].append(i)

    components = []
    for i in range(n):
        if not visited[i]:
            comp = []
            stack = [i]
            while stack:
                curr = stack.pop()
                if not visited[curr]:
                    visited[curr] = True
                    comp.append(events[curr])
                    for neighbor in adj[curr]:
                        if not visited[neighbor]:
                            stack.append(neighbor)
            components.append(comp)
    return components


_GROUP_MERGE_SYSTEM = (
    "你是一位精明且擁有極高標準的 AI 新聞總編輯。\n"
    "你的任務是審查一組疑似重複的 AI 事件，並進行完全去重與合併。\n\n"
    "【合併標準】\n"
    "  ‣ 只有當多個事件確實在描述「同一個具體的 AI 事件」時，才進行合併。\n"
    "    例如：「發布 Gemini 3.5 Flash」與「Google 推出 Gemini 3.5 Flash」是同一件事，必須合併。\n"
    "  ‣ 若描述的是不同事件（例如「微軟發布 A 模型」與「微軟發布 B 模型」，或「OpenAI 發布新模型」與「OpenAI 被起訴」），請絕對不要合併，必須保留為多個獨立事件。\n\n"
    "【輸出要求】\n"
    "1. 請仔細比對，輸出一個 JSON array，包含去重與合併後的事件列表。\n"
    "2. 對於被判定為「同一件事」而合併的事件群組，請綜合所有輸入事件的細節，重新撰寫：\n"
    "   - `title`: 最精煉、流暢的繁體中文事件標題 (8-20字)。\n"
    "   - `summary`: 最完整且無冗餘的繁體中文摘要 (2-3句，80-150字)。\n"
    "   - `who`: 合併後的主體列表 (保留最核心、無重複的 1-4 個主體)。\n"
    "   - `what` & `when` & `where`: 取最精確的事實。\n"
    "   - `importance`: 該組事件的最大 importance。\n"
    "   - `merged_idx_list`: 一個整數陣列，包含該合併事件是由哪些輸入事件的 `idx` 所構成。這至關重要！我們會用它來合併證據來源 (sources)。\n"
    "3. 對於「不需要合併」的獨立事件，原樣保留，但必須帶有原本的 `idx` 作為它的唯一 `merged_idx_list`。\n"
    "4. 不要輸出 JSON 以外的任何文字。"
)


def _merge_into(head: dict, other: dict) -> None:
    """把 other 合進 head（in-place 更新 head.sources，並擴充 who 集合）。"""
    seen_urls = {s.get("url") for s in head["sources"]}
    for s in other["sources"]:
        if s.get("url") and s["url"] not in seen_urls:
            head["sources"].append(s)
            seen_urls.add(s["url"])
    cur_who = head.get("who", []) or []
    cur_set = {_norm_token(w) for w in cur_who}
    for w in other.get("who", []):
        if _norm_token(w) not in cur_set:
            cur_who.append(w)
            cur_set.add(_norm_token(w))
    head["who"] = cur_who[:8]
    head["importance"] = max(head.get("importance", 0), other.get("importance", 0))


def _llm_group_merge(comp: list[dict]) -> list[dict]:
    """呼叫 LLM 進行群組判定與去重合併。失敗時降級回傳原事件列表。"""
    if len(comp) == 1:
        return comp

    rows = []
    for idx, ev in enumerate(comp):
        rows.append({
            "idx": idx,
            "title": ev.get("title", ""),
            "who": ev.get("who", []),
            "what": ev.get("what", ""),
            "when": ev.get("when", ""),
            "summary": ev.get("summary", "")[:220]
        })

    payload = "請幫我判定並合併以下疑似重複的 AI 事件：\n\n" + json.dumps(rows, ensure_ascii=False)
    res = chat_json(payload, system=_GROUP_MERGE_SYSTEM, max_tokens=4000)

    if not isinstance(res, list):
        # 降級：若 LLM 失敗，原樣保留不進行合併
        print(f"      [LLM-group-merge info] LLM 失敗或回傳非列表，降級保留原本 {len(comp)} 個事件")
        return comp

    merged_out = []
    for item in res:
        if not isinstance(item, dict):
            continue
        idx_list = item.get("merged_idx_list") or []
        if not idx_list:
            continue

        # 找到第一個有效的原事件當作 head 基礎
        head = None
        for orig_idx in idx_list:
            if 0 <= orig_idx < len(comp):
                if head is None:
                    # 深度複製或建立一個新 dict 避免污染
                    head = dict(comp[orig_idx])
                    # 用 LLM 優化後的內容改寫
                    head["title"] = item.get("title") or head["title"]
                    head["summary"] = item.get("summary") or head["summary"]
                    head["who"] = item.get("who") or head["who"]
                    head["what"] = item.get("what") or head["what"]
                    head["when"] = item.get("when") or head["when"]
                    head["where"] = item.get("where") or head.get("where", "")
                    head["importance"] = item.get("importance") or head["importance"]
                else:
                    _merge_into(head, comp[orig_idx])
        if head:
            merged_out.append(head)

    # 萬一 LLM 回傳空的，做保底
    if not merged_out:
        return comp

    return merged_out


def _merge_into_programmatic(head: dict, other: dict) -> None:
    """把 other 合併入 head (in-place 更新，不污染原始資料)。"""
    head["sources"] = list(head.get("sources") or [])
    head["who"] = list(head.get("who") or [])

    # 1. 合併 sources，避開重複 URL
    seen_urls = {s.get("url") for s in head["sources"] if s.get("url")}
    for s in other.get("sources") or []:
        url = s.get("url")
        if url and url not in seen_urls:
            head["sources"].append(s)
            seen_urls.add(url)

    # 2. 合併 who 列表
    cur_who = head["who"]
    cur_set = {_norm_token(w) for w in cur_who}
    for w in other.get("who") or []:
        if w and _norm_token(w) not in cur_set:
            cur_who.append(w)
            cur_set.add(_norm_token(w))
    head["who"] = cur_who[:8]

    # 3. importance 取最大值
    head["importance"] = max(head.get("importance") or 5, other.get("importance") or 5)

    # 4. 更好的 when / where
    w_head = head.get("when") or ""
    w_other = other.get("when") or ""
    if ("近期" in w_head or not w_head or w_head == "n/a") and ("近期" not in w_other and w_other and w_other != "n/a"):
        head["when"] = w_other

    if not head.get("where") and other.get("where"):
        head["where"] = other["where"]

    # 5. 保留細節更豐富的 summary
    s_head = head.get("summary") or ""
    s_other = other.get("summary") or ""
    if len(s_other) > len(s_head):
        head["summary"] = s_other

    # 6. 保留更長/更明確的 title
    t_head = head.get("title") or ""
    t_other = other.get("title") or ""
    if len(t_other) > len(t_head):
        head["title"] = t_other


def _programmatic_dedup(events: list[dict]) -> list[dict]:
    """
    100% 確定性的程式化預去重機制：
    - 規則 1：若 normalized 標題完全一致，直接合併。
    - 規則 2：若標題 Jaccard 相似度 >= 0.48 且語意對齊後的 who 集合有交集 且 兩者包含核心主題關鍵字。
    """
    if not events:
        return []

    current = [dict(ev) for ev in events]
    changed = True

    while changed:
        changed = False
        merged_list = []
        used = [False] * len(current)

        for i in range(len(current)):
            if used[i]:
                continue
            head = current[i]
            used[i] = True

            who_head = {_align_who(w) for w in (head.get("who") or []) if w}
            who_head = {w for w in who_head if w and len(w) > 1}
            title_head_norm = _norm_token(head.get("title") or "")
            title_head_raw = (head.get("title") or "").lower()

            for j in range(i + 1, len(current)):
                if used[j]:
                    continue
                other = current[j]

                title_other_norm = _norm_token(other.get("title") or "")
                title_other_raw = (other.get("title") or "").lower()

                is_match = False
                # 規則 1: 標題完全一致
                if title_head_norm and title_other_norm and title_head_norm == title_other_norm:
                    is_match = True
                else:
                    # 規則 2: Jaccard >= 0.48 且 who 重疊 且 包含相同特異主題關鍵字
                    sim = _jaccard_similarity(head.get("title", ""), other.get("title", ""))
                    if sim >= 0.48:
                        who_other = {_align_who(w) for w in (other.get("who") or []) if w}
                        who_other = {w for w in who_other if w and len(w) > 1}
                        if who_head.intersection(who_other):
                            topic_keywords_groups = [
                                ["ipo", "上市", "公開募股"],
                                ["erdős", "erdos", "幾何", "數學", "猜想", "單位距離"],
                                ["genie", "世界模型"],
                                ["mix-quant", "量化", "prefilling"],
                                ["mtp", "multi-token"],
                                ["自駕", "自動駕駛", "marl"],
                                ["llm", "大模型", "推理", "微調"],
                                ["150億", "150 億", "15 billion", "12.5億", "12.5 億", "算力", "數據中心", "資料中心", "招股", "colossus"]
                            ]
                            has_common_topic = False
                            for group in topic_keywords_groups:
                                has_head = any(kw in title_head_raw for kw in group)
                                has_other = any(kw in title_other_raw for kw in group)
                                if has_head and has_other:
                                    has_common_topic = True
                                    break
                            if has_common_topic:
                                is_match = True

                    # 規則 3: Jaccard >= 0.52 且 who 重疊 (高置信度直接合併)
                    if not is_match and sim >= 0.52:
                        who_other = {_align_who(w) for w in (other.get("who") or []) if w}
                        who_other = {w for w in who_other if w and len(w) > 1}
                        if who_head.intersection(who_other):
                            is_match = True

                if is_match:
                    _merge_into_programmatic(head, other)
                    used[j] = True
                    changed = True
                    # 重新計算特徵以利後續的再比對
                    who_head = {_align_who(w) for w in (head.get("who") or []) if w}
                    who_head = {w for w in who_head if w and len(w) > 1}
                    title_head_norm = _norm_token(head.get("title") or "")
                    title_head_raw = (head.get("title") or "").lower()

            merged_list.append(head)

        current = merged_list
        if not changed:
            break

    return current


def merge_events(events: list[dict]) -> list[dict]:
    """
    連通元件與 LLM 群組語意去重 (Deduplication 2.0)
    1. 先行執行 100% 確定性的程式化預去重，合併完全一致或高度相似事件
    2. 建立疑似重複的無向圖關係
    3. 劃分連通元件 (Connected Components)
    4. 對大於 1 個節點的元件送 LLM 進行全局判定與合併
    """
    if not events:
        return []

    print(f"  開始事件合併去重 2.0 (原始輸入 {len(events)} 個事件)...")
    events = _programmatic_dedup(events)
    print(f"    程式化預去重完成，剩餘 {len(events)} 個事件進入圖連通元件劃分...")

    components = _find_connected_components(events)
    print(f"    圖劃分完成：共劃分出 {len(components)} 個連通群組")

    final: list[dict] = []
    n_groups_processed = 0
    n_total_merged = 0

    result_lock = threading.Lock()

    def _process_comp(comp):
        nonlocal n_groups_processed, n_total_merged
        if len(comp) > 1:
            with result_lock:
                n_groups_processed += 1
            merged = _llm_group_merge(comp)
            with result_lock:
                n_total_merged += (len(comp) - len(merged))
            return merged
        else:
            return comp

    # 用 ThreadPoolExecutor 平行處理大於 1 個元素的群組
    comps_to_process = [c for c in components if len(c) > 1]
    single_comps = [c for c in components if len(c) == 1]

    parallel_results = []
    if comps_to_process:
        print(f"    正在平行處理 {len(comps_to_process)} 個疑似重複群組 (平行度 4)...")
        with ThreadPoolExecutor(max_workers=MERGE_LLM_WORKERS) as ex:
            parallel_results = list(ex.map(_process_comp, comps_to_process))

    for r in parallel_results:
        final.extend(r)
    for c in single_comps:
        final.extend(c)

    # 寫入 event_id / mention_count
    for ev in final:
        ev["mention_count"] = len(ev["sources"])
        fp = _event_fingerprint(ev)
        ev["event_id"] = hashlib.sha1(fp.encode("utf-8")).hexdigest()[:10]

    print(f"  事件合併完成：原 {len(events)} 個事件 → 最終 {len(final)} 個事件 (共合併去重 {n_total_merged} 筆事件)")
    return final




# ─────────────────────────────────────────────────────────────
# 3. 品質過濾
# ─────────────────────────────────────────────────────────────
_VAGUE_WHEN_RE = re.compile(r"近期|recent|recently|n/a|未知|未提及", re.I)
_DATE_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})")


def _parse_event_when(when: str) -> date | None:
    """從事件 when 字串嘗試取出日期；失敗或模糊回 None（= 不限制）。"""
    if not when:
        return None
    s = when.strip()
    if _VAGUE_WHEN_RE.search(s):
        return None
    # ISO format first
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        pass
    m = _DATE_RE.search(s)
    if m:
        try:
            y, mo, d = (int(g) for g in m.groups())
            return date(y, mo, d)
        except Exception:
            return None
    return None


def filter_events(events: list[dict],
                  min_importance: int = 4,
                  min_summary_chars: int = 40,
                  days_back: int | None = None,
                  today: date | None = None) -> list[dict]:
    """
    硬篩：
      ‣ importance < min_importance
      ‣ summary 過短
      ‣ event.when 早於 cutoff（only when days_back & today 都給；when="近期"或無日期則放行）
    """
    if today is None:
        today = date.today()
    cutoff = (today - timedelta(days=days_back)) if days_back is not None else None

    kept: list[dict] = []
    dropped_imp = dropped_short = dropped_old = 0
    for ev in events:
        if ev.get("importance", 0) < min_importance:
            dropped_imp += 1
            continue
        if len(ev.get("summary", "")) < min_summary_chars:
            dropped_short += 1
            continue
        if cutoff is not None:
            evt_date = _parse_event_when(ev.get("when", ""))
            if evt_date is not None and evt_date < cutoff:
                dropped_old += 1
                continue
        kept.append(ev)
    msg = f"  品質過濾：刪 {dropped_imp} 個低重要度、{dropped_short} 個摘要過短"
    if cutoff:
        msg += f"、{dropped_old} 個事件日期早於 {cutoff.isoformat()}"
    print(msg)
    return kept
