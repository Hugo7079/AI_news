#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 把 deploy/ainews.env 上傳成 Secret Manager 的 ainews-env
#
#   cp deploy/ainews.env.example deploy/ainews.env   # 填值（這個檔不進版控）
#   bash deploy/secrets.sh
#
# 所有金鑰放在同一個 secret 裡、只留最新一版：
# Secret Manager 每個計費帳戶免費 6 個「有效版本」，兩個 job 各用 1 個。
# 換金鑰時改 ainews.env 再跑一次即可，舊版本會被銷毀（無法復原，但已經被新版取代）。
# 下次 job 執行就會讀到新值，不用重新部署。
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./config.env

SECRET=ainews-env
FILE=./ainews.env
P=(--project "$PROJECT_ID")

if [ ! -f "$FILE" ]; then
  echo "找不到 deploy/ainews.env：先 cp deploy/ainews.env.example deploy/ainews.env 再填值" >&2
  exit 1
fi
if grep -Eq '^[A-Z0-9_]+=$' "$FILE"; then
  echo "deploy/ainews.env 還有沒填的項目：" >&2
  grep -E '^[A-Z0-9_]+=$' "$FILE" >&2
  exit 1
fi

if ! gcloud secrets describe "$SECRET" "${P[@]}" >/dev/null 2>&1; then
  gcloud secrets create "$SECRET" "${P[@]}" \
    --replication-policy user-managed --locations "$REGION"
fi
gcloud secrets versions add "$SECRET" "${P[@]}" --data-file "$FILE"

# 只留最新一版
OLD=$(gcloud secrets versions list "$SECRET" "${P[@]}" \
        --filter='state!=DESTROYED' --sort-by='~createTime' --format='value(name)' | tail -n +2)
for v in $OLD; do
  gcloud secrets versions destroy "${v##*/}" --secret "$SECRET" "${P[@]}" --quiet
done
echo "已更新 ${SECRET}"
