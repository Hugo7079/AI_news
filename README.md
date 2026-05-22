# AI 新聞爬搜整理

每天自動抓取**台灣 + 國際 + AI 廠商 + 社群 + Podcast**的 AI 相關新聞，
透過 LLM 自動歸入 **5 大類別**，並去重後輸出成 Excel / JSON，可在 Streamlit 上閱讀。

設計概念參考姊妹專案 `臺灣通用電子地圖`（同樣使用 Google News RSS + 自建 LLM 服務做去噪與去重）。

---

## 一、目標讀者與五大分類

設計時想像 AI 新聞讀者的 5 種輪廓，對應 5 個類別：

| 讀者輪廓 | 對應類別（category_id） | 包含內容 |
| --- | --- | --- |
| 技術開發者 / AI 研究者 | **技術突破與研究** (`tech_research`) | 新模型發表、模型架構、量化/壓縮/蒸餾、訓練方法、優化演算法、論文、開源框架 |
| 創業者 / 投資人 / 分析師 | **產業動態與商業** (`industry_business`) | 新創融資、併購、IPO、估值、合作、財報、企業 AI 策略 |
| 硬體 / 半導體 / 供應鏈 | **硬體與基礎建設** (`hardware_infra`) | GPU / NPU / ASIC、HBM、伺服器、資料中心、人形機器人、機器人零組件、供應鏈 |
| 企業 IT / PM / 一般職場 | **產品與應用** (`products_apps`) | 新產品/服務、企業導入案例、整合公告、AI 工具評測 |
| 政策 / 法務 / 社會關注者 | **政策法規與社會影響** (`policy_society`) | AI 立法、訴訟、智財權、安全/對齊、勞動衝擊、隱私、社會輿論 |

> 修改類別：在 [`config.py`](config.py) 的 `CATEGORIES` 字典中編輯即可（label / desc / examples）。

---

## 二、新聞來源（50+ 個 feed）

全部在 [`sources.py`](sources.py) 設定，分四大類：

1. **台灣科技/財經媒體**：iThome、TechNews 科技新報、INSIDE、數位時代、中央社科技、聯合 / 經濟日報科技、Digitimes 中文。
2. **國外科技媒體**：TechCrunch、The Verge、Ars Technica、Wired、MIT Tech Review、VentureBeat AI、The Information、Bloomberg Tech、Reuters Tech、The Decoder、Import AI。
3. **AI 廠商 / 研究機構部落格**：OpenAI、Anthropic、Google DeepMind / Google AI、Meta AI、Microsoft AI、Nvidia、Hugging Face、Mistral。
4. **社群 / 聚合**：Hacker News、Reddit (r/MachineLearning、r/LocalLLaMA、r/singularity)、arXiv (cs.AI/cs.LG/cs.CL)、Nitter (OpenAI / Anthropic 等 X 帳號鏡像)。
5. **Podcast (RSS)**：Latent Space、No Priors、The Cognitive Revolution、Lex Fridman、Acquired、a16z、TWIML、Practical AI、科技島讀、M觀點。
6. **開源 AI 生態（非 RSS）** — 給 AI 小公司關注的「武器庫」，見 [`sources_extra.py`](sources_extra.py)：
   - **HuggingFace Trending Models** — Hub API，近兩週熱度暴衝的模型
   - **HuggingFace Daily Papers** — 編輯精選論文 + upvote 數
   - **GitHub Trending (weekly)** — 本週熱門 repo（自動過濾 AI 相關）
   - **Ollama Library** — 平台上可下載的開源模型
   - **OpenRouter Models** — 平台上新加入的模型（含定價、context）
   - 這幾類來源不經 LLM 分類，**統一歸到「產品與應用」**。

另外用 **Google News RSS 即時搜尋**（中英文 query，見 `sources.GOOGLE_NEWS_QUERIES_*`）做補強，
不需 API key、不需登入。

---

## 三、安裝

```bash
cd "~/AI新聞爬搜整理"
python3 -m venv .venv          # 可選
source .venv/bin/activate
pip install -r requirements.txt
```

### LLM 設定

預設讀取 [`.ainews_llm_config.json`](.ainews_llm_config.json)（已沿用 emap 的設定範本）；
也可改用環境變數：

```bash
export AINEWS_LLM_API_KEY=...
export AINEWS_LLM_BASE_URL=http://125.227.53.125:50062/
export AINEWS_LLM_MODEL=gemma-4-31B-it
```

> 若 LLM 不可用，pipeline 仍會跑完，但所有條目會落入「未分類」，需手動分類。

### 封面圖（HF Inference API）

每則「今日精選」會嘗試抓原文 `og:image`；抓不到時用 **FLUX.1-schnell**
（Hugging Face Inference API，開源模型）生成。需要一個 HF token：

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

取得方式：<https://huggingface.co/settings/tokens>（Read 權限即可）。
未設定時跳過 AI 生圖、用分類色塊 + icon 作 fallback，pipeline 仍能跑完。

---

## 四、執行

### 1. 一次性 / 手動執行

```bash
python3 pipeline.py --days 1                  # 抓近 1 天
python3 pipeline.py --days 3 --no-google      # 只用 RSS，不用 Google News
python3 pipeline.py --kinds vendor podcast    # 只抓廠商部落格 + Podcast
```

結果輸出在 `output/YYYY-MM-DD_AI新聞整理.xlsx`（全部 + 5 個分類分頁）
與 `output/YYYY-MM-DD_AI新聞整理.json`。

### 2. Streamlit UI

```bash
streamlit run app_ainews.py
```

側欄可調天數、來源類型、Google News 開關；可載入歷史輸出。

### 3. 每日自動排程

**方式 A：launchd（macOS 推薦）**

```bash
cp com.leolee.ainews.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.leolee.ainews.plist
```

預設每天早上 08:00 跑。改時間就編輯 plist 內 `<key>Hour</key>`。

**方式 B：cron**

```bash
crontab -e
# 加入：
0 8 * * * /Users/leolee/AI新聞爬搜整理/run_daily.sh >> /Users/leolee/AI新聞爬搜整理/output/cron.log 2>&1
```

### 4. 部署到 Streamlit Community Cloud

工作流程：本機 Mac 跑 pipeline 產生 `output/` 檔案 → push 到 GitHub → Streamlit Cloud 拉取顯示。

1. **設 Repo**：把整個資料夾 push 到 GitHub（`output/*.xlsx` 已 gitignore，
   `output/*.json` 與 `output/images/*` 會跟著進 repo）。
2. **連結 Streamlit Cloud**：到 <https://streamlit.io/cloud> → New App → 指向你的 repo，
   主檔 `app_ainews.py`。
3. **設 Secrets**：App settings → Secrets，貼上 [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example)
   的內容並填入真正的 `HF_TOKEN` 與 LLM 設定。
4. **每日更新**：本機 launchd 跑完後執行
   `git add output/ && git commit -m "daily $(date +%F)" && git push`，Streamlit Cloud 會自動重建。
   想要全自動可寫個 wrapper script 接在 `run_daily.sh` 之後。

> ⚠️ Streamlit Cloud 是 ephemeral filesystem，從 UI 上按「開始爬搜」生成的檔案重啟後會消失；
> 正式資料請從本機 push。

---

## 五、Pipeline 流程

```
        ┌──────────────────────────┐
        │  sources.py: 50+ feeds   │
        └──────────┬───────────────┘
                   │
          fetch_all_sources()        ← 平行抓 RSS，過濾近 N 天
                   │
          google_news_supplement()   ← 中英文 query 搜尋補強
                   │
              prefilter()            ← AI 關鍵字 + 噪音字過濾
                   │
            URL 級去重
                   │
          classify_batch()           ← LLM 批次分類 → 5 類 / 非 AI
                   │
              dedup()                ← Title shingle Jaccard + LLM 比對
                   │
        ┌──────────┴───────────────┐
        │  output/*.xlsx + *.json  │
        └──────────────────────────┘
```

對應檔案：

| 檔 | 角色 |
| --- | --- |
| [`config.py`](config.py) | 分類定義、關鍵字、預設參數、LLM 設定 |
| [`sources.py`](sources.py) | 所有 RSS feed + Google News query |
| [`sources_extra.py`](sources_extra.py) | 非 RSS：HF / GitHub / Ollama / OpenRouter |
| [`fetcher.py`](fetcher.py) | RSS / Google News 抓取 + 粗篩 |
| [`llm.py`](llm.py) | OpenAI 相容 chat / chat_json 包裝 |
| [`classifier.py`](classifier.py) | LLM 分類 + 去重 |
| [`quality_rank.py`](quality_rank.py) | 品質過濾 + 重要度評分 |
| [`cover_image.py`](cover_image.py) | og:image 抓取 + HF FLUX 生圖 |
| [`pipeline.py`](pipeline.py) | 主流程 + CLI 進入點 |
| [`app_ainews.py`](app_ainews.py) | Streamlit UI（卡片版面） |
| [`ui_assets.py`](ui_assets.py) | UI 用 CSS / SVG icon / 配色 |
| [`run_daily.sh`](run_daily.sh) | 排程 shell |
| [`com.leolee.ainews.plist`](com.leolee.ainews.plist) | launchd 範本 |

---

## 六、調整建議

- **加新來源**：在 `sources.py` 的 `SOURCES` 加一筆 dict 即可。
- **改 query**：在 `sources.py` 改 `GOOGLE_NEWS_QUERIES_ZH / EN`。
- **改分類**：在 `config.py` 改 `CATEGORIES`，`label` / `desc` 會被注入 prompt，影響 LLM 判斷。
- **關掉 LLM**：`config.py` 設 `LLM_CLASSIFY_ENABLED = False`、`LLM_DEDUP_ENABLED = False`。
- **X / Twitter**：因官方無公開 RSS，預設使用 Nitter 鏡像；若鏡像被擋，可改用付費 API（X API、socialdata.tools 等）後在 `fetcher.py` 新增 fetcher。
- **Podcast 內容**：目前只抓 episode 標題與描述；若要逐字稿，可串 Whisper / Deepgram，但成本較高，未納入預設。
