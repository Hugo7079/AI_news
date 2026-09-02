# 晨誌 Morning Ledger

每天自動抓取 **台灣 + 國際 + AI 廠商 + 社群 + Podcast** 的 AI 相關新聞，
LLM 抽事件 / 去重 / 分類 → 寫入 **Firestore** → 靜態網站直接顯示。

外部服務全部走免費額度：

| 用途 | 服務 | 免費額度 | 本專案每天用量 |
|---|---|---|---|
| 抽事件 / 去重 / 全文 | Mistral `mistral-small-latest` | 1 RPS、500K TPM、10 億 token/月 | 約 220 次呼叫、60 萬 token |
| 封面生圖 | Cloudflare Workers AI `flux-1-schnell` | 10,000 neurons/天（約 173 張） | 約 68 張 |
| 封面存放 | Firebase Storage | 5 GB 存放、5,000 上傳操作/月 | 68KB × 68 張/天 ≈ 4.6MB/天、約 2,040 次/月 |

> 封面存放需要 Firebase **Blaze** 方案 —— Spark 方案寫入會回
> `403 The billing account for the owning project is disabled`。Blaze 要綁付款方式，
> 但以上表的用量算，實際費用是 $0（都在免費額度內）。建議在 GCP billing 設個
> 預算警示，量爆掉時會通知而不是直接開帳單。
>
> 不想用 Blaze 的話，`src/r2_storage.py` 提供 Cloudflare R2 作為替代：設好
> `AINEWS_R2_*` 環境變數後 `_upload_cover()` 會自動改走 R2，程式不用改。
> 但 R2 開通同樣需要填付款方式，所以除非你已經在用 Cloudflare 生態，
> 沒必要為此多接一個服務。

兩套部署可以並存，同一份程式碼，差別只在 `AINEWS_STORE`：

```
A. 雲端版（GitHub Actions + Firebase）        B. 自架版（Docker，完全本地）

   Actions cron (06:00 TPE)                     ainews 容器（每天 06:00）
        │                                              │
        ▼  AINEWS_STORE=firestore                      ▼  AINEWS_STORE=local
   src/pipeline.py                                src/pipeline.py
        │                                              │
        ▼                                              ▼
   Firestore + Storage                           output/store/*.json
        │                                        output/images/*
        ▼                                              │
   web/  ← Firebase Hosting                            ▼
   （前端用 Firebase SDK 讀）                     ainews-web 容器
                                                 src/server.py :8080
                                                 （前端打 /api/*，不碰 Firebase）
```

前端靠 `web/config.json` 的 `mode` 自動切換：Firebase Hosting 拿到的是靜態檔
`{"mode":"firestore"}`；本地伺服器會覆寫成 `{"mode":"local"}`。
**本地模式完全不會載入 Firebase SDK**，內網 / 離線環境也能跑。

舊版本用 Streamlit Cloud 顯示，但 Cloud 是 ephemeral filesystem，重啟就丟資料；
這版本資料全進 Firestore，網站只負責顯示，徹底解決「昨天的紀錄又不見了」。

---

## 一、檔案結構

```
.
├── src/                     Python 主程式
│   ├── pipeline.py          主流程（CLI 進入點）
│   ├── config.py            分類、關鍵字、LLM / 生圖設定、路徑
│   ├── sources.py           50+ RSS feed + Google News query
│   ├── sources_extra.py     HF / GitHub / Ollama / OpenRouter
│   ├── fetcher.py           RSS / Google News 抓取
│   ├── llm.py               OpenAI 相容 LLM 包裝
│   ├── events.py            LLM 抽事件 + 合併
│   ├── classifier.py        LLM 分類 + 去重
│   ├── quality_rank.py      重要度評分 + 過濾
│   ├── cover_image.py       og:image 抓取 + 文生圖
│   ├── enrich.py            事件全文彙整
│   ├── summarize.py         摘要工具
│   ├── doc_model.py         事件文件 schema（兩種儲存共用）
│   ├── local_store.py       本地資料庫（output/store/*.json）
│   ├── server.py            自架網站：靜態前端 + /api + /media
│   └── firestore_writer.py  寫入 Firestore + Storage
│
├── docker/                  容器化
│   ├── Dockerfile
│   └── entrypoint.sh        schedule / once / 任意指令
├── compose.yaml             docker compose 設定（放根目錄，會自動讀 .env）
├── .env.example             環境變數範本（複製成 .env）
│
├── web/                     前端（雲端版部署到 Firebase Hosting）
│   ├── index.html
│   ├── style.css
│   ├── app.js               前端主程式（自動切換本地 / Firestore 資料來源）
│   ├── config.json          資料來源標記（部署到 Firebase 時 = firestore）
│   ├── report.js            產生「雙週電子報」版面的 PDF（瀏覽器列印）
│   ├── assets/              電子報版型素材（頁首 logo、主視覺橫幅）
│   └── _report_test.html    本機預覽電子報版面用（不會部署）
│
├── scripts/                 維運腳本
│   ├── export_firestore_local.py  把 Firestore 歷史資料倒回本地 store
│   ├── migrate_legacy.py    一次性：把舊 output/*.json 灌進 Firestore
│   ├── repair_day.py        修某一天的資料
│   ├── regen_top.py         重跑某天的精選 / 封面
│   ├── backfill_*.py        補封面圖 / 補全文
│   └── devserver.js         本機靜態預覽 server
│
├── firebase.json            Hosting + Firestore + Storage 設定
├── .firebaserc              project ID
├── firestore.rules          安全規則：public read, admin-only write
├── storage.rules            同上
│
├── .github/workflows/
│   └── daily.yml            每天 22:00 UTC cron（跑 src/pipeline.py）
│
└── output/                  資料與產出（已 gitignore）
    ├── store/               本地資料庫，一天一個 JSON
    ├── images/              封面圖
    └── *.json / *.xlsx      每日備份與報表
```

> 所有 Python 模組都是**扁平 import**（`from config import ...`）。
> 直接 `python3 src/pipeline.py` 就會把 `src/` 加進 sys.path，不需要設 PYTHONPATH。

---

## 二、五大分類

| 對應讀者 | category_id | 內容 |
| --- | --- | --- |
| 技術開發者 | `tech_research` | 新模型、架構、量化、論文 |
| 創業者 / 投資人 | `industry_business` | 融資、併購、財報、合作 |
| 硬體 / 半導體 | `hardware_infra` | GPU/NPU、HBM、資料中心、人形機器人 |
| 企業 IT / PM | `products_apps` | 產品上市、企業導入、AI 工具評測 |
| 政策 / 法務 | `policy_society` | 立法、訴訟、安全、勞動衝擊 |

修改在 [`src/config.py`](src/config.py) 的 `CATEGORIES`。

---

## 三、初次設定

### 1. Firebase 專案

Project ID：**d8ainews**（已建好；如要換別的 project，改 [`src/firestore_writer.py`](src/firestore_writer.py) 的常數 + [`.firebaserc`](.firebaserc) + [`web/app.js`](web/app.js) 的 `firebaseConfig`）

到 Firebase Console 確保以下服務都已啟用：
- **Firestore Database**（地點建議 `asia-east1`）
- **Storage**（同地點）
- **Hosting**

### 2. 取得 Service Account 金鑰（本機用）

Console → Project settings → Service accounts → **Generate new private key**
→ 下載 JSON，存成 `firebase-credentials.json` 放在專案根目錄。**這個檔已在 `.gitignore`，絕對不要 commit。**

### 3. 部署安全規則 + Hosting

```bash
npm install -g firebase-tools          # 第一次
firebase login                          # 用 Google 帳號登入

# 第一次：在 d8ainews 專案下開一個新的 hosting site，並綁到 "ledger" target
firebase hosting:sites:create morning-ledger
firebase target:apply hosting ledger morning-ledger

# 之後每次部署（都在 repo 根目錄執行）
firebase deploy --only firestore:rules
firebase deploy --only storage
firebase deploy --only hosting:ledger
```

部署完會得到 `https://morning-ledger.web.app`。site id 若已被占用，
換一個名字，`target:apply` 跟著改即可（`firebase.json` 裡的 `target` 名稱不用動）。

> `firebase.json` 與 `.firebaserc` 一定要放在 repo 根目錄。firebase CLI 只在
> **當前目錄**找這兩個檔，而且 `hosting.public` 是相對於 **`firebase.json` 自己的
> 位置**解析的 —— 放進子目錄會變成找 `firebase/web`，然後報
> `Directory 'web' for Hosting does not exist`。規則檔留在 `firebase/` 沒問題，
> 因為 `firebase.json` 裡已經寫成 `firebase/firestore.rules`。

舊站 `d8ainews.web.app` 確認新站正常後再停用：

```bash
firebase hosting:sites:delete d8ainews
```

（刪的是 hosting site，Firestore 資料與專案本身都不受影響。）

### 4. 灌入歷史資料

```bash
pip install -r requirements.txt
python3 scripts/migrate_legacy.py             # 全部匯入
python3 scripts/migrate_legacy.py --dry-run   # 先看會匯哪些
```

匯完到 Firestore Console 確認 `events` / `daily_summary` 兩個 collection 有資料即可。

### 5. GitHub Actions Secrets

到 GitHub repo → Settings → Secrets and variables → Actions，新增：

| Secret | 內容 |
| --- | --- |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | 整段 service account JSON 的內容（複製 `firebase-credentials.json` 整檔貼上） |
| `AINEWS_LLM_API_KEY` | LLM API key |
| `AINEWS_LLM_BASE_URL` | LLM base URL（例如 `http://125.227.53.125:50062/`） |
| `AINEWS_LLM_MODEL` | 模型名（例如 `gemma-4-31B-it`） |
| `HF_TOKEN` | Hugging Face token（用於 FLUX 生封面圖；可留空） |

設好後 [`.github/workflows/daily.yml`](.github/workflows/daily.yml) 會每天 UTC 22:00（台灣 06:00）自動跑。

---

## 四、手動執行

```bash
# 本地手動跑（需要 firebase-credentials.json 在根目錄）
python3 src/pipeline.py --days 1
python3 src/pipeline.py --days 3 --google                  # 加上 Google News 補強
python3 src/pipeline.py --kinds vendor podcast             # 只抓某些來源
AINEWS_STORE=local python3 src/pipeline.py --days 1         # 只寫本地 store
AINEWS_STORE=both python3 src/pipeline.py --days 1          # 本地 + Firestore 都寫

# GitHub Actions 也可在 repo Actions 頁面手動觸發（workflow_dispatch）
# Docker 見第九章
```

---

## 五、資料 Schema

Firestore 與本地 store 用**同一份** schema（`src/doc_model.py`），
所以前端不需要分辨資料從哪來，兩種部署也能互相匯出匯入。

### `events/{date}_{event_id}`
| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `event_id` | string | 10 字元 SHA1 |
| `date` | string | `YYYY-MM-DD` |
| `title` / `summary` | string | LLM 抽出的事件標題與摘要 |
| `category` / `category_label` | string | 分類 id 與中文標籤 |
| `importance` / `mention_count` | int | 重要度 (0-10) 與報導數 |
| `who[]` / `what` / `when` / `where` | — | 5W |
| `sources[]` | array | 證據來源（url, title, source_name, source_kind, published） |
| `cover_image` | map | `{kind: "remote"\|"fallback", url?, category?}` |
| `is_top` | bool | 是否在當日精選 |
| `generated_at` | string ISO | UTC 時間戳 |

### `daily_summary/{date}`
| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `date` | string | `YYYY-MM-DD` |
| `total_db` / `total_top` | int | 當日事件數與精選數 |
| `by_category_label` | map | `{ 中文標籤: 數量 }` |
| `generated_at` | string ISO | |

---

## 六、安全模型

- **Firestore Rules**：所有 collection 開放 public read，前端的 firebaseConfig 雖然會被看到但無法寫入。
- **寫入權限**：只有持有 service account JSON 的 GitHub Actions（或本機）能寫，靠 Admin SDK 繞過 rules。
- **Storage**：封面圖公開讀，同樣只有 service account 能上傳。

把 `firebase-credentials.json` 守好，不要 commit、不要貼到 Slack/聊天室。
GitHub Secret 不會在 logs 顯示，安全的方式是直接複製整段 JSON 內容貼到 secret 欄位。

---

## 七、本地預覽前端

```bash
# 自架版（讀本地 output/store，附 /api 與 /media）
python3 src/server.py --port 8080

# 雲端版（純靜態，前端會去讀 Firestore）
cd web && python3 -m http.server 5173
```

或用 Firebase 模擬器：

```bash
firebase emulators:start --only hosting
```

---

## 八、前端功能

### 1. 精選指標（自己決定「精選」怎麼挑）

精選卡片右邊有一塊「精選指標」面板，勾選你在意的指標，精選就會即時依這些指標重新排序、重新篩選（可複選，選擇會記在瀏覽器 localStorage）：

| 指標 | 依據 |
| --- | --- |
| 重要度 | LLM 給的 `importance`（0–10） |
| 報導熱度 | `mention_count`（同一件事被幾篇報導提到） |
| 來源多樣性 | 跨幾家媒體、幾種 `source_kind` |
| 時效性 | 越接近區間最新一天分數越高 |
| 主體聲量 | 事件主角（`who`）在區間內跨幾個事件出現 |
| 台灣相關 | 有 `source_region == "TW"` 的來源，或內文提到台灣 |
| 開源熱度 | GitHub / HuggingFace 的 stars、下載、按讚數 |
| 深度內容 | `full_content` 長度（有完整內文才適合放進電子報） |

每個指標會先在「目前區間的事件池」內正規化成 0~1，再把被勾選的指標平均成「精選分」（卡片上會顯示，滑上去可看各指標分數）。沒有勾任何指標時，退回預設的「重要度 + 報導熱度」。

顯示則數（3 / 6 / 9 / 12 / 20）也可以在同一塊面板調整；
點面板標題可以把整塊指標收起來，「開源生態與模型觀測站」也一樣可收合，收合狀態會記住。

### 2. 事件資料庫

- 日期範圍是**真的日曆日**：選「近 14 天」就是用 `date >= 起日 AND date <= 迄日` 直接查 Firestore，範圍內每一天、每一則事件都會列出來（不再只抓「有 daily_summary 的 N 天」）。
- 清單分頁顯示，每頁 10 / 20 / 50 / 100 則可選，下方有「上一頁 / 下一頁 / 頁碼 / 末頁」。

### 3. 電子報 PDF

在卡片或清單勾選「加入電子報」（或按精選面板的「精選全部加入電子報」），右下角工具列按 **產生電子報 PDF**，會開一個排好版的視窗（彈出視窗被擋時改用頁內全螢幕預覽），在列印對話框選「另存為 PDF」即可。

版面對齊雙週電子報範本：

1. **目錄頁**：頁首（左 logo｜期別 + 日期｜右 logo）→ 主視覺橫幅 + 橘色刊名膠囊 → 分類標籤 → 每頁 3 張新聞卡（縮圖 + 標題 + 摘要 + 日期/來源）→ 右下角換頁按鈕。
2. **內文頁**：滿版橫幅 + 白色圓角卡（標題 / 日期·來源 / 小標 / 內文），內容太長自動續頁並標「(承上頁)」，右下角有「上一頁 / 首頁 / 下一頁」。

分頁是在瀏覽器裡「實際量測」出來的，所以不會出現半行被切掉或溢出頁面。

**換成自己的品牌**：改 [`web/report.js`](web/report.js) 最上面的 `DEFAULT_CFG`（刊名、期別、日期、四個素材路徑），素材換掉 `web/assets/` 內同名檔案即可；刊名 / 期別 / 日期也可以直接在工具列的「版面設定」填，會存在 localStorage。

---

## 九、自架版：Docker（完全本地，不需要 Firebase）

雲端那套（GitHub Actions + Firebase）**照舊保留**，兩邊可以並存。
自架版把資料存成本地 JSON、封面圖留在本機、網站也由容器自己提供，
整台機器斷開外網（除了抓新聞與呼叫 LLM）也能運作。

### 1. 準備

```bash
cp .env.example .env
# 至少要填 AINEWS_LLM_API_KEY，其餘有預設值
```

`.env` 已在 `.gitignore`；程式碼裡不再有任何寫死的金鑰，沒填會直接報錯不會白跑。

### 2. 啟動

```bash
docker build -f docker/Dockerfile -t ainews:latest .   # 建 image
docker compose up -d                                   # 排程 + 網站
open http://localhost:8080
```

> 一般情況下 `docker compose up -d --build` 一行就好；
> 但如果專案路徑含有中文之類的非 ASCII 字元，compose 的 bake 會噴
> `x-docker-expose-session-sharedkey ... non-printable ASCII characters`，
> 這時就照上面拆成 `docker build` + `docker compose up -d`。

會起兩個容器：

| 容器 | 做什麼 |
| --- | --- |
| `ainews` | 排程器，每天 `AINEWS_RUN_AT`（預設 06:00）跑一次 pipeline，寫進 `output/store/` |
| `ainews-web` | 網站（預設 8080）：靜態前端 + `/api/*` 資料 + `/media/*` 封面圖 |

### 3. 常用指令

```bash
docker compose run --rm ainews once                      # 立刻抓一次
docker compose run --rm -e AINEWS_DAYS=3 ainews once     # 抓近 3 天
docker compose logs -f                                   # 看紀錄
docker compose restart web                               # 只重啟網站
docker compose down                                      # 全部停掉
docker compose run --rm ainews python3 scripts/repair_day.py --date 2026-08-24
```

### 4. 把雲端歷史資料搬下來

本地 store 一開始是空的，用這支把 Firestore 既有資料倒回來（需要 `firebase-credentials.json`）：

```bash
python3 scripts/export_firestore_local.py                     # 全部
python3 scripts/export_firestore_local.py --start 2026-08-01  # 指定區間
python3 scripts/export_firestore_local.py --download-images   # 順便把封面圖抓成本地檔
```

不加 `--download-images` 的話，封面仍指向 Firebase Storage 的網址（要外網才看得到）。

### 5. 環境變數

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `AINEWS_LLM_API_KEY` | 無（必填） | LLM 金鑰，沒填 pipeline 會直接停 |
| `AINEWS_LLM_BASE_URL` / `_MODEL` | d8ai gateway / `gemma-4-31B-it` | LLM 端點與模型 |
| `AINEWS_STORE` | `local` | `local` / `firestore` / `both` |
| `AINEWS_RUN_AT` | `06:00` | 每天幾點跑（依 `TZ`） |
| `AINEWS_DAYS` | `1` | 抓近 N 天 |
| `AINEWS_ARGS` | 空 | 額外參數，例如 `--google`、`--kinds vendor podcast` |
| `AINEWS_RUN_ON_START` | `0` | 設 `1` 則容器一啟動先跑一次 |
| `AINEWS_WEB_PORT` | `8080` | 網站埠號 |
| `AINEWS_OUTPUT_DIR` | `/app/output` | 資料目錄（compose 已掛到主機 `./output`） |
| `TZ` | `Asia/Taipei` | 容器時區 |

### 6. 資料放在哪

```
output/
├── store/2026-08-24.json     ← 事件資料庫（網站讀這個）
├── images/2026-08-24/*.png   ← 封面圖（網站以 /media/ 提供）
└── 2026-08-24_AI新聞_*.json / .xlsx
```

備份＝直接複製 `output/`；要看資料直接打開 JSON 就行，不用連任何雲端服務。

### 7. 搬到另一台機器（部署包）

一行打包成單一檔案，丟過去解開就能跑：

```bash
sh scripts/make_bundle.sh --with-data     # image + compose + 說明 + 現有事件資料
```

參數：

| 參數 | 作用 |
| --- | --- |
| （無） | 只包 image + `compose.yaml` + `.env.example` + `README.txt` |
| `--with-data` | 加上 `output/store/`（既有事件資料，網站一開就有內容） |
| `--with-images` | 再加上 `output/images/`（封面圖，檔案較大） |
| `--with-env` | 連 `.env` 一起包（**內含金鑰**，請用安全管道傳輸） |

產出 `dist/ainews-bundle-YYYYMMDD.tar.gz`。目標機器上：

```bash
tar -xzf ainews-bundle-YYYYMMDD.tar.gz && cd ainews
docker load < ainews-image.tar.gz
cp .env.example .env        # 填 AINEWS_LLM_API_KEY（有帶 --with-env 就跳過）
docker compose up -d
# 開 http://<這台機器的IP>:8080
```

部署包裡的 `compose.yaml` 不含 `build:`，也不會掛載 `web/`（前端已經在 image 裡），
所以目標機器**不需要原始碼**。

**CPU 架構**：打包前建議先建成雙架構 image，x86 伺服器與 ARM 機器都能跑：

```bash
docker buildx build --platform linux/amd64,linux/arm64 -f docker/Dockerfile -t ainews:latest --load .
```

只建單一架構的話，image 只能在同架構的機器上跑（例如在 Apple Silicon 建的
arm64 image 放不到一般 x86 伺服器）。

### 8. 還是想寫回 Firestore？

`.env` 把 `AINEWS_STORE` 改成 `firestore` 或 `both`，並提供憑證（二擇一）：

- `.env` 填 `FIREBASE_SERVICE_ACCOUNT_JSON=<整份 JSON 貼成一行>`
- 或在 `compose.yaml` 的 volumes 加一行
  `- ./firebase-credentials.json:/app/firebase-credentials.json:ro`
