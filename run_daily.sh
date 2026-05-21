#!/bin/bash
# 每日 AI 新聞爬搜 — 排程進入點
# 用法：crontab -e  加入：
#   0 8 * * * /Users/leolee/Desktop/AI新聞爬搜整理/run_daily.sh >> /Users/leolee/Desktop/AI新聞爬搜整理/output/cron.log 2>&1

set -e
cd "$(dirname "$0")"

# 若用 venv，請取消註解
# source .venv/bin/activate

PYTHON="${PYTHON:-python3}"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_daily.sh 開始 ====="
"$PYTHON" pipeline.py --days 1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 完成 ====="
