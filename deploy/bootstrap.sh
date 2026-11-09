#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 一次性建置：AInews 與 resolution 共用的 Google Cloud 專案
#
#   bash deploy/bootstrap.sh
#
# 會做的事（可重複執行，已經存在的會跳過）：
#   1. 建專案 PROJECT_ID，掛到計費帳戶 BILLING_ACCOUNT（deploy/local.env）
#   2. 開 API：Cloud Run / Scheduler / Build / Artifact Registry / Secret Manager / Storage
#   3. 建 job 執行身分 daily-jobs-runner，只給它需要的權限
#   4. 建 Docker image 倉庫（只留最新 2 版，維持在 0.5 GB 免費額度內）
#   5. 建 resolution 的狀態 bucket（作品池與歷史當日檔）
#   6. 跨專案授權：
#        d8ainews        → Firestore 寫入（AInews 寫新聞）
#        resolution-0000 → Firebase Hosting 部署（resolution 發佈網站）
#      這樣兩個 job 都不需要 Firebase 金鑰檔。
#
# 前提：gcloud 已登入一個對 d8ainews、resolution-0000 有 Owner 權限的帳號
#       （d8ainews、resolution-0000 兩個 Firebase 專案的擁有者即可）
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./config.env

if [ -z "${BILLING_ACCOUNT:-}" ]; then
  echo "請先在 deploy/local.env 填 BILLING_ACCOUNT=<計費帳戶 ID>（gcloud billing accounts list 可查）" >&2
  exit 1
fi

say() { printf '\n== %s\n' "$*"; }
P=(--project "$PROJECT_ID")
SA="${JOB_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

say "1. 專案 ${PROJECT_ID}"
if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud projects create "$PROJECT_ID" --name="Daily jobs"
fi
gcloud billing projects link "$PROJECT_ID" --billing-account "$BILLING_ACCOUNT"

say "2. 開 API"
# firestore / firebasehosting / firebase 也要在這個專案開：
# 用這個專案的 service account 跨專案呼叫時，有些 API 會檢查呼叫端專案有沒有啟用。
# 只是啟用，不會建資料庫、不會產生費用。
gcloud services enable "${P[@]}" \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  firestore.googleapis.com \
  firebasehosting.googleapis.com \
  firebase.googleapis.com
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

say "3. job 執行身分 ${SA}"
if ! gcloud iam service-accounts describe "$SA" "${P[@]}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$JOB_SA_NAME" "${P[@]}" \
    --display-name="AInews / resolution 每日任務"
fi
# 讀 Secret Manager 的金鑰、被 Cloud Scheduler 拿來觸發 job
for role in roles/secretmanager.secretAccessor roles/run.invoker; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" --role="$role" --condition=None --quiet >/dev/null
done

say "4. Docker image 倉庫 ${AR_REPO}"
if ! gcloud artifacts repositories describe "$AR_REPO" "${P[@]}" --location "$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" "${P[@]}" \
    --location "$REGION" --repository-format docker \
    --description "AInews / resolution 每日任務的 image"
fi
POLICY=$(mktemp)
cat > "$POLICY" <<'JSON'
[
  {"name": "keep-latest-2", "action": {"type": "Keep"},
   "mostRecentVersions": {"keepCount": 2}},
  {"name": "delete-older", "action": {"type": "Delete"},
   "condition": {"olderThan": "1d"}}
]
JSON
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" "${P[@]}" \
  --location "$REGION" --policy "$POLICY" --no-dry-run --quiet >/dev/null
rm -f "$POLICY"

# Cloud Build 預設用 Compute Engine 預設 service account 來 build；
# 新專案不一定自動給它權限，這裡明確補上：讀上傳的原始碼、推 image、寫 log。
BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for role in roles/artifactregistry.writer roles/storage.objectViewer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${BUILD_SA}" --role="$role" --condition=None --quiet >/dev/null
done

say "5. resolution 狀態 bucket gs://${STATE_BUCKET}"
if ! gcloud storage buckets describe "gs://${STATE_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${STATE_BUCKET}" "${P[@]}" \
    --location "$REGION" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets add-iam-policy-binding "gs://${STATE_BUCKET}" \
  --member="serviceAccount:${SA}" --role=roles/storage.objectAdmin --quiet >/dev/null

say "6. 跨專案授權"
# AInews：寫 Firestore（封面圖走 Cloudflare R2，不需要 Firebase Storage 權限）
gcloud projects add-iam-policy-binding "$AINEWS_FIREBASE_PROJECT" \
  --member="serviceAccount:${SA}" --role=roles/datastore.user --condition=None --quiet >/dev/null
# resolution：部署 Firebase Hosting。
# Service Usage Consumer 是 firebase-tools 15.34.1 起部署前要查的權限（GitHub 時代 403 過）
for role in roles/firebasehosting.admin roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$RES_FIREBASE_PROJECT" \
    --member="serviceAccount:${SA}" --role="$role" --condition=None --quiet >/dev/null
done

say "完成。接下來：兩個 repo 各自跑 deploy/secrets.sh 與 deploy/deploy.sh（見 deploy/README.md）"
