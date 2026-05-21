"""
非 RSS 補充來源 — 開源 AI 模型 / 專案生態
==========================================

這層專門服務「給 AI 小公司看」的需求：

  ‣ HuggingFace Trending Models   — API
  ‣ HuggingFace Daily Papers      — API
  ‣ GitHub Trending (weekly)      — HTML scrape
  ‣ Ollama Library                — HTML scrape
  ‣ OpenRouter Models             — API

回傳的 item dict 與 fetcher.fetch_rss 同 schema，並統一帶
`source_kind="opensource"`，讓 fetcher.prefilter 直接放行、
pipeline 階段強制歸到 products_apps 分類。
"""

from __future__ import annotations
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import FETCH_TIMEOUT


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _http_get(url: str, headers: Optional[dict] = None, timeout: int = FETCH_TIMEOUT) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"  [warn] {url[:70]}: {type(e).__name__}: {e}")
        return None


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


# ─────────────────────────────────────────────────────────────
# 1. HuggingFace Trending Models
# ─────────────────────────────────────────────────────────────
def fetch_hf_trending(days_back: int = 7, limit: int = 30) -> list[dict]:
    """嚴格用 days_back；早於 cutoff 的丟掉。"""
    url = f"https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit={limit}&full=false"
    raw = _http_get(url)
    if not raw:
        return []
    try:
        models = json.loads(raw)
    except Exception:
        return []

    items: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for m in models:
        model_id = m.get("id") or m.get("modelId") or ""
        if not model_id:
            continue
        downloads = m.get("downloads", 0) or 0
        likes = m.get("likes", 0) or 0
        task = m.get("pipeline_tag") or ""
        last_modified = m.get("lastModified") or m.get("createdAt") or ""
        dt: Optional[datetime] = None
        if last_modified:
            try:
                dt = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
            except Exception:
                dt = None
        # 嚴格時間過濾：沒日期或舊於 cutoff 都丟
        if dt is None or dt < cutoff:
            continue

        title = f"[HF Trending] {model_id}"
        summary = (
            f"Hugging Face 熱門模型，任務類型：{task or '未標註'}；"
            f"下載 {downloads:,} 次、likes {likes:,}。"
            f"模型卡：https://huggingface.co/{model_id}"
        )
        items.append({
            "title": title,
            "url": f"https://huggingface.co/{model_id}",
            "summary": summary,
            "published": dt.isoformat() if dt else "",
            "source_name": "HuggingFace Trending",
            "source_region": "GLOBAL",
            "source_kind": "opensource",
            "source_lang": "en",
            "is_opensource": True,
            "downloads": downloads,
            "likes": likes,
            "task": task,
        })
    return items


# ─────────────────────────────────────────────────────────────
# 2. HuggingFace Daily Papers
# ─────────────────────────────────────────────────────────────
def fetch_hf_papers(days_back: int = 7) -> list[dict]:
    url = "https://huggingface.co/api/daily_papers"
    raw = _http_get(url)
    if not raw:
        return []
    try:
        papers = json.loads(raw)
    except Exception:
        return []

    items: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for entry in papers:
        paper = entry.get("paper") or entry
        title = paper.get("title") or ""
        if not title:
            continue
        abstract = paper.get("summary") or paper.get("abstract") or ""
        arxiv_id = paper.get("id") or entry.get("id") or ""
        upvotes = entry.get("upvotes") or paper.get("upvotes") or 0
        pub_str = entry.get("publishedAt") or paper.get("publishedAt") or ""
        dt: Optional[datetime] = None
        if pub_str:
            try:
                dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except Exception:
                dt = None
        # 嚴格：沒日期或舊於 cutoff 都丟
        if dt is None or dt < cutoff:
            continue

        url_paper = f"https://huggingface.co/papers/{arxiv_id}" if arxiv_id else "https://huggingface.co/papers"
        items.append({
            "title": f"[HF Paper] {title}",
            "url": url_paper,
            "summary": f"HuggingFace Daily Papers · upvotes {upvotes}。\n\n{abstract[:600]}",
            "published": dt.isoformat() if dt else "",
            "source_name": "HuggingFace Daily Papers",
            "source_region": "GLOBAL",
            "source_kind": "opensource",
            "source_lang": "en",
            "is_opensource": True,
            "upvotes": upvotes,
        })
    return items


# ─────────────────────────────────────────────────────────────
# 3. GitHub Trending (weekly)
#    沒有官方 API，scrape https://github.com/trending
# ─────────────────────────────────────────────────────────────
_AI_HINT_RE = re.compile(
    r"\b(ai|ml|llm|gpt|llama|mistral|qwen|deepseek|agent|rag|embedding|"
    r"diffusion|transformer|model|inference|train|tokeniz|vision|"
    r"voice|tts|stt|whisper|claude|openai|anthropic|huggingface|"
    r"pytorch|tensor)\b",
    re.I,
)


def _gh_repo_is_ai(repo: str, desc: str, lang: str) -> bool:
    """簡單 AI 相關性過濾，避免 GH trending 帶進太多 frontend/devops repo。"""
    text = f"{repo} {desc}".lower()
    return bool(_AI_HINT_RE.search(text))


def fetch_github_trending(since: str = "weekly", limit: int = 25) -> list[dict]:
    url = f"https://github.com/trending?since={since}&spoken_language_code="
    raw = _http_get(url)
    if not raw:
        return []
    html = raw.decode("utf-8", errors="ignore")

    article_blocks = re.findall(r'<article class="Box-row">(.*?)</article>', html, flags=re.S)
    items: list[dict] = []
    for block in article_blocks:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', block)
        if not m:
            continue
        repo = m.group(1).strip()
        if "/" not in repo:
            continue
        repo = re.sub(r"\s+", "", repo)

        desc_m = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', block, flags=re.S)
        desc = _strip_tags(desc_m.group(1)) if desc_m else ""

        lang_m = re.search(r'itemprop="programmingLanguage"[^>]*>([^<]+)<', block)
        lang = lang_m.group(1).strip() if lang_m else ""

        stars_today_m = re.search(r'(\d[\d,]*)\s*stars (?:this week|today|this month)', block)
        stars_period = stars_today_m.group(1) if stars_today_m else ""

        if not _gh_repo_is_ai(repo, desc, lang):
            continue

        period_name = "今日" if since == "daily" else "本週"
        title = f"[GitHub {period_name}熱門] {repo}"
        bits = []
        if lang:
            bits.append(lang)
        if stars_period:
            bits.append(f"{period_name} +{stars_period} stars")
        prefix = " · ".join(bits)
        summary = f"{prefix}。{desc}" if desc else prefix
        items.append({
            "title": title,
            "url": f"https://github.com/{repo}",
            "summary": summary[:600],
            "published": "",
            "source_name": "GitHub Trending",
            "source_region": "GLOBAL",
            "source_kind": "opensource",
            "source_lang": "en",
            "is_opensource": True,
            "stars": stars_period,
            "lang": lang,
        })
        if len(items) >= limit:
            break
    return items


def parse_relative_time_to_days(s: str) -> float:
    """
    將相對時間字串解析為天數 (float)。
    例如: 'Updated 2 hours ago', 'an hour ago', '10 minutes ago', 'just now'
          'a day ago', '2 days ago', 'yesterday'
          'a week ago', '3 weeks ago'
          'a month ago', '2 months ago'
          'a year ago', '2 years ago'
    解析失敗或格式未知回傳 9999.0。
    """
    s = s.lower().replace("updated", "").strip()
    if not s or "just now" in s or "second" in s or "minute" in s:
        return 0.0
    if "hour" in s:
        m = re.search(r'(\d+)\s+hour', s)
        if m:
            return float(m.group(1)) / 24.0
        return 1.0 / 24.0
    if "day" in s:
        m = re.search(r'(\d+)\s+day', s)
        if m:
            return float(m.group(1))
        return 1.0
    if "week" in s:
        m = re.search(r'(\d+)\s+week', s)
        if m:
            return float(m.group(1)) * 7.0
        return 7.0
    if "month" in s:
        m = re.search(r'(\d+)\s+month', s)
        if m:
            return float(m.group(1)) * 30.0
        return 30.0
    if "year" in s:
        m = re.search(r'(\d+)\s+year', s)
        if m:
            return float(m.group(1)) * 365.0
        return 365.0
    return 9999.0


# ─────────────────────────────────────────────────────────────
# 4. Ollama Library
# ─────────────────────────────────────────────────────────────
def fetch_ollama_library(days_back: int = 7, limit: int = 20) -> list[dict]:
    url = "https://ollama.com/library"
    raw = _http_get(url)
    if not raw:
        return []
    html = raw.decode("utf-8", errors="ignore")

    items: list[dict] = []
    seen: set[str] = set()
    # 結構：每個 model 是一個 <li> 帶 <a href="/library/{name}"> + <p> 描述
    li_re = re.compile(r'<li[^>]*x-test-model[^>]*>(.*?)</li>', re.S)
    for li in li_re.findall(html):
        name_m = re.search(r'href="/library/([^"]+)"', li)
        if not name_m:
            continue
        name = name_m.group(1).strip()
        if name in seen:
            continue
        seen.add(name)

        desc_m = re.search(r'<p[^>]*x-test-model-description[^>]*>(.*?)</p>', li, flags=re.S)
        desc = _strip_tags(desc_m.group(1)) if desc_m else ""

        pulls_m = re.search(r'x-test-pull-count[^>]*>\s*([\d.,KM]+)', li)
        pulls = pulls_m.group(1) if pulls_m else ""
        updated_m = re.search(r'x-test-updated[^>]*>\s*([^<]+)<', li)
        updated = (updated_m.group(1).strip() if updated_m else "")

        # 嚴格時間過濾：若更新天數大於 days_back，則在爬取端直接丟棄
        if updated:
            days_ago = parse_relative_time_to_days(updated)
            if days_ago > days_back:
                continue

        bits = []
        if pulls:
            bits.append(f"pulls {pulls}")
        if updated:
            bits.append(f"updated {updated}")
        meta = " · ".join(bits)

        items.append({
            "title": f"[Ollama 模型] {name}",
            "url": f"https://ollama.com/library/{name}",
            "summary": (f"{meta}。{desc}" if desc else meta) or f"Ollama 開源模型 {name}",
            "published": "",
            "source_name": "Ollama Library",
            "source_region": "GLOBAL",
            "source_kind": "opensource",
            "source_lang": "en",
            "is_opensource": True,
            "pulls": pulls,
            "updated": updated,
        })
        if len(items) >= limit:
            break

    # Fallback：若 x-test-model 選擇器失效，退回粗暴 anchor 解析（保底 5 則）
    if not items:
        for m in re.finditer(r'href="/library/([a-z0-9._\-]+)"', html):
            name = m.group(1)
            if name in seen or "/" in name:
                continue
            seen.add(name)
            items.append({
                "title": f"[Ollama 模型] {name}",
                "url": f"https://ollama.com/library/{name}",
                "summary": f"Ollama 開源模型 {name}",
                "published": "",
                "source_name": "Ollama Library",
                "source_region": "GLOBAL",
                "source_kind": "opensource",
                "source_lang": "en",
                "is_opensource": True,
            })
            if len(items) >= 10:
                break
    return items


# ─────────────────────────────────────────────────────────────
# 5. OpenRouter Models（最新加入的）
# ─────────────────────────────────────────────────────────────
def fetch_openrouter_models(days_back: int = 7, limit: int = 25) -> list[dict]:
    url = "https://openrouter.ai/api/v1/models"
    raw = _http_get(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        models = data.get("data") or data.get("models") or []
    except Exception:
        return []

    models_sorted = sorted(models, key=lambda m: m.get("created", 0), reverse=True)
    items: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for m in models_sorted:
        mid = m.get("id") or ""
        if not mid:
            continue
        name = m.get("name") or mid
        desc = m.get("description") or ""
        created = m.get("created") or 0
        dt: Optional[datetime] = None
        if created:
            try:
                dt = datetime.fromtimestamp(int(created), tz=timezone.utc)
            except Exception:
                dt = None
        if dt and dt < cutoff:
            continue
        # 嚴格：沒日期就丟（OpenRouter 都應該有 created）
        if dt is None:
            continue
        ctx = m.get("context_length") or 0
        pricing = m.get("pricing") or {}
        in_price = pricing.get("prompt") or ""
        out_price = pricing.get("completion") or ""
        bits = []
        if ctx:
            bits.append(f"context={ctx:,}")
        if in_price and out_price:
            bits.append(f"price in={in_price}/out={out_price}")
        meta = " · ".join(bits)

        items.append({
            "title": f"[OpenRouter 新模型] {name}",
            "url": f"https://openrouter.ai/models/{mid}",
            "summary": (f"{meta}。{desc[:500]}" if meta else desc[:500]) or f"OpenRouter 上架模型 {mid}",
            "published": dt.isoformat() if dt else "",
            "source_name": "OpenRouter Models",
            "source_region": "GLOBAL",
            "source_kind": "opensource",
            "source_lang": "en",
            "is_opensource": True,
            "context_length": ctx,
            "pricing": pricing,
        })
        if len(items) >= limit:
            break
    return items


# ─────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────
def fetch_opensource_supplement(days_back: int = 7) -> list[dict]:
    """
    平行版：所有來源依嚴格 days_back 過濾。
    GitHub Trending 與 Ollama Library 不再受限於 days_back，改為每日更新。
      ‣ GH Trending：若 days_back < 7 則抓取 daily，否則抓取 weekly
      ‣ Ollama：     每日抓取最新開源模型
    """
    print(f"開始抓開源生態補強來源（嚴格近 {days_back} 天，平行）...")
    gh_since = "daily" if days_back < 7 else "weekly"
    gh_label = f"GitHub Trending ({gh_since})"
    blocks: list[tuple[str, callable]] = [
        ("HuggingFace Trending",     lambda: fetch_hf_trending(days_back=days_back)),
        ("HuggingFace Daily Papers", lambda: fetch_hf_papers(days_back=days_back)),
        ("OpenRouter Models",        lambda: fetch_openrouter_models(days_back=days_back)),
        (gh_label,                   lambda: fetch_github_trending(since=gh_since)),
        ("Ollama Library",           lambda: fetch_ollama_library(days_back=days_back)),
    ]

    def _safe(label_fn):
        label, fn = label_fn
        try:
            return label, fn()
        except Exception as e:
            return label, e

    all_items: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(2, len(blocks))) as ex:
        for label, result in ex.map(_safe, blocks):
            if isinstance(result, Exception):
                print(f"  [fail] {label}: {type(result).__name__}: {result}")
            else:
                print(f"  [ok]  {label}: {len(result)} 則")
                all_items.extend(result)
    return all_items
