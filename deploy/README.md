# 每日任務搬到 Google Cloud Run Jobs

2026-11-06 起 GitHub 帳號因帳務問題被鎖，Actions 全部停擺。
這份是 **AInews（晨誌）** 與 **resolution（解析度）** 兩個每日任務一起搬到 Google Cloud 的做法：
同一個專案，掛在既有的「Firebase Payment」計費帳戶（d8ainews 本來就在這個帳戶），免費額度合併計算。

## 架構

```
Cloud Scheduler（Asia/Taipei，準時）
  06:30 ─▶ Cloud Run Job resolution-daily
  │          bucket 拉作品池與當日檔 → pipeline → 部署 Firebase Hosting（resolution-0000）→ 存回 bucket
  07:28 ─▶ Cloud Run Job ainews-daily
             pipeline → 寫 Firestore（d8ainews）→ 封面圖上 Cloudflare R2
```

| 原本在 GitHub | 現在 |
|---|---|
| Actions cron（會排隊延遲數小時） | Cloud Scheduler（準時） |
| Cloudflare Worker 準時觸發 + 07:43 重試 | 不需要；AInews 失敗自動重跑 1 次（`--max-retries 1`） |
| GitHub Secrets | Secret Manager，每個 job 一個 secret（KEY=VALUE 檔） |
| Firebase service account 金鑰 JSON | 不用金鑰：job 的 service account 直接被授權跨專案寫入 |
| resolution 把當日檔與作品池 commit 回 repo | 存在 bucket `gs://<專案>-resolution-state` |
| Actions 執行紀錄、失敗變紅 | Cloud Run → Jobs → 執行紀錄；失敗一樣標紅 |

兩個網站本身（Firebase Hosting、Firestore）都沒有動。

## 費用

一般用量在免費額度內（以 us-central1 計，以[官方價目](https://cloud.google.com/run/pricing)為準）。
免費額度是整個計費帳戶共用：同一個帳戶底下其他專案的 Cloud Run 用量會跟這兩個 job 一起算。

- Cloud Run Jobs：每月免費 240,000 vCPU-秒、450,000 GiB-秒。
  最壞情況兩個 job 合計約 120,000 vCPU-秒、240,000 GiB-秒。
- Cloud Scheduler：每個計費帳戶 3 個免費，我們用 2 個。
- Secret Manager：6 個有效版本免費，我們用 2 個（secrets.sh 會自動銷毀舊版本）。
- Artifact Registry：0.5 GB 免費，倉庫設成每個 image 只留最新 2 版。
- Cloud Build：每月有免費 build 分鐘數，一次部署約 3–5 分鐘。

建議在計費帳戶設一個 1 美元的預算警示（只會寄信，不會自動停止服務）。

## 第一次設定

### 0. 計費帳戶（已決定）

用既有的「Firebase Payment」帳戶（d8ainews 本來就在這個帳戶）。
2026-11-09 原本開了新帳戶，但那張卡被要求先預付 NT$1,000，沒完成就被 Google 關閉，所以改用這個。

帳戶 ID 不進版控（repo 是公開的），放在兩個 repo 各自的 `deploy/local.env`：

```
BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX
```

`gcloud billing accounts list` 可以查 ID。

`PROJECT_ID` 全球唯一，`d8-daily-jobs` 被用走了就換一個，兩邊一樣改。

### 1. 建專案與權限（在 AInews repo 跑一次）

```bash
bash deploy/bootstrap.sh
```

### 2. 放金鑰（兩個 repo 各一次）

GitHub 上的 secrets 讀不回來，要從原本的地方重拿，說明在各自的 `*.env.example` 裡。

```bash
cp deploy/ainews.env.example deploy/ainews.env
bash deploy/secrets.sh
```

resolution repo 那邊是 `resolution.env.example` → `resolution.env`。

### 3. resolution 的作品池放進 bucket（resolution repo 跑一次）

```bash
bash deploy/seed_state.sh
```

### 4. 部署（兩個 repo 各一次，之後改程式就再跑）

```bash
bash deploy/deploy.sh
```

### 5. 手動跑一次確認

```bash
gcloud run jobs execute resolution-daily --project d8-daily-jobs --region us-central1 --wait
gcloud run jobs execute ainews-daily --project d8-daily-jobs --region us-central1 --wait
```

執行紀錄與 log：Cloud Run → Jobs → 點 job → 執行作業。

### 6. 收尾

- 停掉 Cloudflare 上的 `cron-trigger` Worker（它會繼續去呼叫已經被鎖的 GitHub）：
  Cloudflare 後台 → Workers → cron-trigger → Settings → Triggers 刪掉 cron，或直接刪 Worker。
- `.github/workflows/` 與 `cron-trigger/` 可以等確認穩定後再刪。

## 常用操作

```bash
# 手動補跑 resolution 某一天
gcloud run jobs execute resolution-daily --project d8-daily-jobs --region us-central1 \
  --update-env-vars RES_DATE=2026-11-07

# AInews 抓近 3 天、加 Google News
gcloud run jobs execute ainews-daily --project d8-daily-jobs --region us-central1 \
  --update-env-vars "AINEWS_DAYS=3,AINEWS_ARGS=--google"

# 暫停 / 恢復排程
gcloud scheduler jobs pause ainews-daily-trigger --project d8-daily-jobs --location us-central1
gcloud scheduler jobs resume ainews-daily-trigger --project d8-daily-jobs --location us-central1

# 看最近一次的 log
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="ainews-daily"' \
  --project d8-daily-jobs --limit 100 --freshness 1d --format 'value(textPayload)'
```

換金鑰：改 `deploy/*.env` 再跑 `deploy/secrets.sh`，下次執行就生效，不用重新部署。
改排程時間：改兩邊的 `deploy/config.env`，再跑該 repo 的 `deploy/deploy.sh`。
