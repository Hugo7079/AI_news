# ─────────────────────────────────────────────────────────────
# AI新聞爬搜整理 — 可攜式執行環境
#
# build（在專案根目錄執行）：
#   docker build -f docker/Dockerfile -t ainews:latest .
#
# 這個 image 只負責「跑 pipeline」：抓新聞 → LLM 抽事件 → 寫 Firestore。
# 前端仍然是 Firebase Hosting 的靜態網站，不需要這個容器。
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Taipei \
    AINEWS_OUTPUT_DIR=/app/output

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY web/ ./web/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /app/output

# 憑證與金鑰一律不打包進 image：用 volume 掛載或環境變數帶入
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["schedule"]
