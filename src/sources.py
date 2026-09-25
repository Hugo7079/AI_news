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
    {"name": "Bloomberg Tech",    "url": "https://feeds.bloomberg.com/technology/news.rss",         "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "BBC Tech",          "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",        "region": "GLOBAL", "kind": "media", "lang": "en"},
    {"name": "The Decoder",       "url": "https://the-decoder.com/feed/",                           "region": "GLOBAL", "kind": "media", "lang": "en"},
    # Import AI：原 importai.substack.com 在 GitHub runner 上 8/8 次 403（Substack 擋機房 IP），
    # 改抓作者 WordPress.com 鏡像（2026-09-25 驗證 10 則、最新 09-21）
    {"name": "Import AI",         "url": "https://jack-clark.net/feed/",                            "region": "GLOBAL", "kind": "media", "lang": "en"},
    # VentureBeat 整站掛 Vercel bot challenge，CI 與本機皆 429（2026-09-25 驗證），已移除；靠 Google News query 補
    # The Information / Reuters 需付費或已關閉公開 RSS，靠 Google News query 補

    # ─────────────────────────── AI 廠商 / 研究機構部落格 ───────────────────────────
    {"name": "OpenAI Blog",       "url": "https://openai.com/blog/rss.xml",                         "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Google DeepMind",   "url": "https://deepmind.google/blog/feed/basic",                 "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Google Research",   "url": "https://research.google/blog/rss/",                       "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    # blogs.microsoft.com/ai/feed/ 已 410 Gone，AI 內容併入 Microsoft Source 的 AI 主題（2026-09-25 驗證 10 則、最新 09-10，月更 2~4 篇）
    {"name": "Microsoft Source AI", "url": "https://news.microsoft.com/source/topics/ai/feed/",    "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Nvidia Blog",       "url": "https://blogs.nvidia.com/feed/",                          "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml",                    "region": "GLOBAL", "kind": "vendor", "lang": "en"},
    # Anthropic / Mistral / Meta AI 官方部落格已關閉公開 RSS，依賴 Google News query「OpenAI OR Anthropic OR Mistral」補

    # ─────────────────────────── 社群 / 聚合 ───────────────────────────
    {"name": "Hacker News (front)",      "url": "https://hnrss.org/frontpage",                       "region": "GLOBAL", "kind": "community", "lang": "en"},
    # Reddit 未登入 RSS 每 IP 約 60 秒只給 1 次（x-ratelimit-remaining 立刻歸 0，換 UA 無效；
    # old.reddit.com 的 .rss 會導去登入頁），三個 sub 分開抓每次只活一個。
    # 改用 multireddit 一次抓完（2026-09-25 驗證 limit=100 → 100 則，涵蓋約 40 小時）
    {"name": "Reddit (ML+LocalLLaMA+singularity)", "url": "https://www.reddit.com/r/MachineLearning+LocalLLaMA+singularity/.rss?limit=100", "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "arXiv cs.AI (新論文)",      "url": "https://export.arxiv.org/rss/cs.AI",               "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "arXiv cs.LG (新論文)",      "url": "https://export.arxiv.org/rss/cs.LG",               "region": "GLOBAL", "kind": "community", "lang": "en"},
    {"name": "arXiv cs.CL (新論文)",      "url": "https://export.arxiv.org/rss/cs.CL",               "region": "GLOBAL", "kind": "community", "lang": "en"},
    # X/Twitter 無公開 RSS；nitter.net 已 connection refused（2026-09 CI 8/8 失敗），已移除。如需 X 資料建議另接付費 API。

    # ─────────────────────────── 科技 / AI Podcast (RSS) ───────────────────────────
    # Latent Space：api.substack.com podcast feed 在 GitHub runner 上 8/8 次 403；Apple Podcasts 登記的也只有這條，
    # 無 Substack 以外的託管。改抓出版物本身 feed（2026-09-25 本機驗證 20 則、最新 09-25，含文章＋podcast），
    # 但同屬 Substack Cloudflare，CI 仍 403 的話就整個移除
    {"name": "Latent Space",         "url": "https://www.latent.space/feed",                        "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    {"name": "Lex Fridman",          "url": "https://lexfridman.com/feed/podcast/",                 "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    # Acquired 約月更（最新 2026-09-14，前一集 08-10），DEFAULT_DAYS_BACK=1 下多數日子 0 則屬正常（2026-09-25 驗證 feed 仍活）
    {"name": "Acquired",             "url": "https://feeds.transistor.fm/acquired",                 "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    {"name": "a16z Podcast",         "url": "https://feeds.simplecast.com/JGE3yC0V",                "region": "GLOBAL", "kind": "podcast", "lang": "en"},
    # No Priors / TWIML / Practical AI / Cognitive Revolution 主機端 URL 不穩，需要時請至 podcast 主頁取最新 RSS

    # ─────────────────────────── 台灣 / 華語 Podcast ───────────────────────────
    # 科技島讀 podcast 已於 2021-06-06 停更（Apple Podcasts 登記的 SoundCloud feed 最後一集即此），
    # daodu.tech/rss 現在回 HTML 而非 RSS，已移除（2026-09-25 驗證）
    # 矽谷輕鬆談週更（週日，最新 2026-09-13），DEFAULT_DAYS_BACK=1 下只有上架當天抓得到，0 則屬正常（2026-09-25 驗證 feed 仍活）
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
