"""
封面圖：og:image 抓取 + HF Inference API 生圖（FLUX.1-schnell）
==============================================================

對每則「今日精選」呼叫 attach_cover_images()：
  1) 先試 extract_og_image(url)：抓 <meta property="og:image">
  2) 若失敗（或圖片載不到）→ 用 HF Inference API 生一張 (FLUX.1-schnell)
  3) 寫入 item["cover_image"]：可能是外站 URL 或本地相對路徑

設定（兩種來源任一）：
  ‣ 環境變數 HF_TOKEN
  ‣ st.secrets["HF_TOKEN"]（streamlit 部署）
  ‣ .ainews_llm_config.json 的 "hf_token" 欄位
"""

from __future__ import annotations
import hashlib
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from config import OUTPUT_DIR, BASE_DIR, CATEGORY_LABEL_BY_ID


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HF_MODEL = os.getenv("AINEWS_HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
HF_TIMEOUT = 60


# ─────────────────────────────────────────────────────────────
# Token 載入
# ─────────────────────────────────────────────────────────────
def _load_hf_token() -> str:
    tok = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN") or ""
    if tok:
        return tok

    # Fallback to Streamlit Secrets
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "HF_TOKEN" in st.secrets:
            val = str(st.secrets["HF_TOKEN"]).strip()
            if val:
                return val
    except Exception:
        pass

    cfg_path = BASE_DIR / ".ainews_llm_config.json"
    if cfg_path.exists():
        try:
            with cfg_path.open(encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("hf_token", "") or ""
        except Exception:
            return ""
    return ""


# ─────────────────────────────────────────────────────────────
# og:image 抓取
# ─────────────────────────────────────────────────────────────
_OG_RES = [
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', re.I),
]


def extract_og_image(url: str, timeout: int = 10) -> Optional[str]:
    """從文章 URL 拉 og:image / twitter:image 連結；失敗回 None。"""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(200_000)  # 只讀前 200KB（meta 一定在 <head>）
    except Exception:
        return None

    html = raw.decode("utf-8", errors="ignore")
    for r in _OG_RES:
        m = r.search(html)
        if m:
            img_url = m.group(1).strip()
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                parsed = urllib.parse.urlparse(url)
                img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
            if img_url.startswith("http"):
                return img_url
    return None


def _is_image_reachable(img_url: str, timeout: int = 6) -> bool:
    """簡單 HEAD 檢查圖片可達且不是空殼。"""
    try:
        req = urllib.request.Request(img_url, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            cl = int(resp.headers.get("Content-Length", "0") or "0")
            return ct.startswith("image/") and cl > 2048
    except Exception:
        # 有些站擋 HEAD，改試 GET 前 4KB
        try:
            req = urllib.request.Request(img_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ct = resp.headers.get("Content-Type", "")
                if not ct.startswith("image/"):
                    return False
                return len(resp.read(4096)) >= 2048
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────
# HF Inference API 生圖
# ─────────────────────────────────────────────────────────────
_CATEGORY_STYLE = {
    "tech_research": "abstract neural network nodes, geometric circuits, deep blue and violet gradient, minimal high-tech",
    "industry_business": "modern corporate skyline silhouette with abstract data streams, navy and gold, editorial illustration",
    "hardware_infra": "macro shot of silicon wafer or GPU chip, dark background, cyan glow, photoreal",
    "products_apps": "clean modern dashboard UI on a tilted device, vibrant accent color, soft studio light, isometric",
    "policy_society": "abstract symbol of scales and digital network, neutral palette, minimal editorial illustration",
    "uncategorized": "abstract AI motif, minimal geometric, blue gradient",
}


def _build_image_prompt(title: str, summary: str, category: str) -> str:
    style = _CATEGORY_STYLE.get(category, _CATEGORY_STYLE["uncategorized"])
    keywords = (title + " " + summary)[:200]
    keywords = re.sub(r"[\[\](){}「」『』【】、，。；：！？!?,.;:]", " ", keywords)
    keywords = re.sub(r"\s+", " ", keywords).strip()
    return (
        f"Editorial concept cover art for an AI news article. "
        f"Subject hint: {keywords}. "
        f"Style: {style}. "
        f"Clean composition, no text, no logo, no human face, "
        f"16:9 wide thumbnail."
    )


def _hf_generate(prompt: str, token: str) -> Optional[bytes]:
    if not token:
        return None
    api = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
    body = json.dumps({
        "inputs": prompt,
        "parameters": {"num_inference_steps": 4, "guidance_scale": 0.0, "width": 1024, "height": 576},
        "options": {"wait_for_model": True},
    }).encode()
    req = urllib.request.Request(api, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "image/png",
    })
    try:
        with urllib.request.urlopen(req, timeout=HF_TIMEOUT) as resp:
            data = resp.read()
        if data[:8].startswith(b"\x89PNG") or data[:3] == b"\xff\xd8\xff" or data[:4] == b"RIFF":
            return data
        # 回傳 JSON 錯誤
        try:
            err = json.loads(data.decode("utf-8", errors="ignore"))
            print(f"  [hf-image] error: {err.get('error', err)[:200]}")
        except Exception:
            print(f"  [hf-image] unexpected payload, first bytes: {data[:80]!r}")
        return None
    except Exception as e:
        print(f"  [hf-image] {type(e).__name__}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────
def _short_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def attach_cover_images(items: list[dict], date_str: str,
                        generate_fallback: bool = True,
                        max_generate: int = 20,
                        max_workers: int = 4) -> None:
    """
    平行版：og:image 抓取 + HF 生圖都是 I/O bound，可平行。
      - max_workers 控制同時最多幾個 worker
      - HF 生圖份額由 generated_counter 共用，加鎖確保不超過 max_generate
    """
    img_dir = OUTPUT_DIR / "images" / date_str
    img_dir.mkdir(parents=True, exist_ok=True)
    token = _load_hf_token() if generate_fallback else ""
    if generate_fallback and not token:
        print("  [cover] 未設定 HF_TOKEN — 將跳過 AI 生圖，使用分類 fallback")

    counter_lock = threading.Lock()
    counters = {"og": 0, "gen": 0, "fallback": 0}

    def _one(it: dict):
        url = it.get("url", "")
        cat = it.get("category") or "uncategorized"

        # 1) og:image
        og = extract_og_image(url) if url else None
        if og and _is_image_reachable(og):
            it["cover_image"] = {"kind": "remote", "url": og}
            with counter_lock:
                counters["og"] += 1
            return

        # 2) HF 生圖（份額上限保護）
        do_generate = False
        if token:
            with counter_lock:
                if counters["gen"] < max_generate:
                    counters["gen"] += 1   # 先佔位（萬一失敗下面會還回去）
                    do_generate = True
        if do_generate:
            prompt = _build_image_prompt(it.get("title", ""), it.get("summary", ""), cat)
            img_bytes = _hf_generate(prompt, token)
            if img_bytes:
                fname = f"{_short_id(url or it.get('title', ''))}.png"
                fpath = img_dir / fname
                try:
                    fpath.write_bytes(img_bytes)
                    it["cover_image"] = {"kind": "local", "url": f"images/{date_str}/{fname}"}
                    return
                except Exception as e:
                    print(f"  [cover] 寫檔失敗 {fpath.name}: {e}")
            # 生圖失敗 → 還回份額
            with counter_lock:
                counters["gen"] -= 1

        # 3) Fallback
        it["cover_image"] = {"kind": "fallback", "category": cat}
        with counter_lock:
            counters["fallback"] += 1

    print(f"  封面圖抓取（{len(items)} 則，平行 {max_workers}）...")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_one, items))

    print(f"  封面圖完成：og {counters['og']} 張 / 生成 {counters['gen']} 張 / fallback {counters['fallback']} 張")
