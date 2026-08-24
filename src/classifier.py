"""
分類 & 去重
============

  ‣ classify_batch(items)  — 用 LLM 將條目分到 5 大類，並標記是否為 AI 新聞
  ‣ dedup(items)           — 標題正規化 + LLM 比對相似條目
"""

from __future__ import annotations
import json
import re
from collections import defaultdict

from config import (
    CATEGORIES, CATEGORY_IDS, CATEGORY_LABEL_BY_ID,
    LLM_CLASSIFY_ENABLED, LLM_DEDUP_ENABLED, LLM_BATCH_SIZE,
)
from llm import chat_json


# ─────────────────────────────────────────────────────────────
# 分類
# ─────────────────────────────────────────────────────────────
_CATEGORY_SPEC = "\n".join(
    f"- {cid}（{c['label']}）：{c['desc']}" for cid, c in CATEGORIES.items()
)

_SYSTEM_PROMPT = (
    "你是一位資深 AI 產業分析師，協助將科技新聞歸類。"
    "你會收到一批新聞（標題 + 摘要），請判斷：\n"
    "  1) 是否與『人工智慧 / 機器學習 / 生成式 AI / AI 硬體與供應鏈』直接相關。\n"
    "  2) 若相關，將其歸入下列 5 類其中一個（只能選一個最主要的）：\n"
    f"{_CATEGORY_SPEC}\n"
    "\n回應規則：\n"
    "  - 純 JSON array，與輸入順序對應。\n"
    "  - 每個元素：{\"idx\":int, \"is_ai\":bool, \"category\":str, \"reason\":str}。\n"
    f"  - category 必須是 {CATEGORY_IDS} 其中之一；is_ai=false 時 category 設為 \"none\"。\n"
    "  - reason 控制在 30 字內。\n"
    "  - 不要輸出 JSON 之外的任何文字。"
)


def _build_user_payload(batch: list[dict]) -> str:
    rows = []
    for i, it in enumerate(batch):
        title = (it.get("title") or "")[:200]
        summary = (it.get("summary") or "")[:400]
        source = it.get("source_name", "")
        rows.append(f"[{i}] 來源={source}\n標題：{title}\n摘要：{summary}")
    return "請分類下列 {n} 則新聞：\n\n{rows}".format(n=len(batch), rows="\n\n".join(rows))


def classify_batch(items: list[dict]) -> list[dict]:
    """
    回傳新的 list（每筆加上 is_ai / category / category_label / classify_reason）。
    LLM 失效時：is_ai=True、category="uncategorized"。
    """
    if not items:
        return []

    out = list(items)
    for it in out:
        it.setdefault("is_ai", True)
        it.setdefault("category", "uncategorized")
        it.setdefault("category_label", "未分類")
        it.setdefault("classify_reason", "")

    if not LLM_CLASSIFY_ENABLED:
        return out

    failed_single: list[int] = []
    total_batches = (len(out) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE
    print(f"  共 {total_batches} 批，每批 {LLM_BATCH_SIZE} 則")

    def _apply(batch_idx_in_full: list[int], result_list: list) -> None:
        by_idx = {}
        for r in result_list:
            if isinstance(r, dict) and "idx" in r:
                by_idx[int(r["idx"])] = r
        for local_i, full_i in enumerate(batch_idx_in_full):
            it = out[full_i]
            r = by_idx.get(local_i, {})
            is_ai = bool(r.get("is_ai", True))
            cat = r.get("category", "uncategorized")
            if cat not in CATEGORY_IDS:
                cat = "uncategorized" if is_ai else "none"
            it["is_ai"] = is_ai
            it["category"] = cat
            it["category_label"] = CATEGORY_LABEL_BY_ID.get(cat, "未分類" if is_ai else "非 AI")
            it["classify_reason"] = str(r.get("reason", ""))[:80]

    for start in range(0, len(out), LLM_BATCH_SIZE):
        end = min(start + LLM_BATCH_SIZE, len(out))
        idxs = list(range(start, end))
        batch = [out[i] for i in idxs]
        b_no = start // LLM_BATCH_SIZE + 1
        if b_no % 10 == 0 or b_no == total_batches:
            print(f"  分類中 {b_no}/{total_batches}...", flush=True)
        result = chat_json(_build_user_payload(batch), system=_SYSTEM_PROMPT, max_tokens=4000)
        if isinstance(result, list) and result:
            _apply(idxs, result)
            continue

        # 拆半重試
        if len(batch) > 1:
            half = len(batch) // 2
            r1 = chat_json(_build_user_payload(batch[:half]), system=_SYSTEM_PROMPT, max_tokens=3000)
            r2 = chat_json(_build_user_payload(batch[half:]), system=_SYSTEM_PROMPT, max_tokens=3000)
            ok1 = isinstance(r1, list) and r1
            ok2 = isinstance(r2, list) and r2
            if ok1:
                _apply(idxs[:half], r1)
            if ok2:
                _apply(idxs[half:], r2)
            if ok1 and ok2:
                continue
            # 還沒分到的單筆 fallback
            remaining = [] if ok1 else list(zip(idxs[:half], batch[:half]))
            remaining += [] if ok2 else list(zip(idxs[half:], batch[half:]))
        else:
            remaining = list(zip(idxs, batch))

        for full_i, single in remaining:
            r = chat_json(_build_user_payload([single]), system=_SYSTEM_PROMPT, max_tokens=2000)
            if isinstance(r, list) and r:
                _apply([full_i], r)
            else:
                failed_single.append(full_i)

    if failed_single:
        print(f"  [classify] 終究失敗 {len(failed_single)} 則（已標記未分類）")
    return out


# ─────────────────────────────────────────────────────────────
# 去重
# ─────────────────────────────────────────────────────────────
_PUNCT_RE = re.compile(r"[，。、！？!?,.;:：；\"'`()【】\[\]｜\|—\-－—‘’“”·…．、　\s]+")

# 英文停用詞 — 名稱類詞才有去重訊息量
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "by", "with", "from", "into", "over", "as", "is", "are", "was", "were",
    "be", "been", "being", "has", "have", "had", "do", "does", "did", "this",
    "that", "these", "those", "it", "its", "you", "your", "we", "our", "he",
    "she", "they", "them", "his", "her", "their", "new", "now", "can", "may",
    "via", "vs", "vs.", "amp", "amid",
}


def _norm_title(s: str) -> str:
    s = s.lower()
    # 去掉持有格 's
    s = re.sub(r"['’]s\b", "", s)
    s = _PUNCT_RE.sub("", s)
    return s


def _shingle(s: str, n: int = 4) -> set[str]:
    """字符 n-gram — 對中文很有效，對英文同義改寫稍弱。"""
    s = _norm_title(s)
    if len(s) <= n:
        return {s} if s else set()
    return {s[i:i+n] for i in range(len(s) - n + 1)}


def _word_shingle(s: str) -> set[str]:
    """單字 set — 抓英文同事件 reorder / 多寫一段修飾語 / 中英混排。"""
    s = s.lower()
    s = re.sub(r"['’]s\b", "", s)
    # 把非單字字元換空白；中文字會被保留（\w 含中文）
    s = re.sub(r"[^\w一-鿿]+", " ", s)
    tokens: set[str] = set()
    for t in s.split():
        if not t:
            continue
        if t.isascii():
            if len(t) >= 3 and t not in _STOPWORDS:
                tokens.add(t)
        else:
            # 中文字串再切 2-gram
            for i in range(len(t) - 1):
                tokens.add(t[i:i + 2])
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _best_jaccard(a: dict, b: dict) -> float:
    """雙策略取大：字符 n-gram Jaccard、word-level Jaccard。"""
    ta, tb = a.get("title", ""), b.get("title", "")
    char_j = _jaccard(_shingle(ta), _shingle(tb))
    word_j = _jaccard(_word_shingle(ta), _word_shingle(tb))
    return max(char_j, word_j)


_DEDUP_SYSTEM = (
    "你協助判斷兩則新聞是否在報導相同事件。"
    "若兩者描述的是相同公司+相同主體事件（例如同一個產品發表、同一場融資、同一份論文），"
    "即使語言、措辭、焦點略有不同，也視為同事件。"
    "若是不同產品、不同公司、不同事件（即使主題類似），即視為不同。"
    "輸出純 JSON：{\"same\": true/false, \"reason\": \"30 字內\"}。"
)


def _llm_same(a: dict, b: dict) -> bool:
    if not LLM_DEDUP_ENABLED:
        return False
    prompt = (
        f"新聞 A：\n標題：{a.get('title','')}\n摘要：{a.get('summary','')[:300]}\n\n"
        f"新聞 B：\n標題：{b.get('title','')}\n摘要：{b.get('summary','')[:300]}"
    )
    result = chat_json(prompt, system=_DEDUP_SYSTEM, max_tokens=200)
    return isinstance(result, dict) and bool(result.get("same"))


def dedup(items: list[dict], jaccard_high: float = 0.55, jaccard_check: float = 0.25) -> list[dict]:
    """
    跨分類全域去重；保留摘要較長者，並合併來源欄位。
      ‣ best Jaccard（max of char-shingle / word-shingle）>= jaccard_high
            → 直接視為重複
      ‣ jaccard_check ~ jaccard_high
            → 呼叫 LLM 判斷
      ‣ < jaccard_check
            → 不同

    同一事件被分到不同類別時，保留首見者的類別（避免分類在去重中飄移）；
    若新項摘要更長則覆寫文字內容（但不改類別）。
    """
    kept: list[dict] = []
    n_in_class = 0
    n_cross_class = 0

    for it in items:
        dup_of = None
        for existing_it in kept:
            j = _best_jaccard(it, existing_it)
            if j >= jaccard_high or (j >= jaccard_check and _llm_same(it, existing_it)):
                dup_of = existing_it
                break

        if dup_of is None:
            kept.append(it)
            continue

        # 命中重複：分內 / 跨類計數
        if dup_of.get("category") == it.get("category"):
            n_in_class += 1
        else:
            n_cross_class += 1

        # 若新項摘要更長，覆寫文字內容（不改類別）
        if len(it.get("summary", "")) > len(dup_of.get("summary", "")):
            merged_source = dup_of.get("source_name", "")
            new_source = it.get("source_name", "")
            if new_source and new_source not in merged_source:
                merged_source = f"{merged_source} / {new_source}" if merged_source else new_source
            dup_of.update({
                "title": it["title"],
                "url": it["url"],
                "summary": it["summary"],
                "published": it.get("published") or dup_of.get("published"),
                "source_name": merged_source,
            })
        else:
            # 摘要沒比較長也至少把來源加進來
            cur = dup_of.get("source_name", "")
            new_source = it.get("source_name", "")
            if new_source and new_source not in cur:
                dup_of["source_name"] = f"{cur} / {new_source}" if cur else new_source

    print(f"  去重命中：同類內 {n_in_class} 則、跨類別 {n_cross_class} 則")
    return kept


def dedup_after_rewrite(items: list[dict],
                        jaccard_high: float = 0.40,
                        jaccard_check: float = 0.22) -> list[dict]:
    """
    繁體中文摘要重寫後的第二輪去重。
    此時所有 item 的 summary 都已是繁體中文，可比較 (title + summary) 的 word-shingle，
    抓出原本因「英文 vs 中文」分流、或標題長度差異大而沒抓到的同事件報導。
      ‣ jaccard >= jaccard_high      → 直接合併
      ‣ jaccard_check ~ jaccard_high → 呼叫 LLM 判斷
    """
    def sig(it):
        text = (it.get("title") or "") + " " + (it.get("summary") or "")
        return _word_shingle(text)

    kept: list[dict] = []
    sigs: list[set[str]] = []
    n_merged = 0
    n_by_llm = 0
    for it in items:
        s = sig(it)
        dup_idx = -1
        for i, es in enumerate(sigs):
            j = _jaccard(s, es)
            if j >= jaccard_high:
                dup_idx = i
                break
            if j >= jaccard_check and _llm_same(it, kept[i]):
                dup_idx = i
                n_by_llm += 1
                break
        if dup_idx == -1:
            kept.append(it)
            sigs.append(s)
            continue

        # 命中：合併來源、保留較長 summary（保留首見者的類別與 importance）
        existing = kept[dup_idx]
        n_merged += 1
        new_source = it.get("source_name", "")
        cur = existing.get("source_name", "")
        if new_source and new_source not in cur:
            existing["source_name"] = f"{cur} / {new_source}" if cur else new_source
        if len(it.get("summary", "")) > len(existing.get("summary", "")):
            existing["title"] = it.get("title", existing.get("title", ""))
            existing["summary"] = it.get("summary", existing.get("summary", ""))
    if n_merged:
        print(f"  二次去重（摘要重寫後）合併：{n_merged} 則（其中 {n_by_llm} 則由 LLM 判定）")
    return kept


# ─────────────────────────────────────────────────────────────
# 事件鍵聚類（cluster_by_event）
#
# 動機：標題完全不同、但圍繞同一事件的多角度報導
# （如「Gemini 3.5 Flash 上市」/「Gemini 3.5 Flash 定價分析」/「Gemini 3.5 Flash Agent 應用」）
# 用 Jaccard 抓不到，只能靠 LLM 用「事件鍵」聚類。
# ─────────────────────────────────────────────────────────────
_CLUSTER_SYSTEM = (
    "你是 AI 新聞編輯，正在把多則新聞歸納為事件群。\n"
    "對每則新聞，請輸出一個短的「事件鍵」，格式：\n"
    "    主體 | 動作\n"
    "\n"
    "規則：\n"
    "  ‣ 主體用標準名稱（例如「Gemini 3.5 Flash」「Mistral AI」「OpenAI GPT-5」），"
    "不要持有格、不要冠詞，不要亂加形容詞。\n"
    "  ‣ 動作用 2–6 字描述事件本身（例如「上市發布」「收購」「融資」「合作」"
    "「訴訟」「財報」「定價」「評測」）。\n"
    "  ‣ 不同產品線視為不同主體（GPT-4 與 GPT-5 屬不同鍵；Gemini 2.5 與 Gemini 3.5 屬不同鍵）。\n"
    "  ‣ 但是同一個產品/事件的不同切入角度（例如「Gemini 3.5 上市」「Gemini 3.5 定價分析」"
    "「Gemini 3.5 Agent 應用」「Gemini 3.5 評測」）一律用同一個鍵：「Gemini 3.5 | 上市發布」。\n"
    "  ‣ HuggingFace trending、Ollama Library、OpenRouter 上的單一模型上架算一鍵，例如：「Qwen3-72B | 模型上架」。\n"
    "  ‣ 若真的是獨立事件無法歸類，仍要給一個鍵（用標題主詞 + 動作）。\n"
    "\n"
    "輸入是 JSON array，每筆 {idx, title, summary}。\n"
    "輸出純 JSON array，每筆 {\"idx\": int, \"key\": str}，與輸入一一對應。\n"
    "不要輸出 JSON 以外的文字。"
)


def _norm_event_key(k: str) -> str:
    """規範化事件鍵：去多餘空白、統一中英文管道符號、轉小寫比對用。"""
    k = (k or "").strip()
    k = re.sub(r"\s*[|｜]\s*", "|", k)
    k = re.sub(r"\s+", " ", k)
    return k.lower()


def _extract_event_keys(items: list[dict], batch_size: int = 12) -> list[str]:
    """
    對每個 item 取得事件鍵；失敗回 fallback（標題前 40 字）。
    """
    keys: list[str] = [""] * len(items)
    total_batches = (len(items) + batch_size - 1) // batch_size

    for b in range(total_batches):
        start = b * batch_size
        batch = items[start: start + batch_size]
        rows = []
        for i, it in enumerate(batch):
            rows.append({
                "idx": i,
                "title": (it.get("title") or "")[:150],
                "summary": (it.get("summary") or "")[:300],
            })
        payload = (
            f"請替下列 {len(batch)} 則新聞各標一個事件鍵：\n\n"
            + json.dumps(rows, ensure_ascii=False)
        )
        result = chat_json(payload, system=_CLUSTER_SYSTEM, max_tokens=2000)
        if isinstance(result, list):
            by_idx: dict[int, str] = {}
            for r in result:
                if isinstance(r, dict) and "idx" in r and r.get("key"):
                    try:
                        by_idx[int(r["idx"])] = str(r["key"])
                    except Exception:
                        continue
            for local_i, it in enumerate(batch):
                k = by_idx.get(local_i)
                keys[start + local_i] = k if k else (it.get("title") or "")[:40]
        else:
            # 整批 fallback
            for local_i, it in enumerate(batch):
                keys[start + local_i] = (it.get("title") or "")[:40]

        if (b + 1) % 5 == 0 or b + 1 == total_batches:
            print(f"    事件鍵抽取進度 {b + 1}/{total_batches}", flush=True)
    return keys


def cluster_by_event(items: list[dict]) -> list[dict]:
    """
    以 LLM 抽出的「事件鍵」聚類，同鍵的新聞只保留 importance 最高者（cluster head）。
    為每則 cluster head 補上：
      ‣ mention_count   — 該事件總共有幾則報導（含自己）
      ‣ mention_sources — 所有被合併者的來源 list（去重後）
      ‣ event_key       — LLM 給的事件鍵
      ‣ mention_titles  — 被合併者的標題 list（顯示用）
    """
    if not items:
        return []
    print(f"  LLM 事件鍵聚類（{len(items)} 則）...")
    keys = _extract_event_keys(items)

    # 依鍵分桶（用規範化的鍵做 key）
    buckets: dict[str, list[tuple[int, dict, str]]] = defaultdict(list)
    for i, it in enumerate(items):
        nk = _norm_event_key(keys[i])
        # 太空泛的 key（單字 < 3 char 或沒包含 |）→ 視為獨立桶
        if "|" not in nk or len(nk) < 5:
            nk = f"__solo_{i}__"
        buckets[nk].append((i, it, keys[i]))

    kept: list[dict] = []
    n_collapsed = 0
    for nk, rows in buckets.items():
        # 取 importance 最高者當代表（次序穩定）
        rows_sorted = sorted(
            rows, key=lambda r: (-(r[1].get("importance") or 0), r[0])
        )
        head_i, head, head_key = rows_sorted[0]
        merged_sources: list[str] = []
        merged_titles: list[str] = []
        for idx_in_b, (orig_i, it, raw_key) in enumerate(rows_sorted):
            src = it.get("source_name") or ""
            for piece in [s.strip() for s in src.split("/") if s.strip()]:
                if piece not in merged_sources:
                    merged_sources.append(piece)
            if idx_in_b > 0:
                merged_titles.append(it.get("title") or "")

        head["event_key"] = head_key
        head["mention_count"] = len(rows_sorted)
        head["mention_sources"] = merged_sources
        head["mention_titles"] = merged_titles
        # 把合併來源寫回 source_name（保持向後相容）
        if merged_sources:
            head["source_name"] = " / ".join(merged_sources[:6])

        if len(rows_sorted) > 1:
            n_collapsed += len(rows_sorted) - 1
        kept.append(head)

    # 依 importance 重排
    kept.sort(key=lambda x: x.get("importance", 0), reverse=True)
    if n_collapsed:
        big = sum(1 for it in kept if (it.get("mention_count") or 1) > 1)
        print(f"  事件鍵聚類：折疊 {n_collapsed} 則同事件報導，"
              f"形成 {big} 個熱度群組")
    return kept
