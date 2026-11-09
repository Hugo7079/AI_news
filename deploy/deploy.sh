#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 部署 AInews 每日任務到 Cloud Run Job，並設定每天自動觸發
#
#   bash deploy/deploy.sh
#
# 改了程式就再跑一次：重新 build image、更新 job，排程設定也會同步。
# 前提：已跑過 deploy/bootstrap.sh 與 deploy/secrets.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source deploy/config.env

JOB=ainews-daily
P=(--project "$PROJECT_ID")
SA="${JOB_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# image 標籤：commit + 時間；有沒 commit 的改動就加 -dirty，事後查得到部署的是哪一版
REV=$(git rev-parse --short HEAD 2>/dev/null || echo nogit)
git diff --quiet HEAD 2>/dev/null || REV="${REV}-dirty"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/ainews:${REV}-$(date +%Y%m%d-%H%M%S)"

echo "== 1. build ${IMAGE}"
gcloud builds submit "${P[@]}" --region "$REGION" \
  --config deploy/cloudbuild.yaml --substitutions "_IMAGE=${IMAGE}" .

echo "== 2. 更新 Cloud Run Job ${JOB}"
# 非機密設定直接寫在這裡（等同原本 daily.yml 的 env）；機密在 Secret Manager 的 ainews-env，
# 掛成 /secrets/ainews.env，由 docker/entrypoint.sh 載入。
# --max-retries 1：失敗自動重跑一次，取代原本 07:43 那次重試。
# --task-timeout 90m：跟原本 GitHub Actions 的上限一樣，pipeline 內的時間預算也是照這個算的。
gcloud run jobs deploy "$JOB" "${P[@]}" --region "$REGION" \
  --image "$IMAGE" \
  --service-account "$SA" \
  --args job \
  --tasks 1 --max-retries 1 --task-timeout 90m \
  --cpu 1 --memory 2Gi \
  --set-env-vars "^|^AINEWS_STORE=firestore|AINEWS_DAYS=1|AINEWS_LLM_BASE_URL=https://llm-gateway.d8ai.ai/|AINEWS_LLM_MODEL=gemma-4-31B-it|AINEWS_LLM_RPM=45|AINEWS_IMAGE_BACKEND=cloudflare|AINEWS_R2_BUCKET=ainews-covers|TZ=Asia/Taipei" \
  --set-secrets "/secrets/ainews.env=ainews-env:latest"

echo "== 3. 排程 ${AINEWS_SCHEDULE}（Asia/Taipei）"
TRIGGER="${JOB}-trigger"
URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB}:run"
ARGS=(--location "$REGION" --schedule "$AINEWS_SCHEDULE" --time-zone "Asia/Taipei"
      --uri "$URI" --http-method POST --oauth-service-account-email "$SA")
if gcloud scheduler jobs describe "$TRIGGER" "${P[@]}" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$TRIGGER" "${P[@]}" "${ARGS[@]}"
else
  gcloud scheduler jobs create http "$TRIGGER" "${P[@]}" "${ARGS[@]}"
fi

echo
echo "完成。立刻手動跑一次："
echo "  gcloud run jobs execute ${JOB} --project ${PROJECT_ID} --region ${REGION}"
