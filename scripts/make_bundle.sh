#!/bin/sh
# ─────────────────────────────────────────────────────────────
# 打包成可以直接搬到另一台機器的部署包
#
#   sh scripts/make_bundle.sh                       # image + compose + 說明
#   sh scripts/make_bundle.sh --with-data           # 連本地事件資料一起帶
#   sh scripts/make_bundle.sh --with-data --with-images   # 連封面圖一起帶
#   sh scripts/make_bundle.sh --with-env            # 連 .env（含金鑰！）一起帶
#
# 產出：dist/ainews-bundle-YYYYMMDD.tar.gz
# ─────────────────────────────────────────────────────────────
set -eu

IMAGE="${AINEWS_IMAGE:-ainews:latest}"
WITH_ENV=0
WITH_DATA=0
WITH_IMAGES=0

for arg in "$@"; do
  case "$arg" in
    --with-env)    WITH_ENV=1 ;;
    --with-data)   WITH_DATA=1 ;;
    --with-images) WITH_DATA=1; WITH_IMAGES=1 ;;
    --help|-h)     sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "未知參數：$arg（--help 看用法）"; exit 1 ;;
  esac
done

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

STAMP=$(date +%Y%m%d)
STAGE="dist/ainews"
OUT="dist/ainews-bundle-${STAMP}.tar.gz"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "找不到 image $IMAGE，請先執行："
  echo "  docker build -f docker/Dockerfile -t ainews:latest ."
  exit 1
fi

echo "[bundle] 清理 $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE"

echo "[bundle] 匯出 image $IMAGE（會花一點時間）"
docker save "$IMAGE" | gzip > "$STAGE/ainews-image.tar.gz"

echo "[bundle] 複製 compose 與設定範本"
cp docker/compose.bundle.yaml "$STAGE/compose.yaml"
cp .env.example "$STAGE/.env.example"

if [ "$WITH_ENV" = "1" ] && [ -f .env ]; then
  cp .env "$STAGE/.env"
  echo "[bundle] 已包含 .env（內含金鑰，請用安全管道傳輸）"
fi

if [ "$WITH_DATA" = "1" ] && [ -d output/store ]; then
  mkdir -p "$STAGE/output"
  cp -R output/store "$STAGE/output/store"
  echo "[bundle] 已包含事件資料 $(ls output/store | wc -l | tr -d ' ') 天"
fi

if [ "$WITH_IMAGES" = "1" ] && [ -d output/images ]; then
  mkdir -p "$STAGE/output"
  cp -R output/images "$STAGE/output/images"
  echo "[bundle] 已包含封面圖"
fi

cat > "$STAGE/README.txt" <<'TXT'
AI新聞 自架部署包
=================

需要目標機器有 Docker（含 docker compose v2）。

1) 載入 image
     docker load < ainews-image.tar.gz

2) 設定金鑰
     cp .env.example .env
     # 編輯 .env，至少要填 AINEWS_LLM_API_KEY
     # （若部署包裡已附 .env 就跳過這步）

3) 啟動
     docker compose up -d

4) 開網站
     http://<這台機器的IP>:8080

常用指令
  docker compose run --rm ainews once     立刻抓一次（不等排程）
  docker compose logs -f                  看紀錄
  docker compose down                     停掉

資料位置
  ./output/store/*.json     事件資料庫（網站讀這個）
  ./output/images/          封面圖
  備份直接複製整個 output/ 就好。

排程
  預設每天 06:00（台北時間）跑一次，改 .env 的 AINEWS_RUN_AT。
  容器設 restart: unless-stopped，機器重開會自己起來。

注意
  - 這台機器需要能連外：抓 RSS 新聞來源、呼叫 LLM gateway。
  - 資料與網站都在本機，不需要 Firebase。
TXT

echo "[bundle] 打包 $OUT"
tar -czf "$OUT" -C dist ainews
rm -rf "$STAGE"

SIZE=$(ls -lh "$OUT" | awk '{print $5}')
echo ""
echo "[bundle] 完成：$OUT（$SIZE）"
echo "         傳到目標機器後解開，照裡面的 README.txt 三步驟即可。"
