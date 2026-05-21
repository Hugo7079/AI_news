"""
新聞抓取層
==========

  ‣ fetch_rss(url)         — 抓單一 RSS / Atom feed
  ‣ fetch_all_sources()    — 平行抓所有 sources.SOURCES
  ‣ google_news_search(q)  — Google News RSS 搜尋（作為即時 web search）
  ‣ extract_article(url)   — 必要時抓單篇文章內文（用於摘要不足）

設計原則：不依賴付費 API；以 RSS 為主，HTML 抓取為輔。
"""

from __future__ import annotations
import re
import html
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser  # type: ignore

from config import FETCH_TIMEOUT, MAX_PER_SOURCE, NOISE_KEYWORDS, ALL_AI_KEYWORDS, PER_SOURCE_MAX_OVERRIDES
from sources import SOURCES, GOOGLE_NEWS_QUERIES_ZH, GOOGLE_NEWS_QUERIES_EN


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


# ─────────────────────────────────────────────────────────────
# RSS / Atom 解析
# ─────────────────────────────────────────────────────────────
def _parse_published(entry) -> Optional[datetime]:
    """從 feedparser entry 取出發布時間，回傳 UTC datetime。"""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    raw = entry.get("published") or entry.get("updated") or ""
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_rss(source: dict, days_back: int = 7) -> list[dict]:
    """
    抓單一 source；只回近 days_back 天的條目。
    當 days_back ≤ 2（嚴格短窗）時，連同 published 缺失的條目一起丟（多半是老文）。
    """
    url = source["url"]
    name = source["name"]
    items: list[dict] = []

    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"  [warn] {name} 抓取失敗: {type(e).__name__}: {e}")
        return items

    feed = feedparser.parse(raw)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    limit = PER_SOURCE_MAX_OVERRIDES.get(name, MAX_PER_SOURCE)
    strict_no_date = days_back <= 2  # 短窗時連沒日期的也丟

    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        summary = _strip_html(entry.get("summary") or entry.get("description") or "")
        published = _parse_published(entry)
        if published is None:
            if strict_no_date:
                continue
        elif published < cutoff:
            continue

        items.append({
            "title": title,
            "url": link,
            "summary": summary[:1200],
            "published": published.isoformat() if published else "",
            "source_name": name,
            "source_region": source.get("region", ""),
            "source_kind": source.get("kind", ""),
            "source_lang": source.get("lang", ""),
        })
    return items


def fetch_all_sources(days_back: int = 7, parallel: int = 8, only_kinds: Optional[set[str]] = None) -> list[dict]:
    """
    平行抓所有來源；only_kinds 可限制 source kind（media/vendor/community/podcast）。
    """
    targets = [s for s in SOURCES if not only_kinds or s.get("kind") in only_kinds]
    print(f"開始抓 {len(targets)} 個來源（近 {days_back} 天）...")

    all_items: list[dict] = []
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futures = {ex.submit(fetch_rss, s, days_back): s for s in targets}
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                rows = fut.result()
                print(f"  [ok]  {s['name']}: {len(rows)} 則")
                all_items.extend(rows)
            except Exception as e:
                print(f"  [fail] {s['name']}: {e}")
    return all_items


# ─────────────────────────────────────────────────────────────
# Google News 搜尋（即時 Web Search）
# ─────────────────────────────────────────────────────────────
def google_news_search(query: str, hl: str = "zh-TW", gl: str = "TW",
                       max_results: int = 30,
                       cutoff: Optional[datetime] = None) -> list[dict]:
    """
    Google News RSS 搜尋。
    若 cutoff 指定，會解析 pubDate；早於 cutoff 或無法解析的直接丟。
    """
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl={hl}&gl={gl}&ceid={gl}:{hl.split('-')[0]}"
    items: list[dict] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        for item in root.findall(".//item")[:max_results]:
            title = html.unescape(item.findtext("title", "") or "")
            link = item.findtext("link", "") or ""
            desc = html.unescape(item.findtext("description", "") or "")
            source = item.findtext("source", "") or "Google News"
            pub_str = item.findtext("pubDate", "") or ""

            pub_dt: Optional[datetime] = None
            if pub_str:
                try:
                    pub_dt = parsedate_to_datetime(pub_str)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pub_dt = None

            if cutoff is not None:
                # 嚴格時間過濾：沒日期或舊於 cutoff 都丟
                if pub_dt is None or pub_dt < cutoff:
                    continue

            items.append({
                "title": title,
                "url": link,
                "summary": _strip_html(desc)[:800],
                "published": pub_dt.isoformat() if pub_dt else pub_str,
                "source_name": f"GoogleNews:{source}",
                "source_region": "GLOBAL" if hl.startswith("en") else "TW",
                "source_kind": "search",
                "source_lang": hl.split("-")[0],
            })
    except Exception as e:
        print(f"  [warn] Google News 失敗 ({query[:30]}): {e}")
    return items


def google_news_supplement(days_back: int = 1, parallel: int = 6) -> list[dict]:
    """平行版：所有 query 一起送；嚴格時間過濾按 days_back。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    jobs = (
        [(q, "zh-TW", "TW") for q in GOOGLE_NEWS_QUERIES_ZH]
        + [(q, "en-US", "US") for q in GOOGLE_NEWS_QUERIES_EN]
    )
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        results = ex.map(
            lambda j: google_news_search(j[0], hl=j[1], gl=j[2], cutoff=cutoff),
            jobs,
        )
        for r in results:
            out.extend(r)
    print(f"  Google News 補強：{len(out)} 則（{len(jobs)} 個 query 平行 / "
          f"近 {days_back} 天）")
    return out


# ─────────────────────────────────────────────────────────────
# 粗篩
# ─────────────────────────────────────────────────────────────
def is_ai_related(item: dict) -> bool:
    """標題或摘要含任一 AI 關鍵字，且不含噪音字。"""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    if any(nk in text for nk in NOISE_KEYWORDS):
        return False
    lower = text.lower()
    for kw in ALL_AI_KEYWORDS:
        if len(kw) <= 3:
            # 短字使用大小寫敏感、單字邊界（避免 AI 命中 "raise" 之類）
            if re.search(rf"(?<![A-Za-z]){re.escape(kw)}(?![A-Za-z])", text):
                return True
        else:
            if kw.lower() in lower:
                return True
    return False


def prefilter(items: list[dict], verbose: bool = True) -> list[dict]:
    """
    對非 AI vendor / arxiv / Reddit-AI 等來源做 AI 關鍵字粗篩；
    AI 廠商與 AI 專屬社群來源直接全收。
    verbose=True 時印出各來源 (進 → 留) 統計。
    """
    # vendor 部落格 + podcast + 開源生態（HF/GH/Ollama/OpenRouter）全部豁免
    ai_native_kinds = {"vendor", "podcast", "opensource"}
    ai_native_names = {"Reddit r/MachineLearning", "Reddit r/LocalLLaMA",
                       "arXiv cs.AI (新論文)", "arXiv cs.LG (新論文)", "arXiv cs.CL (新論文)",
                       "Hugging Face Blog", "Import AI", "The Decoder",
                       "VentureBeat AI", "iThome AI 專區"}

    from collections import defaultdict
    in_count: dict[str, int] = defaultdict(int)
    out_count: dict[str, int] = defaultdict(int)

    kept: list[dict] = []
    for it in items:
        src = it.get("source_name", "?")
        in_count[src] += 1
        passed = False
        if it.get("source_kind") in ai_native_kinds or it.get("source_name") in ai_native_names:
            text = f"{it.get('title', '')} {it.get('summary', '')}"
            if not any(nk in text for nk in NOISE_KEYWORDS):
                passed = True
        elif is_ai_related(it):
            passed = True
        if passed:
            kept.append(it)
            out_count[src] += 1

    if verbose:
        print("  粗篩明細（進 → 留）：")
        for src in sorted(in_count.keys(), key=lambda s: -in_count[s]):
            i, o = in_count[src], out_count[src]
            pct = f"{o*100//i}%" if i else "-"
            print(f"    {src:40s} {i:>4} → {o:>4}  ({pct})")
    return kept
