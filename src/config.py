"""
AI 新聞爬搜整理 — 全域設定
==========================

定義：
  1. 新聞分類架構（目標讀者導向）
  2. AI 相關關鍵字（粗篩用）
  3. 噪音字（排除誤判）
  4. LLM 連線設定（與 emap 同格式）
"""

from __future__ import annotations
import json
import os
from pathlib import Path

# src/ 的上一層 = 專案根目錄（firebase-credentials.json、.ainews_llm_config.json 都放這）
BASE_DIR = Path(__file__).resolve().parents[1]
# 產出目錄：Docker 用 AINEWS_OUTPUT_DIR 指到掛載的 volume
OUTPUT_DIR = Path(os.getenv("AINEWS_OUTPUT_DIR", "").strip() or (BASE_DIR / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 1. 分類架構（5 類）
#
# 設計思路：一般人看 AI 新聞的身份多半是
#   ‣ 技術開發者 / AI 研究者
#   ‣ 創業者 / 投資人 / 商業分析師
#   ‣ 硬體 / 供應鏈從業者（台灣特別多）
#   ‣ 企業 IT / 產品經理 / 一般職場
#   ‣ 政策法務 / 社會關注者
# 對應出 5 大主題類別。
# ─────────────────────────────────────────────────────────────
CATEGORIES: dict[str, dict] = {
    "tech_research": {
        "label": "技術突破與研究",
        "desc": "新模型發表、模型架構創新、量化/壓縮/蒸餾、訓練方法、優化演算法、學術論文、開源框架/工具。",
        "examples": [
            "OpenAI 發表 GPT-X / Claude / Gemini 新版本",
            "新的 attention / MoE / state-space 架構",
            "1-bit 量化、QLoRA、推理加速演算法",
            "arXiv 重要論文、HuggingFace 新模型",
        ],
    },
    "industry_business": {
        "label": "產業動態與商業",
        "desc": "新創融資、併購、IPO、估值、合作、財報、企業 AI 策略、市場份額。",
        "examples": [
            "xAI 完成 $X 億融資",
            "Anthropic 與 AWS 擴大合作",
            "Nvidia 財報、台積電 AI 訂單",
            "AI 新創估值、CEO 異動",
        ],
    },
    "hardware_infra": {
        "label": "硬體與基礎建設",
        "desc": "GPU / NPU / ASIC、半導體、HBM 記憶體、伺服器、資料中心、電力散熱、人形機器人與機器人零組件、供應鏈。",
        "examples": [
            "Nvidia B200 / H200、AMD MI300",
            "HBM3e、CoWoS 先進封裝",
            "Tesla Optimus、Figure 02 人形機器人",
            "AI 資料中心耗電、液冷",
        ],
    },
    "products_apps": {
        "label": "產品與應用",
        "desc": "新產品/服務上市、企業導入、實際使用案例、整合公告、AI 工具評測、開發者體驗。",
        "examples": [
            "Copilot 推出新功能、Notion AI 升級",
            "某銀行 / 醫院導入 AI 系統",
            "AI Agent / Devin 類產品",
            "ChatGPT 用戶數據、App 排行",
        ],
    },
    "policy_society": {
        "label": "政策法規與社會影響",
        "desc": "AI 立法、訴訟、智財權、安全與對齊、勞動衝擊、隱私、教育、社會輿論。",
        "examples": [
            "歐盟 AI Act 進度、美國行政命令",
            "NYT vs OpenAI 著作權訴訟",
            "Deepfake、AI 詐騙、選舉假訊息",
            "AI 對就業/教育衝擊報導",
        ],
    },
}

# 給 LLM 用的可選值（穩定 ID）
CATEGORY_IDS = list(CATEGORIES.keys())
CATEGORY_LABEL_BY_ID = {k: v["label"] for k, v in CATEGORIES.items()}


# ─────────────────────────────────────────────────────────────
# 2. 粗篩用 AI 關鍵字（標題或摘要含其一才進入 LLM 階段）
# ─────────────────────────────────────────────────────────────
AI_KEYWORDS_ZH = [
    # 概念
    "AI", "人工智慧", "人工智能", "生成式 AI", "生成式人工智慧",
    "大模型", "大型語言模型", "語言模型", "多模態", "基礎模型",
    "深度學習", "機器學習", "神經網路", "強化學習",
    # 模型/產品
    "ChatGPT", "GPT", "Claude", "Gemini", "Llama", "Mistral", "Qwen",
    "Grok", "DeepSeek", "Kimi", "豆包", "文心一言", "通義千問",
    "Copilot", "Stable Diffusion", "Sora", "Midjourney", "Runway",
    "Cursor", "Devin", "Perplexity",
    # 公司
    "OpenAI", "Anthropic", "DeepMind", "Hugging Face", "xAI",
    "Cohere", "Stability AI", "Inflection", "Character", "Databricks",
    "Scale AI", "Together AI", "ElevenLabs", "Glean", "Harvey",
    "Cognition", "Replicate", "Groq", "Cerebras", "SambaNova",
    "輝達", "黃仁勳", "馬斯克", "山姆奧特曼", "Sam Altman", "Sundar Pichai",
    # 硬體
    "NPU", "TPU", "AI 晶片", "AI晶片", "AI 伺服器", "AI伺服器",
    "AI 資料中心", "HBM", "HBM3", "HBM4", "CoWoS", "先進封裝",
    "B200", "H100", "H200", "GB200", "GH200", "MI300", "MI325",
    "Blackwell", "Hopper", "Grace",
    # Agent / 代理
    "AI Agent", "AI 代理", "智能體", "代理人 AI",
    # 人形機器人 / Robotics
    "人形機器人", "Optimus", "Figure", "Agility", "Unitree", "宇樹",
    "波士頓動力", "Boston Dynamics", "1X", "Apptronik", "Sanctuary",
    # 技術名詞
    "MoE", "RAG", "LoRA", "QLoRA", "量化", "蒸餾", "微調", "對齊",
    "RLHF", "DPO", "Chain-of-Thought", "CoT", "推理模型",
    "Mamba", "Transformer", "Attention", "State Space",
    "向量資料庫", "vector database",
    # 半導體 / 供應鏈
    "台積電", "TSMC", "ASML", "EUV", "SK海力士", "SK Hynix",
    "三星 HBM", "Samsung HBM", "美光", "Micron",
]

AI_KEYWORDS_EN = [
    # Concepts
    "AI", "artificial intelligence", "AGI", "ASI",
    "machine learning", "deep learning", "reinforcement learning",
    "LLM", "SLM", "VLM", "large language model", "small language model",
    "foundation model", "multimodal", "world model",
    # Models
    "GPT", "Claude", "Gemini", "Llama", "Mistral", "Grok", "Qwen",
    "DeepSeek", "Kimi", "Phi", "Falcon", "Yi", "MiniMax",
    "Stable Diffusion", "Midjourney", "Sora", "Runway",
    "Cursor", "Devin", "Copilot", "Perplexity",
    # Companies
    "OpenAI", "Anthropic", "DeepMind", "xAI", "Hugging Face",
    "Cohere", "Stability AI", "Inflection", "Character.AI",
    "Databricks", "Snowflake AI", "Scale AI", "Together AI",
    "Mistral AI", "ElevenLabs", "AssemblyAI", "Glean", "Harvey",
    "Cognition Labs", "Replicate", "Vercel AI",
    # AI chip companies
    "Nvidia", "AMD MI", "Groq", "Cerebras", "SambaNova",
    "Tenstorrent", "Graphcore", "Etched", "Lightmatter", "Rivos",
    "Trainium", "Inferentia",
    # Hardware
    "HBM", "HBM3", "HBM3e", "HBM4", "CoWoS",
    "B200", "H100", "H200", "GB200", "GH200",
    "MI300", "MI325", "Blackwell", "Hopper",
    "AI datacenter", "AI data center", "AI chip", "AI server",
    "AI accelerator", "AI training", "AI inference", "TPU",
    # Agents / Robotics
    "AI agent", "agentic AI",
    "humanoid robot", "Optimus", "Figure 02", "Figure AI",
    "Agility Robotics", "Unitree", "Boston Dynamics", "Apptronik",
    "Sanctuary AI", "1X Technologies",
    # Techniques
    "MoE", "mixture of experts", "RAG", "LoRA", "QLoRA",
    "quantization", "distillation", "fine-tuning", "alignment",
    "RLHF", "DPO", "chain-of-thought", "reasoning model",
    "Mamba", "transformer", "attention mechanism", "state space model",
    "vector database", "embedding model",
    # Semiconductor supply chain
    "TSMC", "ASML", "SK Hynix", "Samsung HBM", "Micron HBM",
]

ALL_AI_KEYWORDS = AI_KEYWORDS_ZH + AI_KEYWORDS_EN

# 噪音字（標題含其一則丟棄 — 多半非 AI 新聞）
NOISE_KEYWORDS = [
    "星座", "命理", "塔羅",
    "彩券", "樂透",
    "球賽", "棒球", "籃球",
]


# ─────────────────────────────────────────────────────────────
# 3. 預設參數
# ─────────────────────────────────────────────────────────────
DEFAULT_DAYS_BACK = 1           # 每日跑時抓近 N 天
MAX_PER_SOURCE = 50             # 每個來源最多抓幾則（避免 RSS 太長）
ENABLE_GOOGLE_NEWS_DEFAULT = False  # Google News 補強預設關閉（內容過雜）
# arXiv 一天就有上百篇，而且 RSS 沒有任何熱度訊號 —— 全收會讓報表被
# 「某某團隊提出 XXX 框架」洗版（實測佔了進 LLM 總量的 23%）。
# 這裡砍到每類 5 篇，真正有熱度的論文改由 HuggingFace Daily Papers 供給，
# 那是依社群 upvote 篩過的。
PER_SOURCE_MAX_OVERRIDES = {
    "arXiv cs.AI (新論文)": 5,
    "arXiv cs.LG (新論文)": 5,
    "arXiv cs.CL (新論文)": 5,
    "Hacker News (front)": 15,
}
LLM_CLASSIFY_ENABLED = True     # 是否使用 LLM 分類（關掉則只用關鍵字落到「未分類」）
LLM_DEDUP_ENABLED = True        # 是否使用 LLM 去重
LLM_BATCH_SIZE = 5              # LLM 批次大小；推理型模型建議 ≤ 5
LLM_TIMEOUT_OVERRIDE = 90       # 推理型模型較慢，覆寫 LLM timeout
FETCH_TIMEOUT = 15


# ─────────────────────────────────────────────────────────────
# 4. LLM 設定載入（沿用 emap 慣例）
# ─────────────────────────────────────────────────────────────
def load_llm_config() -> dict:
    """
    優先序（後面覆蓋前面）：
      1. 內建預設（只有 base_url / model，沒有金鑰）
      2. .ainews_llm_config.json（本機開發用，已 gitignore）
      3. 環境變數 AINEWS_LLM_API_KEY / _BASE_URL / _MODEL / _TIMEOUT
         （Docker 由 .env 帶入、GitHub Actions 由 workflow 帶入）
    """
    # 金鑰不寫在程式碼裡：Docker 走 .env、GitHub Actions 走 workflow 的 env /
    # secrets、本機開發可放 .ainews_llm_config.json（已 gitignore）。
    cfg = {
        "api_key":  "",
        # Mistral La Plateforme：OpenAI 相容，免費 Experiment tier 每月 10 億 token、
        # 每秒 1 次請求。本專案每天約 220 次呼叫 / 60 萬 token，用掉約 2% 月額度。
        "base_url": "https://api.mistral.ai/v1",
        "model":    "mistral-small-latest",
        "timeout":  90,
    }

    candidates = [
        BASE_DIR / ".ainews_llm_config.json",
        Path.home() / "Desktop" / "臺灣通用電子地圖" / ".emap_llm_config.json",
    ]
    for fp in candidates:
        if fp.exists():
            try:
                with fp.open(encoding="utf-8") as f:
                    file_cfg = json.load(f)
                for k in cfg:
                    if file_cfg.get(k):
                        cfg[k] = file_cfg[k]
                break
            except Exception:
                continue

    env_map = {
        "api_key":  "AINEWS_LLM_API_KEY",
        "base_url": "AINEWS_LLM_BASE_URL",
        "model":    "AINEWS_LLM_MODEL",
        "timeout":  "AINEWS_LLM_TIMEOUT",
    }
    for k, env_key in env_map.items():
        v = os.getenv(env_key, "").strip()
        if v:
            cfg[k] = int(v) if k == "timeout" else v

    return cfg


LLM_CFG = load_llm_config()


# ─────────────────────────────────────────────────────────────
# 5. 文生圖設定
#
# backend 三選一（AINEWS_IMAGE_BACKEND）：
#   cloudflare（預設）— Cloudflare Workers AI 的 FLUX.1 [schnell]
#                       免費額度每天 10,000 neurons；1024×1024 / 4 steps
#                       約 57.6 neurons 一張 → 每天約 173 張，本專案每天
#                       約 68 張，用掉四成不到。
#   gateway           — d8ai gateway 的 OpenAI 相容 /v1/images/generations
#   hf                — HuggingFace Inference API（api-inference 這個 host
#                       已下線，留著只為相容舊設定，實際上叫不通）
# ─────────────────────────────────────────────────────────────
def _local_json_cfg() -> dict:
    """讀 .ainews_llm_config.json（本機開發用，已 gitignore）。讀不到回空 dict。"""
    fp = BASE_DIR / ".ainews_llm_config.json"
    if not fp.exists():
        return {}
    try:
        with fp.open(encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def load_image_config() -> dict:
    """生圖設定。

    來源優先序（後面覆蓋前面）：
      1. 內建預設
      2. .ainews_llm_config.json — 本機開發用，設一次就好，不必每開一個終端機
         都重新 export（cf_account_id / cf_api_token / cf_model 等欄位）
      3. 環境變數 AINEWS_CF_* — CI 與 Docker 走這條
    """
    file_cfg = _local_json_cfg()

    def pick(env_key: str, file_key: str, default: str = "") -> str:
        return (os.getenv(env_key, "").strip()
                or str(file_cfg.get(file_key, "") or "").strip()
                or default)

    # timeout 縮短為 60s（原 120s）：後端抖動時單張圖不再卡 2 分鐘，
    # 讓 CI 90 分鐘預算不被少數卡住的生圖請求吃光。可用環境變數覆寫。
    _img_timeout = os.getenv("AINEWS_IMAGE_TIMEOUT", "").strip()
    _cf_steps = pick("AINEWS_CF_IMAGE_STEPS", "cf_image_steps")
    return {
        "backend":  pick("AINEWS_IMAGE_BACKEND", "image_backend", "cloudflare").lower(),
        # d8ai gateway（backend="gateway" 時才用得到）
        "base_url": os.getenv("AINEWS_IMAGE_BASE_URL", "").strip() or LLM_CFG["base_url"],
        "api_key":  os.getenv("AINEWS_IMAGE_API_KEY", "").strip() or LLM_CFG["api_key"],
        "model":    pick("AINEWS_IMAGE_MODEL", "image_model", "z-image-turbo"),
        # Cloudflare Workers AI
        "cf_account_id": pick("AINEWS_CF_ACCOUNT_ID", "cf_account_id"),
        "cf_api_token":  pick("AINEWS_CF_API_TOKEN", "cf_api_token"),
        "cf_model":      pick("AINEWS_CF_IMAGE_MODEL", "cf_image_model",
                              "@cf/black-forest-labs/flux-1-schnell"),
        # steps 上限 8；4 是官方預設，也是 neuron 花費與品質的平衡點
        "cf_steps":      int(_cf_steps) if _cf_steps else 4,
        "timeout":  int(_img_timeout) if _img_timeout else 60,
    }


IMAGE_CFG = load_image_config()
