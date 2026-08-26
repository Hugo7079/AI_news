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

# ── 不用 root 跑 ──
# 反向代理後面只需要一個 >1024 的埠（預設 8080），沒有任何動作需要 root。
# UID/GID 固定成 10001，方便主機上把 ./output 的擁有者對齊：
#   sudo chown -R 10001:10001 output
# 主機的 uid 不是 10001 時，改用 compose 的 user: 覆蓋（見 compose.yaml）。
RUN groupadd -g 10001 ainews \
 && useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin ainews \
 && chown -R ainews:ainews /app
USER ainews:ainews

# 憑證與金鑰一律不打包進 image：用 volume 掛載或環境變數帶入
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["schedule"]
