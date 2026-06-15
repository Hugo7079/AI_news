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

from config import OUTPUT_DIR, BASE_DIR, CATEGORY_LABEL_BY_ID, IMAGE_CFG


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
# d8ai gateway 文生圖（OpenAI 相容 /v1/images/generations）
# ─────────────────────────────────────────────────────────────
def _images_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/images/generations"):
        return base
    if re.search(r"/v\d+\w*$", base):
        return base + "/images/generations"
    return base + "/v1/images/generations"


def _gateway_generate(prompt: str) -> Optional[bytes]:
    """呼叫 d8ai gateway 文生圖端點，回傳圖片 bytes；失敗回 None。
    針對 504/503/429 做 3 次指數退避重試（gateway 承載有限，並行容易逾時）。"""
    import time as _time
    base = IMAGE_CFG.get("base_url", "")
    key = IMAGE_CFG.get("api_key", "")
    model = IMAGE_CFG.get("model", "z-image-turbo")
    if not base or not key:
        return None
    url = _images_url(base)
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x576",
    }).encode()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # 502/504/503/429 都當暫時錯誤重試（502 = backend 暫時不可用，gateway 的 vLLM 後端會掛）
    max_attempts = 4
    backoff = 10.0
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=IMAGE_CFG.get("timeout", 120)) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="ignore"))
            break
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504, 429) and attempt < max_attempts:
                _time.sleep(backoff)
                backoff *= 2
                continue
            print(f"  [gw-image] HTTPError {e.code} (attempt {attempt}/{max_attempts})")
            return None
        except Exception as e:
            if attempt < max_attempts:
                _time.sleep(backoff)
                backoff *= 2
                continue
            print(f"  [gw-image] {type(e).__name__}: {e}")
            return None

    data = (obj.get("data") or [{}])[0]
    # 1) b64_json 直出
    b64 = data.get("b64_json")
    if b64:
        try:
            import base64
            return base64.b64decode(b64)
        except Exception:
            pass
    # 2) gateway 回傳暫存 URL（http://...tmp/xxx.png）→ 下載 bytes（tmp 會過期，必須現在抓）
    img_url = data.get("url")
    if img_url:
        try:
            r = urllib.request.Request(img_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(r, timeout=IMAGE_CFG.get("timeout", 120)) as resp2:
                raw = resp2.read()
            if raw[:8].startswith(b"\x89PNG") or raw[:3] == b"\xff\xd8\xff" or raw[:4] == b"RIFF":
                return raw
            print(f"  [gw-image] 下載非圖片：{img_url}")
        except Exception as e:
            print(f"  [gw-image] 下載失敗 {type(e).__name__}: {e}")
        return None
    print(f"  [gw-image] 回應無 b64_json/url：{json.dumps(obj, ensure_ascii=False)[:200]}")
    return None


# ─────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────
def _short_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def attach_cover_images(items: list[dict], date_str: str,
                        generate_fallback: bool = True,
                        max_generate: int = 200,
                        max_workers: int = 1,
                        backend: str = "gateway",
                        retry_passes: int = 2) -> None:
    """
    對每則事件用文生圖模型產生一張封面圖（順序呼叫 + 重試）。
      - backend="gateway"（預設）：呼叫 d8ai gateway 的 /v1/images/generations（z-image-turbo）
      - backend="hf"：沿用舊的 HuggingFace FLUX Inference API
      - max_generate：生圖總量上限（保護）；超過則落分類 fallback
      - retry_passes：失敗的事件最多再掃幾輪重試（gateway 偶爾忙會 504，重試多半就成功）
    生圖失敗 → 落分類 fallback（report.js / app.js 會渲染漸層底圖）。
    """
    img_dir = OUTPUT_DIR / "images" / date_str
    img_dir.mkdir(parents=True, exist_ok=True)

    use_gateway = backend == "gateway" and bool(IMAGE_CFG.get("api_key"))
    hf_token = _load_hf_token() if (backend == "hf") else ""
    if not use_gateway and not hf_token:
        print("  [cover] 未設定文生圖端點（gateway/HF）— 全部使用分類 fallback")

    counter_lock = threading.Lock()
    counters = {"gen": 0, "fallback": 0}

    def _generate(prompt: str) -> Optional[bytes]:
        if use_gateway:
            return _gateway_generate(prompt)
        if hf_token:
            return _hf_generate(prompt, hf_token)
        return None

    def _one(it: dict):
        url = it.get("url", "")
        cat = it.get("category") or "uncategorized"

        # 生圖份額保護（先佔位，失敗再還回）
        do_generate = False
        if use_gateway or hf_token:
            with counter_lock:
                if counters["gen"] < max_generate:
                    counters["gen"] += 1
                    do_generate = True
        if do_generate:
            prompt = _build_image_prompt(it.get("title", ""), it.get("summary", ""), cat)
            img_bytes = _generate(prompt)
            if img_bytes:
                fname = f"{_short_id(url or it.get('title', ''))}.png"
                fpath = img_dir / fname
                try:
                    fpath.write_bytes(img_bytes)
                    it["cover_image"] = {"kind": "local", "url": f"images/{date_str}/{fname}"}
                    return
                except Exception as e:
                    print(f"  [cover] 寫檔失敗 {fpath.name}: {e}")
            with counter_lock:
                counters["gen"] -= 1

        # Fallback：分類底圖
        it["cover_image"] = {"kind": "fallback", "category": cat}
        with counter_lock:
            counters["fallback"] += 1

    src = "d8ai gateway" if use_gateway else ("HF FLUX" if hf_token else "fallback only")
    print(f"  封面圖生成（{len(items)} 則，backend={src}，平行 {max_workers}）...")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_one, items))
    print(f"  封面圖首輪：生成 {counters['gen']} 張 / fallback {counters['fallback']} 張")

    # 重試掃尾：gateway 暫時忙就會 504，掃個一兩輪幾乎都能補齊
    if (use_gateway or hf_token) and retry_passes > 0:
        for round_no in range(1, retry_passes + 1):
            still_failed = [it for it in items
                            if (it.get("cover_image") or {}).get("kind") != "local"]
            if not still_failed:
                break
            print(f"  封面圖重試第 {round_no} 輪：{len(still_failed)} 則待補...")
            # 重試前清掉 fallback 標記讓 _one 重新嘗試（但不還回份額計數）
            for it in still_failed:
                it["cover_image"] = None
                with counter_lock:
                    counters["fallback"] -= 1
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                list(ex.map(_one, still_failed))

    real = sum(1 for it in items
               if (it.get("cover_image") or {}).get("kind") == "local")
    fallback = len(items) - real
    print(f"  封面圖最終：生成 {real} 張 / fallback {fallback} 張")
    if fallback:
        print(f"  [warn] 仍有 {fallback} 則使用分類 fallback（gateway 連續失敗）")
