# AI 事件中心

每天自動抓取 **台灣 + 國際 + AI 廠商 + 社群 + Podcast** 的 AI 相關新聞，
LLM 抽事件 / 去重 / 分類 → 寫入 **Firestore** → 靜態網站直接顯示。

```
GitHub Actions cron (08:00 TPE)
        │
        ▼
pipeline.py  ──→ Firestore (events, daily_summary)
        │              │
        │              ▼
        │       Firebase Storage (cover images)
        ▼              │
output/*.json          ▼
(本地備份)        web/index.html  ←  Firebase Hosting
                  靜態 SPA, 直接用 Firebase Web SDK 讀 Firestore
```

舊版本用 Streamlit Cloud 顯示，但 Cloud 是 ephemeral filesystem，重啟就丟資料；
這版本資料全進 Firestore，網站只負責顯示，徹底解決「昨天的紀錄又不見了」。

---

## 一、檔案結構

```
.
├── pipeline.py              主流程（CLI 進入點）
├── config.py                分類、關鍵字、LLM 設定
├── sources.py               50+ RSS feed + Google News query
├── sources_extra.py         HF / GitHub / Ollama / OpenRouter
├── fetcher.py               RSS / Google News 抓取
├── llm.py                   OpenAI 相容 LLM 包裝
├── events.py                LLM 抽事件 + 合併
├── classifier.py            LLM 分類 + 去重
├── quality_rank.py          重要度評分 + 過濾
├── cover_image.py           og:image 抓取 + HF FLUX 生圖
├── summarize.py             摘要工具
│
├── firestore_writer.py      ★ 寫入 Firestore + Storage
├── scripts/
│   └── migrate_legacy.py    一次性：把舊 output/*.json 灌進 Firestore
│
├── web/                     ★ 靜態網站（Firebase Hosting）
│   ├── index.html
│   ├── style.css
│   └── app.js               用 Firebase Web SDK 讀 Firestore 渲染
│
├── firebase.json            Hosting + Firestore + Storage 設定
├── .firebaserc              project ID
├── firestore.rules          安全規則：public read, admin-only write
├── storage.rules            同上
│
├── .github/workflows/
│   └── daily.yml            每天 00:00 UTC cron
│
└── output/                  本地備份 JSON（已 gitignore）
```

---

## 二、五大分類

| 對應讀者 | category_id | 內容 |
| --- | --- | --- |
| 技術開發者 | `tech_research` | 新模型、架構、量化、論文 |
| 創業者 / 投資人 | `industry_business` | 融資、併購、財報、合作 |
| 硬體 / 半導體 | `hardware_infra` | GPU/NPU、HBM、資料中心、人形機器人 |
| 企業 IT / PM | `products_apps` | 產品上市、企業導入、AI 工具評測 |
| 政策 / 法務 | `policy_society` | 立法、訴訟、安全、勞動衝擊 |

修改在 [`config.py`](config.py) 的 `CATEGORIES`。

---

## 三、初次設定

### 1. Firebase 專案

Project ID：**d8ainews**（已建好；如要換別的 project，改 [`firestore_writer.py`](firestore_writer.py) 的常數 + [`.firebaserc`](.firebaserc) + [`web/app.js`](web/app.js) 的 `firebaseConfig`）

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

firebase deploy --only firestore:rules
firebase deploy --only storage
firebase deploy --only hosting
```

部署完會得到一個 `https://d8ainews.web.app` 的網址。

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

設好後 [`.github/workflows/daily.yml`](.github/workflows/daily.yml) 會每天 UTC 00:00（台灣 08:00）自動跑。

---

## 四、手動執行

```bash
# 本地手動跑（需要 firebase-credentials.json 在根目錄）
python3 pipeline.py --days 1
python3 pipeline.py --days 3 --google                  # 加上 Google News 補強
python3 pipeline.py --kinds vendor podcast             # 只抓某些來源
AINEWS_SKIP_FIRESTORE=1 python3 pipeline.py --days 1   # 只寫本地 JSON 不上傳

# GitHub Actions 也可在 repo Actions 頁面手動觸發（workflow_dispatch）
```

---

## 五、Firestore Schema

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
# 不用裝任何東西，直接開個小 server
cd web
python3 -m http.server 5173
# 開 http://localhost:5173
```

或用 Firebase 模擬器：

```bash
firebase emulators:start --only hosting
```
