#!/bin/sh
# ─────────────────────────────────────────────────────────────
# 容器進入點
#
#   schedule            每天固定時間跑一次（預設 06:00，AINEWS_RUN_AT 可改）
#   once                立刻跑一次就結束（失敗也回 0，給 docker compose 用）
#   job                 立刻跑一次，pipeline 的 exit code 原樣回傳（給 Cloud Run Job 用，
#                       失敗才會被標紅、才會觸發 --max-retries 重試）
#   serve               開本地網站（靜態前端 + /api 資料 + /media 封面圖）
#   <其他指令>          直接執行，例如：
#                       docker run ... ainews python3 scripts/repair_day.py --date 2026-08-24
#
# 常用環境變數：
#   AINEWS_RUN_AT        排程時間 HH:MM（預設 06:00，依 TZ）
#   AINEWS_DAYS          抓近 N 天（預設 1）
#   AINEWS_ARGS          額外參數，例如 "--google" 或 "--kinds vendor podcast"
#   AINEWS_RUN_ON_START  schedule 模式啟動時先跑一次（1 = 是）
#   AINEWS_STORE         local（預設，只寫本地）/ firestore / both
#   AINEWS_WEB_PORT      serve 模式的埠號（預設 8080）
#   AINEWS_SECRETS_FILE  KEY=VALUE 格式的金鑰檔（預設 /secrets/ainews.env，不存在就略過）。
#                        Cloud Run 把 Secret Manager 的一個 secret 掛成這個檔，
#                        所有金鑰塞在同一個 secret 裡，才不會超過免費的 6 個版本。
# ─────────────────────────────────────────────────────────────
set -eu

MODE="${1:-schedule}"
[ "$#" -gt 0 ] && shift || true

RUN_AT="${AINEWS_RUN_AT:-06:00}"
DAYS="${AINEWS_DAYS:-1}"
EXTRA="${AINEWS_ARGS:-}"

log() { echo "[ainews] $(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

# 金鑰檔：一行一個 KEY=VALUE，# 開頭是註解。值不要加引號（會被當成值的一部分）。
SECRETS_FILE="${AINEWS_SECRETS_FILE:-/secrets/ainews.env}"
if [ -f "$SECRETS_FILE" ]; then
  n=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    export "$line"
    n=$((n + 1))
  done < "$SECRETS_FILE"
  log "已從 ${SECRETS_FILE} 載入 ${n} 個金鑰"
fi

run_once() {
  log "開始執行 pipeline（days=${DAYS} ${EXTRA}）"
  set +e
  # shellcheck disable=SC2086
  python3 /app/src/pipeline.py --days "$DAYS" $EXTRA
  code=$?
  set -e
  if [ "$code" -eq 0 ]; then
    log "pipeline 完成"
  else
    log "pipeline 失敗（exit=${code}），等下一次排程再試"
  fi
  return 0
}

case "$MODE" in
  once)
    run_once
    ;;

  job)
    log "Cloud Run Job 模式（days=${DAYS} ${EXTRA}）"
    # shellcheck disable=SC2086
    exec python3 /app/src/pipeline.py --days "$DAYS" $EXTRA
    ;;

  schedule)
    log "排程模式啟動：每天 ${RUN_AT}（TZ=${TZ:-UTC}）跑一次"
    if [ "${AINEWS_RUN_ON_START:-0}" = "1" ]; then
      log "AINEWS_RUN_ON_START=1，先立刻跑一次"
      run_once
    fi
    while true; do
      now=$(date +%s)
      target=$(date -d "today ${RUN_AT}" +%s)
      [ "$target" -le "$now" ] && target=$(date -d "tomorrow ${RUN_AT}" +%s)
      wait_s=$((target - now))
      log "下次執行：$(date -d "@${target}" '+%Y-%m-%d %H:%M:%S %Z')（${wait_s} 秒後）"
      sleep "$wait_s"
      run_once
    done
    ;;

  serve)
    log "啟動本地網站（port ${AINEWS_WEB_PORT:-8080}）"
    exec python3 /app/src/server.py --port "${AINEWS_WEB_PORT:-8080}"
    ;;

  sh|bash|shell)
    # 有帶參數就照跑（例如 sh -c "..."），沒帶就開互動 shell
    if [ "$#" -gt 0 ]; then
      exec /bin/sh "$@"
    fi
    exec /bin/sh
    ;;

  *)
    exec "$MODE" "$@"
    ;;
esac
