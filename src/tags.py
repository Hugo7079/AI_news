"""
雙層分類的第二層：主題標籤 tags[]
================================

第一層 category（6 類、單選、長期凍結）回答「這件事屬於產業價值鏈的哪一段」；
第二層 tags（0–3 個、多選、字典可增減）回答「這件事涉及什麼主題」。

設計原則（依 2026-11-19 討論紀錄）：
  1. 不破壞主分類曲線：新增標籤不動 category，舊的分類趨勢圖不會斷層。
  2. 跨領域不打架：例如「AI Agent 遭提示注入造成外洩」主類歸 cybersecurity，
     標籤同時掛 ai_security、ai_agent。
  3. 專區不綁主分類：前端可直接用某個 tag 篩出專題觀測區。
  4. 新標籤可低成本回溯：用 rule_tags()（關鍵詞）或批次 LLM 替歷史事件補 tags，
     只補寫 tags，不改主分類（見 scripts/backfill_tags.py）。
  5. 0–3 個：字典裡沒有合適的就不標，不硬套最接近的標籤，避免汙染該標籤的趨勢曲線。

字典治理：
  - 標籤 id 一經上線就不改名；不用了就標 deprecated，不刪除（歷史資料還在用）。
  - 每次增減標籤都要更新 TAGS_VERSION；有 stats_meta.py 的專案另在 PIPELINE_MILESTONES 補一筆。
  - 兩個專案（AI新聞爬搜整理、AInews）共用同一份 tags.py，改一邊要同步另一邊。
  - keywords 只給歷史回溯（rule_tags）用；每日 pipeline 由抽事件的 LLM 直接給 tags。

v1 字典是用 2026-05-20 → 2026-11-19 共 16,208 則歷史事件歸納出的子主題收斂而成。
"""

from __future__ import annotations
import re
from typing import Iterable

TAGS_VERSION = "v1"
MAX_TAGS = 3

# 群組只用於顯示與 prompt 排版，不是另一層分類
TAG_GROUPS: list[str] = [
    "模型與技術", "Agent 與開發", "應用場景", "硬體與基礎建設",
    "產業與資本", "政策與社會", "資訊安全",
]

# id → {label, group, desc, keywords, exclude, since}
#   desc     ：給抽事件 LLM 看的一行定義（越短越好，影響每次呼叫的 token 數）
#   keywords ：歷史回溯用的 regex（不分大小寫），比對 title + summary + what
#   exclude  ：命中就不標（排除常見誤標）
TAGS: dict[str, dict] = {
    # ───────────────────────── 模型與技術 ─────────────────────────
    "frontier_model": {
        "label": "前沿旗艦模型", "group": "模型與技術",
        "desc": "頂級廠商旗艦模型的發布、改版與能力比較（GPT、Gemini、Claude、Grok 等）",
        "keywords": [r"GPT-?[5-9](\.\d)?\b", r"Gemini ?[3-9]", r"Claude (Opus|Sonnet|Haiku|Mythos|Fable)",
                     r"\bOpus ?[4-9]", r"Mythos", r"Fable ?5", r"Grok ?[4-9]", r"旗艦模型",
                     r"frontier model", r"前沿模型"],
        "exclude": [r"GGUF"],
    },
    "reasoning": {
        "label": "推理模型", "group": "模型與技術",
        "desc": "推理／思考型模型、思維鏈、test-time compute",
        "keywords": [r"推理模型", r"推理能力", r"思維鏈", r"chain[- ]of[- ]thought", r"\bCoT\b",
                     r"\breasoning\b", r"test[- ]time (compute|scaling)", r"深度思考", r"思考模式",
                     r"thinking ?(模型|model|mode|模式)", r"推理蒸餾"],
    },
    "model_training": {
        "label": "訓練方法與新架構", "group": "模型與技術",
        "desc": "強化學習、後訓練、微調、MoE／SSM／擴散語言模型等新架構",
        "keywords": [r"強化學習", r"reinforcement learning", r"\bRLHF\b", r"\bRLVR\b", r"\bGRPO\b",
                     r"\bDPO\b", r"獎勵模型", r"reward model", r"後訓練", r"post[- ]training",
                     r"監督式微調", r"\bLoRA\b", r"微調", r"擴散語言模型", r"diffusion language",
                     r"狀態空間", r"state[- ]space", r"\bSSM\b", r"Mamba", r"\bMoE\b", r"混合專家",
                     r"mixture[- ]of[- ]experts", r"線性注意力", r"linear attention", r"稀疏注意力",
                     r"sparse attention", r"\bRWKV\b"],
    },
    "inference_efficiency": {
        "label": "推論效率與本地部署", "group": "模型與技術",
        "desc": "推論加速與成本、量化、本地部署與推論引擎（vLLM、llama.cpp、Ollama）",
        "keywords": [r"推論", r"\binference\b", r"推理(晶片|加速|引擎|服務|成本|效率|框架|優化|速度)",
                     r"KV[- ]?cache", r"KV 快取", r"speculative", r"投機(解碼|採樣)", r"\bvLLM\b",
                     r"SGLang", r"TensorRT", r"吞吐量", r"GGUF", r"llama\.cpp", r"量化", r"quantiz",
                     r"本地(運行|部署|執行|推論|推理)", r"Ollama", r"\bMLX\b", r"VRAM", r"消費級顯卡"],
    },
    "on_device_ai": {
        "label": "端側 AI", "group": "模型與技術",
        "desc": "手機、PC、邊緣裝置上執行的 AI 與小模型（NPU、AI PC）",
        "keywords": [r"端側", r"裝置端", r"on[- ]device", r"AI ?PC", r"\bNPU\b", r"邊緣 ?AI", r"edge AI",
                     r"小型(語言)?模型", r"\bSLM\b", r"small language model", r"Copilot\+ ?PC", r"離線運行"],
    },
    "open_source": {
        "label": "開源模型與工具", "group": "模型與技術",
        "desc": "開源／開放權重模型與開源 AI 工具的發布（不論國別）",
        "keywords": [r"開源", r"open[- ]source", r"開源權重", r"open[- ]weight", r"開放權重", r"Gemma",
                     r"Llama ?\d", r"Mistral", r"Nemotron", r"\bOLMo", r"gpt-oss", r"Qwen",
                     r"DeepSeek", r"Hugging ?Face"],
    },
    "china_ai": {
        "label": "中國 AI", "group": "模型與技術",
        "desc": "中國模型廠與 AI 生態（DeepSeek、Qwen、Kimi、GLM、MiniMax、華為昇騰等）",
        "keywords": [r"Qwen", r"通義", r"DeepSeek", r"深度求索", r"\bKimi\b", r"月之暗面", r"Moonshot",
                     r"\bGLM", r"智譜", r"MiniMax", r"文心", r"ERNIE", r"混元", r"Hunyuan", r"豆包",
                     r"Doubao", r"字節跳動", r"ByteDance", r"百川", r"階躍", r"StepFun", r"華為",
                     r"Huawei", r"昇騰", r"Ascend", r"寒武紀", r"中芯", r"SMIC", r"摩爾線程"],
    },
    "multimodal": {
        "label": "多模態", "group": "模型與技術",
        "desc": "視覺語言模型、多模態理解、OCR 與文件理解",
        "keywords": [r"多模態", r"multimodal", r"視覺語言", r"\bVLM\b", r"\bMLLM\b", r"vision[- ]language",
                     r"\bOCR\b", r"文件(理解|解析)"],
    },
    "generative_media": {
        "label": "影音生成", "group": "模型與技術",
        "desc": "圖像、影片、語音（TTS）、音樂的生成與編輯",
        "keywords": [r"影片生成", r"生成影片", r"video generation", r"text-to-video", r"\bSora\b",
                     r"\bVeo ?\d", r"Kling", r"可靈", r"Runway", r"圖像生成", r"影像生成", r"圖片生成",
                     r"text-to-image", r"image generation", r"Midjourney", r"\bFLUX\b",
                     r"Stable Diffusion", r"Nano Banana", r"Imagen", r"\bTTS\b", r"text-to-speech",
                     r"語音(合成|生成|模型)", r"ElevenLabs", r"音樂生成", r"AI 音樂", r"Suno", r"聲音複製"],
    },
    "rag_retrieval": {
        "label": "RAG 與知識檢索", "group": "模型與技術",
        "desc": "RAG、向量檢索、嵌入模型、知識圖譜、代理記憶",
        "keywords": [r"\bRAG\b", r"檢索增強", r"retrieval[- ]augmented", r"向量(資料庫|檢索)",
                     r"vector (database|search)", r"嵌入模型", r"embedding", r"知識圖譜",
                     r"knowledge graph", r"GraphRAG", r"代理記憶", r"長期記憶", r"agent memory",
                     r"上下文工程", r"context engineering"],
    },
    "world_model": {
        "label": "世界模型", "group": "模型與技術",
        "desc": "世界模型、物理模擬、數位孿生",
        "keywords": [r"世界模型", r"world model", r"Genie ?\d", r"Cosmos", r"物理模擬", r"數位孿生",
                     r"digital twin"],
    },
    "benchmark_eval": {
        "label": "評測與排行榜", "group": "模型與技術",
        "desc": "模型評測基準、排行榜、能力評估方法",
        "keywords": [r"基準測試", r"評測基準", r"benchmark", r"-Bench\b", r"排行榜", r"leaderboard",
                     r"\bArena\b"],
    },
    "alignment_safety": {
        "label": "對齊與 AI 安全研究", "group": "模型與技術",
        "desc": "對齊、可解釋性、模型欺騙／諂媚、幻覺與可靠性、AI 安全研究機構（不含資安攻擊）",
        "keywords": [r"對齊", r"alignment", r"可解釋性", r"interpretab", r"稀疏自編碼", r"諂媚",
                     r"sycophan", r"欺騙(行為|性)", r"deceptiv", r"獎勵駭客", r"reward hack",
                     r"AI 安全研究所", r"\bAISI\b", r"\bMETR\b", r"紅隊", r"red[- ]team", r"scheming",
                     r"幻覺", r"hallucinat"],
        "exclude": [r"CVE-", r"勒索"],
    },
    "ai_science": {
        "label": "AI for Science", "group": "模型與技術",
        "desc": "AI 用於數學證明、蛋白質、材料、氣象等科學研究",
        "keywords": [r"蛋白質", r"protein", r"AlphaFold", r"AlphaProof", r"AlphaEvolve",
                     r"數學(證明|難題|問題|定理|競賽|奧林匹亞)", r"定理", r"科學發現", r"材料(發現|科學)",
                     r"基因", r"genom", r"分子", r"氣象|天氣預報|氣候模型", r"AI 科學家", r"AI scientist",
                     r"Erdős|Erdos"],
    },

    # ───────────────────────── Agent 與開發 ─────────────────────────
    "ai_agent": {
        "label": "AI Agent", "group": "Agent 與開發",
        "desc": "AI 代理與代理框架、MCP／A2A 協定、電腦與瀏覽器操作代理、代理商務",
        "keywords": [r"\bMCP\b", r"Model Context Protocol", r"\bA2A\b", r"AI ?代理", r"智慧代理",
                     r"代理(框架|協議|協定|平台|技能|工作流)", r"\bagent", r"多代理", r"multi-agent",
                     r"LangChain", r"LangGraph", r"CrewAI", r"AutoGen", r"computer use", r"電腦操作",
                     r"瀏覽器代理", r"AI 瀏覽器", r"Operator", r"代理(商務|支付|購物|結帳)",
                     r"agentic"],
    },
    "coding_ai": {
        "label": "AI 程式開發", "group": "Agent 與開發",
        "desc": "Coding Agent、AI 程式助手與開發工具（Claude Code、Codex、Cursor、Copilot）",
        "keywords": [r"Claude Code", r"\bCodex\b", r"Cursor", r"GitHub Copilot", r"Copilot (Chat|Workspace|Agent|coding)", r"Windsurf", r"Antigravity",
                     r"OpenCode", r"Devin", r"Replit", r"Lovable", r"vibe ?coding", r"氛圍編程",
                     r"coding agent", r"編碼代理", r"程式碼(代理|生成|助手|審查)", r"AI (編碼|程式)",
                     r"code review", r"SWE-?bench"],
    },

    # ───────────────────────── 應用場景 ─────────────────────────
    "enterprise_adoption": {
        "label": "企業導入", "group": "應用場景",
        "desc": "企業部署 AI 的案例與平台、數位員工、流程自動化",
        "keywords": [r"企業(導入|採用|部署|轉型|級 AI|AI 代理|AI 平台)", r"數位(同事|員工|勞動力)",
                     r"AI 員工", r"enterprise AI", r"Agentforce", r"Copilot Studio", r"工作流程自動化",
                     r"workflow automation", r"AI 轉型", r"導入 AI", r"採用 AI"],
    },
    "ai_search": {
        "label": "AI 搜尋", "group": "應用場景",
        "desc": "AI 搜尋、答案引擎、深度研究功能，以及對搜尋與流量生態的衝擊",
        "keywords": [r"AI 搜尋", r"AI search", r"AI Overviews?", r"AI Mode", r"搜尋引擎",
                     r"search engine", r"Perplexity", r"答案引擎", r"ChatGPT Search", r"深度研究",
                     r"Deep Research"],
    },
    "consumer_devices": {
        "label": "消費裝置與助理", "group": "應用場景",
        "desc": "手機、語音助理、AI 眼鏡與穿戴裝置上的 AI 功能",
        "keywords": [r"Siri", r"iPhone", r"Apple Intelligence", r"Galaxy", r"Pixel", r"Alexa",
                     r"語音助理", r"智慧型手機", r"眼鏡", r"glasses", r"Ray-Ban", r"穿戴", r"wearable",
                     r"AI 耳機", r"AR 眼鏡"],
    },
    "healthcare": {
        "label": "醫療健康", "group": "應用場景",
        "desc": "AI 用於醫療、臨床、製藥與健康照護",
        "keywords": [r"醫療", r"醫院", r"臨床", r"clinical", r"診斷", r"病患", r"患者", r"電子病歷",
                     r"癌症", r"藥物(開發|研發|發現)", r"製藥", r"pharma", r"醫師|醫生"],
        "exclude": [r"心理健康", r"mental health"],
    },
    "finance": {
        "label": "金融", "group": "應用場景",
        "desc": "AI 用於銀行、保險、證券、支付等金融業",
        "keywords": [r"銀行", r"\bbank", r"保險", r"金控", r"證券", r"財富管理", r"高盛", r"Goldman",
                     r"JPMorgan", r"摩根大通", r"Visa\b", r"Mastercard", r"金融業"],
        "exclude": [r"世界銀行", r"央行"],
    },
    "education": {
        "label": "教育", "group": "應用場景",
        "desc": "AI 用於教學與學習、校園政策、學生使用 AI",
        "keywords": [r"教育", r"學生", r"學校", r"課程", r"教師|老師", r"考試", r"家教|tutor"],
    },
    "defense_military": {
        "label": "國防軍事", "group": "應用場景",
        "desc": "AI 用於國防、軍事、無人機與武器系統，以及國防部採購",
        "keywords": [r"國防", r"軍事", r"軍方", r"五角大廈", r"Pentagon", r"國防部", r"戰爭部",
                     r"武器", r"無人機", r"drone", r"Anduril", r"Palantir", r"軍用"],
    },
    "robotics": {
        "label": "機器人", "group": "應用場景",
        "desc": "人形機器人、具身智能、工業與服務機器人",
        "keywords": [r"人形機器人", r"humanoid", r"具身", r"embodied", r"physical AI", r"實體 ?AI",
                     r"機器人", r"robot", r"Optimus", r"Figure AI", r"GR00T", r"Unitree|宇樹", r"機械手|機械臂"],
        "exclude": [r"機器人流程自動化", r"聊天機器人", r"chatbot"],
    },
    "autonomous_driving": {
        "label": "自駕車", "group": "應用場景",
        "desc": "自動駕駛、Robotaxi、輔助駕駛",
        "keywords": [r"自駕", r"自動駕駛", r"無人駕駛", r"autonomous (driving|vehicle)", r"self-driving",
                     r"Robotaxi", r"Waymo", r"\bFSD\b", r"Zoox", r"Wayve", r"ADAS"],
    },

    # ───────────────────────── 硬體與基礎建設 ─────────────────────────
    "ai_chips": {
        "label": "AI 晶片", "group": "硬體與基礎建設",
        "desc": "GPU 與 AI 加速器、自研 ASIC／TPU（NVIDIA、AMD、Google TPU、Trainium 等）",
        "keywords": [r"\bGPU", r"Blackwell", r"Rubin", r"\bB[23]00\b", r"GB[23]00", r"\bH[12]00\b",
                     r"\bH20\b", r"\bMI[3-5]\d\d", r"Instinct", r"\bDGX", r"\bCUDA\b", r"顯示卡|顯卡",
                     r"加速器", r"\bASIC", r"\bTPU", r"Trainium", r"Inferentia", r"\bMaia\b", r"\bMTIA\b",
                     r"自研(晶片|AI 晶片)", r"客製化?晶片", r"custom chip", r"Cerebras", r"Groq\b",
                     r"AI 晶片"],
    },
    "memory_hbm": {
        "label": "記憶體與 HBM", "group": "硬體與基礎建設",
        "desc": "HBM、DRAM、NAND 與儲存（SK 海力士、三星、美光）",
        "keywords": [r"\bHBM", r"DRAM", r"NAND", r"記憶體", r"SK ?海力士", r"SK hynix", r"美光",
                     r"Micron", r"長鑫", r"\bSSD\b", r"LPDDR", r"\bCXL\b"],
    },
    "semiconductor_mfg": {
        "label": "晶圓代工與先進封裝", "group": "硬體與基礎建設",
        "desc": "晶圓代工、先進製程、先進封裝（CoWoS、SoIC）、EUV 與半導體設備",
        "keywords": [r"CoWoS", r"先進封裝", r"advanced packaging", r"FOPLP", r"CoPoS", r"SoIC", r"封裝",
                     r"[1-3](\.\d)? ?奈米", r"製程", r"晶圓代工", r"foundry", r"\bEUV", r"ASML",
                     r"玻璃基板", r"18A|14A", r"台積電", r"TSMC"],
    },
    "networking_photonics": {
        "label": "網路與矽光子", "group": "硬體與基礎建設",
        "desc": "資料中心網路、交換器、矽光子與 CPO、光通訊",
        "keywords": [r"矽光子", r"silicon photonic", r"\bCPO\b", r"共同封裝光學", r"光模組", r"光通訊",
                     r"800G|1\.6T|3\.2T", r"交換器", r"InfiniBand", r"乙太網", r"NVLink", r"Spectrum-X",
                     r"光互連"],
    },
    "ai_servers": {
        "label": "AI 伺服器供應鏈", "group": "硬體與基礎建設",
        "desc": "AI 伺服器與機櫃、ODM 與零組件供應鏈（鴻海、廣達、緯創、緯穎、台達電等）",
        "keywords": [r"伺服器", r"機櫃", r"鴻海", r"Foxconn", r"廣達", r"緯創", r"緯穎", r"英業達",
                     r"和碩", r"台達電", r"光寶", r"Supermicro|超微電腦"],
    },
    "datacenter": {
        "label": "資料中心與算力", "group": "硬體與基礎建設",
        "desc": "資料中心興建、算力租賃與合約、雲端算力業者（含 Neocloud）、液冷散熱",
        "keywords": [r"資料中心", r"數據中心", r"data ?center", r"算力(合約|協議|租賃|中心|擴張|採購)",
                     r"運算(協議|合約|容量)", r"compute (deal|contract|capacity)", r"Stargate|星際之門",
                     r"CoreWeave", r"Nscale", r"Crusoe", r"Nebius", r"Neocloud", r"hyperscale",
                     r"液冷", r"散熱", r"cooling"],
    },
    "energy_power": {
        "label": "能源電力", "group": "硬體與基礎建設",
        "desc": "AI 與資料中心的電力、電網、核能與能源供應",
        "keywords": [r"電力", r"電網", r"核能", r"核電", r"nuclear", r"\bSMR\b", r"燃氣渦輪",
                     r"gas turbine", r"能源", r"\bGW\b", r"吉瓦", r"供電", r"電廠", r"儲能"],
    },

    # ───────────────────────── 產業與資本 ─────────────────────────
    "funding_valuation": {
        "label": "融資與估值", "group": "產業與資本",
        "desc": "新創與 AI 公司的融資輪、估值、策略投資",
        "keywords": [r"融資", r"募資", r"籌集", r"籌資", r"估值", r"valuation", r"funding",
                     r"[A-H] ?輪", r"種子輪", r"領投"],
        "exclude": [r"\bIPO\b", r"債券", r"貸款"],
    },
    "ipo": {
        "label": "IPO 與上市", "group": "產業與資本",
        "desc": "首次公開發行、申請上市、掛牌",
        "keywords": [r"\bIPO\b", r"首次公開發行", r"上市(申請|計畫|掛牌)|申請上市|掛牌", r"招股書",
                     r"科創板", r"港交所"],
    },
    "m_and_a": {
        "label": "併購", "group": "產業與資本",
        "desc": "收購、合併、入股取得控制權",
        "keywords": [r"收購", r"併購", r"購併", r"acqui", r"merger", r"買下", r"合併(談判|案|協議)"],
    },
    "earnings": {
        "label": "財報與營收", "group": "產業與資本",
        "desc": "財報、營收、獲利、財測與出貨量",
        "keywords": [r"財報", r"營收", r"revenue", r"第[一二三四]季", r"獲利", r"earnings", r"毛利",
                     r"財測", r"出貨量"],
    },
    "ai_capex_bubble": {
        "label": "資本支出與泡沫疑慮", "group": "產業與資本",
        "desc": "AI 資本支出、發債與融資結構、循環交易、泡沫與過熱疑慮",
        "keywords": [r"資本支出", r"capex", r"債券", r"發債", r"債務", r"\bdebt\b", r"泡沫", r"bubble",
                     r"過熱", r"循環(融資|交易)", r"circular", r"私募信貸", r"private credit"],
    },
    "talent_leadership": {
        "label": "人才與高層異動", "group": "產業與資本",
        "desc": "關鍵人才跳槽與挖角、高層任命與離職、組織重組",
        "keywords": [r"離職", r"跳槽", r"挖角", r"任命", r"出任", r"接任", r"辭職", r"接班",
                     r"人才(爭奪|流動|戰)", r"poach"],
    },

    # ───────────────────────── 政策與社會 ─────────────────────────
    "ai_regulation": {
        "label": "AI 法規監管", "group": "政策與社會",
        "desc": "AI 立法、行政命令、監管機關與合規要求（州、聯邦、歐盟、台灣）",
        "keywords": [r"法案", r"立法", r"AI ?法", r"AI Act", r"監管", r"regulat", r"州(政府|法|議會)",
                     r"參議", r"眾議", r"國會", r"Congress", r"歐盟", r"行政命令", r"executive order",
                     r"規範", r"指引"],
        "exclude": [r"出口管制"],
    },
    "export_control": {
        "label": "出口管制與科技戰", "group": "政策與社會",
        "desc": "晶片出口管制、實體清單、走私、關稅與中美科技對抗",
        "keywords": [r"出口管制", r"export control", r"出口(限制|禁令|許可)", r"走私", r"smuggl",
                     r"實體清單", r"entity list", r"禁售", r"流向中國", r"晶片禁令", r"關稅", r"tariff"],
    },
    "sovereign_ai": {
        "label": "主權 AI", "group": "政策與社會",
        "desc": "國家級 AI 戰略、主權算力與國家 AI 計畫",
        "keywords": [r"主權 ?AI", r"sovereign AI", r"國家(級)? ?AI", r"國家算力", r"AI (行動|國家)計畫",
                     r"AI 基本法", r"國家戰略"],
    },
    "copyright": {
        "label": "著作權", "group": "政策與社會",
        "desc": "訓練資料著作權爭議、侵權訴訟、內容授權協議",
        "keywords": [r"版權", r"著作權", r"copyright", r"侵權", r"授權(協議|內容|音樂)",
                     r"licens(e|ing) deal", r"出版商", r"紐約時報", r"New York Times", r"Getty"],
    },
    "litigation": {
        "label": "訴訟與判決", "group": "政策與社會",
        "desc": "AI 相關訴訟、法院判決、和解（著作權以外的也算）",
        "keywords": [r"起訴", r"訴訟", r"lawsuit", r"\bsue", r"法院", r"判決", r"court", r"和解",
                     r"settlement", r"集體訴訟", r"法官"],
    },
    "privacy": {
        "label": "隱私與資料保護", "group": "政策與社會",
        "desc": "個資與隱私、資料蒐集、監控與臉部辨識",
        "keywords": [r"隱私", r"privacy", r"個資", r"個人資料", r"GDPR", r"資料保護", r"surveillance",
                     r"臉部辨識", r"facial recognition"],
    },
    "jobs_labor": {
        "label": "就業衝擊", "group": "政策與社會",
        "desc": "AI 對就業與勞動市場的影響、裁員、職能轉型",
        "keywords": [r"裁員", r"layoff", r"就業", r"失業", r"勞工", r"勞動(市場|力)", r"工作(機會|崗位)",
                     r"取代.{0,6}(人力|員工|工作)", r"白領", r"再培訓"],
    },
    "child_mental_health": {
        "label": "兒少與心理健康", "group": "政策與社會",
        "desc": "兒少保護、年齡驗證、心理健康與 AI 伴侶依賴",
        "keywords": [r"兒童", r"兒少", r"未成年", r"青少年", r"teen", r"minor", r"心理健康",
                     r"mental health", r"自殺", r"suicide", r"年齡(驗證|分級|限制)", r"age verification",
                     r"AI 伴侶", r"companion", r"Character\.AI", r"成癮"],
    },
    "deepfake_misinfo": {
        "label": "深偽與假訊息", "group": "政策與社會",
        "desc": "Deepfake、假訊息、選舉操弄、浮水印與內容真實性",
        "keywords": [r"深偽", r"深度偽造", r"deepfake", r"假訊息", r"不實資訊", r"disinformation",
                     r"misinformation", r"選舉", r"election", r"水印", r"watermark", r"SynthID", r"C2PA"],
    },

    # ───────────────────────── 資訊安全 ─────────────────────────
    "ai_security": {
        "label": "AI 系統安全", "group": "資訊安全",
        "desc": "針對 AI 系統的攻擊與漏洞：提示注入、越獄、Agent 權限濫用、模型竊取、資料投毒",
        "keywords": [r"提示(詞)?注入", r"prompt injection", r"間接注入", r"越獄", r"jailbreak",
                     r"(AI ?代理|Agent|LLM|模型|MCP|Copilot|Claude Code|Codex|ChatGPT|Gemini).{0,12}(漏洞|遭劫持|被劫持)",
                     r"模型竊取", r"蒸餾攻擊", r"資料投毒", r"data poisoning"],
    },
    "ai_in_cyber": {
        "label": "AI 攻防應用", "group": "資訊安全",
        "desc": "AI 被用於網攻（AI 惡意程式、自動化攻擊），或 AI 用於找漏洞與防禦",
        "keywords": [r"駭客(利用|濫用|使用).{0,12}(AI|代理|模型|Claude|Gemini|ChatGPT|LLM)",
                     r"(AI|代理|LLM).{0,10}(發動|執行|自動化).{0,6}(攻擊|網攻|入侵)",
                     r"AI (駭客|網攻|網路攻擊)", r"AI 惡意", r"LLMJacking", r"vibe hacking",
                     r"AI.{0,10}(發現|挖掘|找出|偵測出).{0,10}漏洞", r"Big Sleep", r"Aardvark",
                     r"CodeMender", r"AI 資安(防禦|代理)"],
    },
    "vulnerability": {
        "label": "漏洞與修補", "group": "資訊安全",
        "desc": "軟硬體漏洞揭露、CVE、安全更新與修補（尚未確認遭大規模利用者）",
        "keywords": [r"CVE-", r"\bCVSS", r"漏洞", r"vulnerabilit", r"\bRCE\b", r"遠端程式碼執行",
                     r"修補", r"\bpatch"],
    },
    "zero_day": {
        "label": "零時差與已遭利用", "group": "資訊安全",
        "desc": "零時差漏洞、已遭實際利用（in the wild）的漏洞",
        "keywords": [r"零日", r"零時差", r"zero-day", r"0-day", r"已遭(實際)?利用", r"遭積極利用",
                     r"actively exploited", r"in the wild", r"\bKEV\b"],
    },
    "ransomware": {
        "label": "勒索軟體", "group": "資訊安全",
        "desc": "勒索軟體攻擊與勒索集團",
        "keywords": [r"勒索", r"ransomware", r"LockBit", r"Akira", r"Qilin"],
    },
    "data_breach": {
        "label": "資料外洩", "group": "資訊安全",
        "desc": "資料外洩與個資洩漏事件",
        "keywords": [r"(資料|個資|資訊|數據|客戶|用戶|使用者|會員|病歷|帳號|金鑰|憑證|密碼|紀錄|原始碼).{0,4}(外洩|洩漏|洩露|遭竊)",
                     r"data breach", r"\bbreach"],
    },
    "phishing_fraud": {
        "label": "釣魚與詐騙", "group": "資訊安全",
        "desc": "網路釣魚、社交工程、詐騙與帳號盜用",
        "keywords": [r"釣魚", r"phishing", r"詐騙", r"scam", r"fraud", r"社交工程", r"帳號(盜用|劫持)"],
    },
    "state_hacking": {
        "label": "國家級駭客", "group": "資訊安全",
        "desc": "國家支持的 APT 攻擊與網路間諜活動",
        "keywords": [r"\bAPT", r"國家級駭客", r"國家支持", r"state-sponsored", r"(北韓|俄羅斯|中國|伊朗)駭客",
                     r"Lazarus", r"Typhoon", r"網路間諜"],
    },
    "supply_chain_attack": {
        "label": "供應鏈攻擊", "group": "資訊安全",
        "desc": "軟體供應鏈攻擊：惡意套件（npm、PyPI）、建置流程與第三方元件遭植入",
        "keywords": [r"供應鏈攻擊", r"supply[- ]chain attack", r"\bnpm\b", r"PyPI", r"惡意套件",
                     r"malicious package", r"套件.{0,6}(遭|被)(植入|劫持|竄改)"],
    },
}

TAG_IDS: list[str] = list(TAGS.keys())
TAG_LABEL_BY_ID: dict[str, str] = {k: v["label"] for k, v in TAGS.items()}

# LLM 偶爾會吐出近義或舊寫法，先對應回正式 id；對不到的直接丟掉
TAG_ALIASES: dict[str, str] = {
    "agent": "ai_agent", "agents": "ai_agent", "agentic_ai": "ai_agent", "mcp": "ai_agent",
    "coding": "coding_ai", "coding_agent": "coding_ai", "ai_coding": "coding_ai",
    "opensource": "open_source", "open_weights": "open_source",
    "semiconductor": "ai_chips", "gpu": "ai_chips", "chips": "ai_chips",
    "hbm": "memory_hbm", "memory": "memory_hbm",
    "foundry": "semiconductor_mfg", "advanced_packaging": "semiconductor_mfg",
    "data_center": "datacenter", "energy": "energy_power", "power": "energy_power",
    "robot": "robotics", "humanoid": "robotics",
    "health": "healthcare", "medical": "healthcare", "fintech": "finance",
    "regulation": "ai_regulation", "policy": "ai_regulation",
    "safety": "alignment_safety", "ai_safety": "alignment_safety",
    "funding": "funding_valuation", "investment": "funding_valuation",
    "acquisition": "m_and_a", "merger": "m_and_a",
    "zeroday": "zero_day", "0day": "zero_day", "cve": "vulnerability",
    "breach": "data_breach", "phishing": "phishing_fraud", "apt": "state_hacking",
    "prompt_injection": "ai_security",
}


def _clean_token(raw) -> str:
    s = str(raw or "").strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    return re.sub(r"[^a-z0-9_]", "", s)


def normalize_tags(raw, max_tags: int = MAX_TAGS) -> list[str]:
    """把 LLM 輸出的 tags 收斂成字典內的 id：去重、保留順序、最多 max_tags 個。
    接受 list 或「逗號／頓號分隔字串」；不在字典裡也對不到別名的直接丟掉。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = re.split(r"[,，、;；|]", raw)
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    out: list[str] = []
    for it in items:
        tid = _clean_token(it)
        if not tid:
            continue
        tid = tid if tid in TAGS else TAG_ALIASES.get(tid, "")
        if tid and tid not in out:
            out.append(tid)
        if len(out) >= max_tags:
            break
    return out


def merge_tags(*tag_lists: Iterable[str], max_tags: int = MAX_TAGS) -> list[str]:
    """合併多個事件的 tags（事件去重合併時用）。

    依「出現次數」排序（多數事件都標的主題排前面），同次數保留先出現的順序，最多 max_tags 個。"""
    first_seen: dict[str, int] = {}
    count: dict[str, int] = {}
    for tl in tag_lists:
        for t in normalize_tags(tl, max_tags=len(TAGS)):
            if t not in count:
                first_seen[t] = len(first_seen)
                count[t] = 0
            count[t] += 1
    ranked = sorted(count, key=lambda t: (-count[t], first_seen[t]))
    return ranked[:max_tags]


def tag_spec_for_prompt() -> str:
    """抽事件 prompt 用的標籤字典（依群組排版，一行一個）。"""
    lines: list[str] = []
    for g in TAG_GROUPS:
        lines.append(f"  [{g}]")
        for tid, t in TAGS.items():
            if t["group"] == g and not t.get("deprecated"):
                lines.append(f"    - {tid}（{t['label']}）：{t['desc']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 歷史回溯：關鍵詞規則標註（不呼叫 LLM）
# ─────────────────────────────────────────────────────────────
_COMPILED: dict[str, tuple[list[re.Pattern], list[re.Pattern]]] = {
    tid: ([re.compile(p, re.I) for p in t.get("keywords", [])],
          [re.compile(p, re.I) for p in t.get("exclude", [])])
    for tid, t in TAGS.items()
}


RULE_MIN_SCORE = 2


def rule_tags(title: str, summary: str = "", what: str = "",
              max_tags: int = MAX_TAGS, min_score: int = RULE_MIN_SCORE) -> list[str]:
    """用關鍵詞規則替一則事件標 tags（歷史回溯用）。

    計分：標題命中的關鍵詞算 2 分、摘要／動作命中算 1 分；同一個關鍵詞只算一次。
    至少 min_score 分才標（預設 2：標題命中，或摘要命中兩個不同關鍵詞），
    避免摘要順帶一提就被標上。取分數最高的 max_tags 個，同分依字典順序。"""
    title = title or ""
    body = f"{summary or ''} {what or ''}"
    full = f"{title} {body}"
    scored: list[tuple[int, int, str]] = []
    for pos, (tid, (pats, excl)) in enumerate(_COMPILED.items()):
        if excl and any(p.search(full) for p in excl):
            continue
        score = 0
        for p in pats:
            if p.search(title):
                score += 2
            elif p.search(body):
                score += 1
        if score >= min_score:
            scored.append((-score, pos, tid))
    scored.sort()
    return [tid for _, _, tid in scored[:max_tags]]
