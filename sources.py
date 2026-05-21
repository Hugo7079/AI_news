"""
新聞來源清單（以 RSS / Atom 為主）
==================================

來源分四大組：
  1. 台灣科技/財經媒體
  2. 國外科技媒體
  3. AI 廠商 / 研究機構官方部落格
  4. 社群與聚合（HN / Reddit / arXiv）
  5. AI 主題 Podcast (RSS feed)
另保留 Google News 搜尋作為「即時 Web Search」備援（見 fetcher.py）。

每個 source 是 dict：
  {
    "name": 顯示名稱,
    "url":  RSS / Atom feed 連結,
    "region": "TW" | "GLOBAL",
    "kind": "media" | "vendor" | "community" | "podcast",
    "lang": "zh" | "en",
  }

註：feed 連結會隨時間變動，若失效請更新或於 Streamlit UI 暫時關閉。
"""

# 註：標 SKIP_RSS 表示無公開 RSS（已驗證 2026-05），改靠 Google News query 補
SOURCES: list[dict] = [
    # ─────────────────────────── 台灣科技 / 財經媒體 ───────────────────────────
    {"name": "iThome 新聞",       "url": "https://www.ithome.com.tw/rss",                         "region": "TW", "kind": "media", "lang": "zh"},
    {"name": "iThome AI 專區",    "url": "https://www.ithome.com.tw/rss/ai",                       "region": "TW", "kind": "media", "lang": "zh"},
    {"name": "TechNews 科技新報", "url": "https://technews.tw/feed/",                              "region": "TW", "kind": "media", "lang": "zh"},
    {"name": "DIGITIMES 中文",    "url": "https://www.digitimes.com.tw/rss/news.xml",              "region": "TW", "kind": "media", "lang": "zh"},
    {"name": "聯合新聞網科技",    "url": "https://udn.com/rssfeed/news/2/6638?ch=news",            "region": "TW", "kind": "media", "lang": "zh"},
    # INSIDE 硬塞 / 數位時代 BNext / 中央社 / 經濟日報科技 已無公開 RSS（2026-05 驗證），透過 Google News 中文 query 補

    # ─────────────────────────── 國外科技媒體 ───────────────────────────
    {"name": "TechCrunch",        "url": "https://techcrunch.com/feed/",                            "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "The Verge",         "url": "https://www.theverge.com/rss/index.xml",                  "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "Ars Technica",      "url": "https://feeds.arstechnica.com/arstechnica/index",         "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "Wired",             "url": "https://www.wired.com/feed/rss",                          "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "MIT Tech Review",   "url": "https://www.technologyreview.com/feed/",                  "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "VentureBeat AI",    "url": "https://venturebeat.com/category/ai/feed",                "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "Bloomberg Tech",    "url": "https://feeds.bloomberg.com/technology/news.rss",         "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "BBC Tech",          "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",        "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "The Decoder",       "url": "https://the-decoder.com/feed/",                           "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "Import AI",         "url": "https://importai.substack.com/feed",                      "region": "GLOBAL", "kind": "media", "lang": "en"},
    # The Information / Reuters 需付費或已關閉公開 RSS，靠 Google News query 補

    # ─────────────────────────── AI 廠商 / 研究機構部落格 ───────────────────────────
    {"name": "OpenAI Blog",       "url": "https://openai.com/blog/rss.xml",                         "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Google DeepMind",   "url": "https://deepmind.google/blog/feed/basic",                 "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Google Research",   "url": "https://research.google/blog/rss/",                       "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Microsoft AI Blog", "url": "https://blogs.microsoft.com/ai/feed/",                    "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Nvidia Blog",       "url": "https://blogs.nvidia.com/feed/",                          "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml",                    "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    # Anthropic / Mistral / Meta AI 官方部落格已關閉公開 RSS，依賴 Google News query「OpenAI OR Anthropic OR Mistral」補

    # ─────────────────────────── 社群 / 聚合 ───────────────────────────
    {"name": "Hacker News (front)",      "url": "https://hnrss.org/frontpage",                       "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "Reddit r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/.rss",     "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "Reddit r/LocalLLaMA",      "url": "https://www.reddit.com/r/LocalLLaMA/.rss",          "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "Reddit r/singularity",     "url": "https://www.reddit.com/r/singularity/.rss",         "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "arXiv cs.AI (新論文)",      "url": "https://export.arxiv.org/rss/cs.AI",               "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "arXiv cs.LG (新論文)",      "url": "https://export.arxiv.org/rss/cs.LG",               "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "arXiv cs.CL (新論文)",      "url": "https://export.arxiv.org/rss/cs.CL",               "region": "GLOBAL", "kind": "community", "lang": "en"},
    # X/Twitter 無公開 RSS；nitter 公開鏡像常被擋。如需 X 資料建議另接付費 API。
    {"name": "Nitter @AnthropicAI",      "url": "https://nitter.net/anthropicai/rss",                "region": "GLOBAL", "kind": "community", "lang": "en"},

    # ─────────────────────────── 科技 / AI Podcast (RSS) ───────────────────────────
    {"name": "Latent Space",         "url": "https://api.substack.com/feed/podcast/1084089.rss",    "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    {"name": "Lex Fridman",          "url": "https://lexfridman.com/feed/podcast/",                 "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    {"name": "Acquired",             "url": "https://feeds.transistor.fm/acquired",                 "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    {"name": "a16z Podcast",         "url": "https://feeds.simplecast.com/JGE3yC0V",                "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    # No Priors / TWIML / Practical AI / Cognitive Revolution 主機端 URL 不穩，需要時請至 podcast 主頁取最新 RSS

    # ─────────────────────────── 台灣 / 華語 Podcast ───────────────────────────
    {"name": "科技島讀",             "url": "https://daodu.tech/rss",                                "region": "TW", "kind": "podcast", "lang": "zh"},
    {"name": "矽谷輕鬆談 Just Kidding Tech", "url": "https://anchor.fm/s/120c33e0/podcast/rss",      "region": "TW", "kind": "podcast", "lang": "zh"},
    {"name": "M觀點",                "url": "https://feeds.soundon.fm/podcasts/b8f5a471-f4f7-4763-9678-65887beda63a.xml", "region": "TW", "kind": "podcast", "lang": "zh"},
    {"name": "科技浪 Tech.wav",      "url": "https://feed.firstory.me/rss/user/cm3o5681s06e801v3fxpjehwb", "region": "TW", "kind": "podcast", "lang": "zh"},
]


# Google News RSS 搜尋（即時 Web Search 用，作為補強，不在 SOURCES 表）
GOOGLE_NEWS_QUERIES_ZH = [
    "AI OR 人工智慧 OR 大模型",
    "AI 晶片 OR AI 伺服器 OR HBM",
    "人形機器人 OR Tesla Optimus OR Figure",
    "AI 新創 融資 OR 估值",
    "OpenAI OR Anthropic OR Google DeepMind",
]

GOOGLE_NEWS_QUERIES_EN = [
    "OpenAI OR Anthropic OR \"Google DeepMind\"",
    "\"large language model\" OR LLM new release",
    "AI chip OR \"AI server\" OR HBM",
    "humanoid robot OR robotics startup",
    "AI funding OR \"AI startup\" raises",
    "AI regulation OR \"AI act\" OR \"AI lawsuit\"",
]
