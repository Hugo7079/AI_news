#!/bin/bash
# 每日 AI 新聞爬搜 — 排程進入點
# 用法：crontab -e  加入：
#   0 8 * * * /Users/leolee/AI新聞爬搜整理/run_daily.sh >> /Users/leolee/AI新聞爬搜整理/output/cron.log 2>&1

set -e
cd "$(dirname "$0")"

# 若用 venv，請取消註解
# source .venv/bin/activate

PYTHON="${PYTHON:-python3}"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_daily.sh 開始 ====="
"$PYTHON" pipeline.py --days 1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始自動提交並推送數據至 GitHub ====="
# 將生成的 JSON 數據與封面圖新增至 Git 暫存區（會自動依據 .gitignore 排除 Excel 與日誌）
git add output/

# 檢查是否有任何數據變更，如果有則自動提交並推送
if ! git diff-index --quiet HEAD --; then
    git commit -m "data: auto-update daily news database and images for $(date '+%Y-%m-%d')"
    git push origin main
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') 數據已成功推送至 GitHub ====="
else
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') 數據無任何變更，跳過推送 ====="
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 完成 ====="
