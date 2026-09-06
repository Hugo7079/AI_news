"""
封面圖：文生圖（預設 Cloudflare Workers AI 的 FLUX.1 [schnell]）
==================================================================

對每則事件呼叫 attach_cover_images()，產生一張封面並寫入
item["cover_image"]（本地相對路徑）；失敗則落分類 fallback 底圖。

backend 由 AINEWS_IMAGE_BACKEND 決定，預設 "cloudflare"：
  ‣ cloudflare — 需要 AINEWS_CF_ACCOUNT_ID + AINEWS_CF_API_TOKEN
                 免費額度 10,000 neurons/天，一張約 57.6 neurons
  ‣ gateway    — d8ai gateway 的 /v1/images/generations
  ‣ hf         — HuggingFace Inference API（api-inference host 已下線）
"""

from __future__ import annotations
import hashlib
import json
import os
import re
import threading
import time
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
    "industry_business": "modern corporate skyline silhouette with abstract light streams, navy and gold, editorial illustration",
    "hardware_infra": "macro shot of silicon wafer or GPU chip, dark background, cyan glow, photoreal",
    "products_apps": "a sleek device on a tilted angle with a softly glowing abstract blank screen, vibrant accent color, soft studio light, isometric",
    "policy_society": "abstract symbol of scales and digital network, neutral palette, minimal editorial illustration",
    "uncategorized": "abstract AI motif, minimal geometric, blue gradient",
}

# 抑制文字必須放「負向 prompt」（gateway 走 diffusers 後端會吃這個欄位）。
# 千萬別把這些字塞進正向 prompt —— 擴散模型看不懂否定句，只會把 text/letters/word
# 這些 token 當成「要畫的東西」，反而更愛在圖上寫字。
NEGATIVE_PROMPT = (
    "text, words, letters, caption, title, heading, paragraph, typography, font, "
    "writing, handwriting, calligraphy, signage, label, watermark, signature, "
    "logo, brand name, trademark, numbers, digits, ui text, menu, button text, "
    "chart labels, graph axis text, subtitles, gibberish characters, scribbles"
)


_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-\.]{1,}")

_BRIEF_SYSTEM = (
    "You are an art director for a tech-news magazine. You turn a Chinese AI-news "
    "headline into ONE concise English visual scene for a text-to-image model."
)


def _llm_visual_brief(title: str, summary: str) -> str:
    """用 LLM 把中文新聞轉成一句具體的英文視覺場景（讓圖片與事件相關）。
    失敗回空字串（呼叫端會退回品牌名 fallback）。"""
    try:
        from llm import chat
    except Exception:
        return ""
    prompt = (
        "Chinese AI news:\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n\n"
        "Describe ONE concrete, literal visual scene that represents this news, "
        "for a magazine cover image. Rules:\n"
        "- 12 to 25 English words, a single phrase, no sentence-ending period needed.\n"
        "- Focus on PHYSICAL, depictable objects/subjects (e.g. a silicon wafer, a humanoid "
        "robot, a data center server rack, a GPU chip, a self-driving car, a robotic arm). "
        "Make it specific to THIS news, not generic.\n"
        "- AVOID anything that forces the image to contain writing: do NOT describe screens "
        "showing readable content, charts/graphs with axes or labels, dashboards, UI mockups, "
        "logos, books, newspapers, documents, road signs, or keyboards with letters. If a "
        "screen or display must appear, describe it as showing abstract glowing visuals only.\n"
        "- Do NOT use any brand names, company names, product names, acronyms, or proper nouns "
        "(such as 'OpenAI', 'Google', 'Apple', 'Anthropic', 'Gemini', 'GPT', 'Siri', 'Nvidia', "
        "'TCS', 'KPMG', etc.). Instead use generic descriptions (e.g. 'a server rack', "
        "'a microchip', 'a robotic arm').\n"
        "- The scene must contain NO text, letters, words, logos, or numbers at all.\n"
        "- Output ONLY the scene phrase in English, nothing else."
    )
    try:
        raw = chat(prompt, system=_BRIEF_SYSTEM, temperature=0.4, max_tokens=4000)
    except Exception:
        return ""
    brief = (raw or "").strip().strip('"').splitlines()[0] if raw else ""
    # 去掉模型偶爾加的前綴
    brief = re.sub(r"^(scene|visual|description|answer)\s*[:：-]\s*", "", brief, flags=re.I)
    # 太長就截斷
    return brief[:200].strip()


_CATEGORY_FALLBACK_SUBJECTS = {
    "tech_research": "futuristic glowing holographic network nodes on dark background",
    "industry_business": "modern glass office towers at dusk with abstract glowing light trails",
    "hardware_infra": "glowing close-up shot of silicon microchips and electronic circuits",
    "products_apps": "a sleek smartphone on a stand with a softly glowing blank gradient screen, studio lighting",
    "policy_society": "abstract minimalist scales of justice on a glowing digital network mesh",
    "uncategorized": "abstract glowing geometric connections on violet and blue gradient",
}


def _build_image_prompt(title: str, summary: str, category: str,
                        use_llm: bool = True) -> str:
    """產生純英文 prompt，讓圖片與新聞相關且不含文字。
    策略（皆經 live z-image-turbo 實測）：
      1) 用 LLM 把中文新聞轉成具體英文視覺場景（主要相關性來源）
      2) LLM 失敗才退回分類通用主題 fallback
      3) 正向 prompt 「完全不提」text/letters/word 等字眼——擴散模型看不懂否定，
         提到反而會畫字。去字一律靠 NEGATIVE_PROMPT（見 _gateway_generate）。
      4) 絕對不要用 "magazine cover / poster / editorial cover" 之類框架——模型學到
         「雜誌封面＝頂部要放大標題」，會強制生標題文字。改用純場景「cinematic
         photograph」描述，實測即可去除頂部標題字。
    """
    style = _CATEGORY_STYLE.get(category, _CATEGORY_STYLE["uncategorized"])

    subject = _llm_visual_brief(title, summary) if use_llm else ""
    if not subject:
        # fallback：使用無文字的分類通用科技主題描述
        subject = _CATEGORY_FALLBACK_SUBJECTS.get(category, _CATEGORY_FALLBACK_SUBJECTS["uncategorized"])

    return (
        "A wide 16:9 cinematic photograph or clean 3D render. "
        f"{subject}. "
        f"Art direction: {style}. "
        "Cinematic lighting, single clear focal subject, professional composition, "
        "smooth clean uncluttered surfaces, no human faces."
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
# Cloudflare Workers AI 文生圖（FLUX.1 [schnell]）
#
# 端點：POST /client/v4/accounts/{account_id}/ai/run/{model}
# 入參只吃 prompt / steps（上限 8）/ seed —— 沒有 width / height，
# 出圖固定正方形。前端 .lead-cover 是 aspect-ratio 16/9 + cover，
# 瀏覽器會自己置中裁切，所以不需要在這裡再處理比例。
# 回應是 JSON：{"result": {"image": "<base64 JPEG>"}, "success": true}
# ─────────────────────────────────────────────────────────────
_CF_ACCOUNT_RE = re.compile(r"^[0-9a-f]{32}$")

# 撞到「當日額度用完」就設起來 —— 這種 429 重試沒有意義，整批作業該直接收手
_cf_quota_exhausted = False


def cf_quota_exhausted() -> bool:
    return _cf_quota_exhausted


def check_cf_config() -> Optional[str]:
    """檢查 Cloudflare 設定是否像樣；有問題回一句人話，沒問題回 None。

    account id 是 32 位小寫十六進位、token 是純 ASCII。先擋掉明顯不對的值，
    否則中文佔位字會一路帶到 urllib 才炸出 UnicodeEncodeError，訊息完全看不出
    是設定沒填。"""
    account = IMAGE_CFG.get("cf_account_id", "")
    token = IMAGE_CFG.get("cf_api_token", "")
    if not account:
        return "AINEWS_CF_ACCOUNT_ID 沒有設定"
    if not token:
        return "AINEWS_CF_API_TOKEN 沒有設定"
    if not _CF_ACCOUNT_RE.match(account):
        return (f"AINEWS_CF_ACCOUNT_ID 格式不對：{account!r}\n"
                f"    應該是 32 位小寫十六進位（例如 8f14e45fceea167a5a36dedd4bea2543）。\n"
                f"    在 dash.cloudflare.com 的網址列，或 Workers & Pages 右側欄可以找到。")
    if not token.isascii():
        return (f"AINEWS_CF_API_TOKEN 含有非 ASCII 字元 —— 看起來是佔位文字沒換掉。\n"
                f"    到 dash.cloudflare.com/profile/api-tokens 建一把，"
                f"權限選 Account → Workers AI → Read。")
    return None


def verify_cf_token(timeout: int = 15) -> Optional[str]:
    """跟 Cloudflare 確認 token 本身有效；有問題回一句人話，沒問題回 None。

    這是網路呼叫，只在批次作業開跑前做一次 —— 比讓每一張圖各自撞 401 便宜太多
    （每次撞牆前都會先花一次 LLM 呼叫去產視覺提示）。"""
    problem = check_cf_config()
    if problem:
        return problem
    token = IMAGE_CFG.get("cf_api_token", "")
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/user/tokens/verify",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return (f"Cloudflare 不認這把 token（長度 {len(token)}、"
                    f"開頭 {token[:4]!r}）。\n"
                    f"    標準的 Cloudflare API token 是 40 個字元、沒有前綴。\n"
                    f"    到 dash.cloudflare.com/profile/api-tokens → Create Token，\n"
                    f"    用 Workers AI 範本（或 Custom：Account → Workers AI → Read），\n"
                    f"    再把它填進 .ainews_llm_config.json 的 cf_api_token。")
        return f"驗證 token 時收到 HTTP {e.code}"
    except Exception as e:
        # 網路問題不該擋住整批作業，交給實際呼叫去處理
        print(f"  [cf-image] token 預檢跳過（{type(e).__name__}）")
        return None

    status = (obj.get("result") or {}).get("status")
    if status and status != "active":
        return f"token 狀態是 {status!r}，不是 active —— 可能已被停用或過期"
    return None


def _cf_generate(prompt: str) -> Optional[bytes]:
    import base64
    import time as _time

    problem = check_cf_config()
    if problem:
        print(f"  [cf-image] {problem}")
        return None

    account = IMAGE_CFG.get("cf_account_id", "")
    token = IMAGE_CFG.get("cf_api_token", "")
    model = IMAGE_CFG.get("cf_model", "@cf/black-forest-labs/flux-1-schnell")

    url = (f"https://api.cloudflare.com/client/v4/accounts/{account}"
           f"/ai/run/{model}")
    payload = json.dumps({
        "prompt": prompt[:2048],           # 官方上限 2048 字元
        "steps": max(1, min(8, int(IMAGE_CFG.get("cf_steps", 4)))),
    }).encode()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    }

    # 429 = 當天 neuron 用完或瞬間超速；5xx = 暫時性。退避重試 3 次。
    max_attempts = 3
    backoff = 3.0
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=IMAGE_CFG.get("timeout", 60)) as resp:
                ctype = resp.headers.get("Content-Type", "")
                raw = resp.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")[:200]
            except Exception:
                pass
            # 429 有兩種：短時間內請求太密（等一下就好），以及當日免費額度用完
            # （等到 UTC 隔天才會恢復，重試再多次都沒用）。用訊息內容區分。
            # 注意 body 上面已經讀過了 —— HTTPError 的 body 只能讀一次，
            # 這裡不能再 e.read()，否則永遠拿到空字串、判斷不出是哪一種 429。
            if e.code == 429 and ("daily free allocation" in body
                                  or "used up your daily" in body):
                global _cf_quota_exhausted
                _cf_quota_exhausted = True
                print("  [cf-image] 今日 Cloudflare 免費額度（10,000 neurons）已用完，"
                      "UTC 隔日 00:00（台灣時間早上 8 點）才會重置")
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                _time.sleep(backoff)
                backoff *= 2
                continue
            # 401/403 = token 沒權限或過期；404 = account id 或 model 名稱不對。
            # 這幾種重試再多次也一樣，直接講清楚要去改什麼。
            if e.code in (401, 403):
                print(f"  [cf-image] {e.code}：AINEWS_CF_API_TOKEN 無效或缺少 "
                      f"Workers AI 權限")
            elif e.code == 404:
                print(f"  [cf-image] 404：AINEWS_CF_ACCOUNT_ID（目前 "
                      f"{account!r}）或模型名稱不對")
            else:
                print(f"  [cf-image] HTTPError {e.code} "
                      f"(attempt {attempt}/{max_attempts}): {body}")
            return None
        except Exception as e:
            if attempt < max_attempts:
                _time.sleep(backoff)
                backoff *= 2
                continue
            print(f"  [cf-image] {type(e).__name__}: {e}")
            return None

        # 少數模型直接回二進位圖
        if ctype.startswith("image/"):
            return raw
        try:
            obj = json.loads(raw.decode("utf-8", errors="ignore"))
        except ValueError:
            print(f"  [cf-image] 回應不是 JSON：{raw[:120]!r}")
            return None

        if not obj.get("success", True):
            errs = obj.get("errors") or obj.get("messages") or obj
            print(f"  [cf-image] API 回報失敗：{json.dumps(errs, ensure_ascii=False)[:200]}")
            return None

        b64 = ((obj.get("result") or {}).get("image")) or ""
        if not b64:
            print(f"  [cf-image] 回應無 result.image：{json.dumps(obj, ensure_ascii=False)[:200]}")
            return None
        try:
            return base64.b64decode(b64)
        except Exception as e:
            print(f"  [cf-image] base64 解碼失敗：{e}")
            return None

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
        "negative_prompt": NEGATIVE_PROMPT,  # 去字主力；gateway 不支援時會被忽略，無害
        "n": 1,
        "size": "1024x576",
    }).encode()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # 502/504/503/429 都當暫時錯誤重試（502 = backend 暫時不可用，gateway 的 vLLM 後端會掛）
    # 快速失敗：max_attempts 4→2、backoff 10→4，避免單張圖在 gateway 抖動時
    # 卡掉 (120s×4 + 10+20+40) ≈ 9 分鐘、拖垮整個 90 分鐘 CI 預算。掃尾重試輪
    # （retry_passes）仍會再給失敗事件機會。
    max_attempts = 2
    backoff = 4.0
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


# 封面在網站上是 16:9（.lead-cover），PDF 是 52mm 橫幅。生圖後端給的是
# 1024×1024 正方形、約 485KB，直接存等於讓瀏覽器載三倍體積再自己裁掉。
COVER_WIDTH = int(os.getenv("AINEWS_COVER_WIDTH", "1024"))
COVER_RATIO = (16, 9)
COVER_QUALITY = int(os.getenv("AINEWS_COVER_QUALITY", "82"))


def postprocess_cover(data: bytes) -> bytes:
    """置中裁成 16:9、縮到 COVER_WIDTH、輸出 JPEG。

    Pillow 沒裝就原樣回傳 —— 圖還是能用，只是檔案大一點，不該為了瘦身讓整條
    pipeline 掛掉。"""
    try:
        import io
        from PIL import Image
    except ImportError:
        return data

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")

        tw, th = COVER_RATIO
        w, h = im.size
        # 置中裁出最大的 16:9 區域
        if w * th > h * tw:
            new_w = int(round(h * tw / th))
            left = (w - new_w) // 2
            im = im.crop((left, 0, left + new_w, h))
        else:
            new_h = int(round(w * th / tw))
            top = (h - new_h) // 2
            im = im.crop((0, top, w, top + new_h))

        target = (COVER_WIDTH, int(round(COVER_WIDTH * th / tw)))
        if im.size[0] > target[0]:
            im = im.resize(target, Image.LANCZOS)

        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=COVER_QUALITY, optimize=True, progressive=True)
        return buf.getvalue()
    except Exception as e:
        print(f"  [cover] 後處理失敗（保留原圖）：{type(e).__name__}: {e}")
        return data


def image_ext(data: bytes) -> str:
    """看 magic bytes 判斷副檔名。不同後端吐的格式不一樣 ——
    Cloudflare flux-1-schnell 回 JPEG、gateway 回 PNG —— 一律寫死 .png
    會產生副檔名與內容不符的檔案，上傳時 content-type 也會標錯。"""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "png"


def prefill_og_covers(items: list[dict], max_workers: int = 10) -> int:
    """
    先用文章自己的 og:image 當封面，抓不到才輪到生圖。

    為什麼重要：生圖一張約 57.6 neurons，一天 100 則就是 5,760，
    而 Cloudflare 免費額度是每天 10,000、且與其他專案共用同一個帳號。
    全部用生圖等於把整鍋額度吃光，別的東西就餓死了。
    真圖對新聞站來說也比 AI 生成的誠實 —— 生圖只該是沒有原圖時的退路。
    """
    todo = [it for it in items
            if not (isinstance(it.get("cover_image"), dict)
                    and it["cover_image"].get("url"))]
    if not todo:
        return 0

    def _grab(it: dict) -> bool:
        for s in (it.get("sources") or [])[:3]:
            u = s.get("url") or ""
            if not u:
                continue
            img = extract_og_image(u)
            if img:
                it["cover_image"] = {"kind": "remote", "url": img}
                return True
        return False

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        got = sum(1 for ok in ex.map(_grab, todo) if ok)
    print(f"  封面 og:image：{got}/{len(todo)} 則抓到文章原圖（不必生圖）")
    return got


def attach_cover_images(items: list[dict], date_str: str,
                        generate_fallback: bool = True,
                        max_generate: int = 150,
                        max_workers: int = 3,
                        backend: str | None = None,
                        retry_passes: int = 2,
                        deadline: float | None = None) -> None:
    """
    對每則事件用文生圖模型產生一張封面圖（平行呼叫 + 重試）。
      - backend=None（預設）：讀 IMAGE_CFG["backend"]（環境變數 AINEWS_IMAGE_BACKEND）
        ‣ "cloudflare"：Cloudflare Workers AI 的 FLUX.1 [schnell]（目前的預設）
        ‣ "gateway"   ：d8ai gateway 的 /v1/images/generations（z-image-turbo）
        ‣ "hf"        ：HuggingFace Inference API（host 已下線，僅為相容保留）
      - max_generate：生圖總量上限（保護）；超過則落分類 fallback。
        預設 150 是照 Cloudflare 免費額度抓的：10,000 neurons/天 ÷ 約 57.6
        neurons/張 ≈ 173 張，留一點餘裕給重試。
      - max_workers：平行度（生圖走獨立 urllib，不受 llm.py 8 RPM 限制）。預設 3，
        比舊的順序（1）快 2-3 倍；仍保留 retry_passes 吸收偶發 504。
      - retry_passes：失敗的事件最多再掃幾輪重試（gateway 偶爾忙會 504，重試多半就成功）
      - deadline：time.monotonic() 時間點；超過就對「尚未產圖」的事件直接落 fallback，
        確保 CI 90 分鐘預算內一定能寫出報表（不再被 cancel）。
    生圖失敗 → 落分類 fallback（report.js / app.js 會渲染漸層底圖）。
    """
    img_dir = OUTPUT_DIR / "images" / date_str
    img_dir.mkdir(parents=True, exist_ok=True)

    backend = (backend or IMAGE_CFG.get("backend") or "cloudflare").lower()

    use_cf = backend == "cloudflare" and bool(
        IMAGE_CFG.get("cf_account_id") and IMAGE_CFG.get("cf_api_token"))
    use_gateway = backend == "gateway" and bool(IMAGE_CFG.get("api_key"))
    hf_token = _load_hf_token() if (backend == "hf") else ""
    # Cloudflare 憑證先驗一次：錯的話 68 張圖會各撞一次 401，而每次撞牆前
    # 都先花一次 LLM 呼叫產視覺提示 —— 白燒 68 次額度還拖慢整個 run。
    # 這裡不 raise，改成安靜退回分類 fallback，報表照樣產得出來。
    if use_cf:
        problem = verify_cf_token()
        if problem:
            print(f"  [cover] Cloudflare 憑證有問題，本次全部改用分類 fallback：\n"
                  f"          {problem}")
            use_cf = False

    can_generate = bool(use_cf or use_gateway or hf_token)
    if not can_generate:
        if backend == "cloudflare":
            print("  [cover] 未設定 AINEWS_CF_ACCOUNT_ID / AINEWS_CF_API_TOKEN"
                  " — 全部使用分類 fallback")
        else:
            print(f"  [cover] backend={backend} 未設定完整 — 全部使用分類 fallback")

    counter_lock = threading.Lock()
    counters = {"gen": 0, "fallback": 0}

    def _generate(prompt: str) -> Optional[bytes]:
        if use_cf:
            return _cf_generate(prompt)
        if use_gateway:
            return _gateway_generate(prompt)
        if hf_token:
            return _hf_generate(prompt, hf_token)
        return None

    def _one(it: dict):
        url = it.get("url", "")
        cat = it.get("category") or "uncategorized"

        # 已經有真圖（og:image 前置階段抓到的）就不要再生一張蓋掉
        cover = it.get("cover_image")
        if isinstance(cover, dict) and cover.get("kind") == "remote" and cover.get("url"):
            with counter_lock:
                counters["og"] = counters.get("og", 0) + 1
            return

        # 時間預算保險：超過 deadline 就不再生圖，直接落 fallback（快速收尾）
        if deadline is not None and time.monotonic() > deadline:
            it["cover_image"] = {"kind": "fallback", "category": cat}
            with counter_lock:
                counters["fallback"] += 1
            return

        # 生圖份額保護（先佔位，失敗再還回）
        do_generate = False
        if can_generate:
            with counter_lock:
                if counters["gen"] < max_generate:
                    counters["gen"] += 1
                    do_generate = True
        if do_generate:
            prompt = _build_image_prompt(it.get("title", ""), it.get("summary", ""), cat)
            img_bytes = _generate(prompt)
            if img_bytes:
                img_bytes = postprocess_cover(img_bytes)
                fname = f"{_short_id(url or it.get('title', ''))}.{image_ext(img_bytes)}"
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

    src = ("Cloudflare FLUX.1-schnell" if use_cf else
           "d8ai gateway" if use_gateway else
           "HF FLUX" if hf_token else "fallback only")
    print(f"  封面圖生成（{len(items)} 則，backend={src}，平行 {max_workers}）...")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_one, items))
    print(f"  封面圖首輪：原圖 {counters.get('og', 0)} 張 / "
          f"生成 {counters['gen']} 張 / fallback {counters['fallback']} 張")

    # 重試掃尾：gateway 暫時忙就會 504，掃個一兩輪幾乎都能補齊
    if can_generate and retry_passes > 0:
        for round_no in range(1, retry_passes + 1):
            if deadline is not None and time.monotonic() > deadline:
                print("  封面圖：已達時間預算上限，跳過剩餘重試")
                break
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
