"""
Cloudflare R2 封面圖儲存
========================

**這是選配路徑，預設不啟用。** 封面圖預設走 Firebase Storage（見
firestore_writer._upload_cover），只有設了 AINEWS_R2_* 環境變數才改走這裡。

用途：不想把 Firebase 專案升到 Blaze 時的替代方案。R2 免費額度 10GB 存放、
Class A 操作 100 萬次/月、流量不計費。
但要注意 —— **R2 開通同樣需要在 Cloudflare 填付款方式**，所以這不是「免綁卡」
的解法；兩邊都要綁卡的話，Blaze 反而比較單純（不用多接一個服務）。

R2 是 S3 相容介面，用 boto3 走 SigV4。

設定（見 .env.example）：
  AINEWS_R2_ACCOUNT_ID         留空則沿用 AINEWS_CF_ACCOUNT_ID
  AINEWS_R2_ACCESS_KEY_ID      R2 API token 的 Access Key ID
  AINEWS_R2_SECRET_ACCESS_KEY  R2 API token 的 Secret Access Key
  AINEWS_R2_BUCKET             bucket 名稱，預設 ainews-covers
  AINEWS_R2_PUBLIC_BASE        對外網址前綴，例如 https://pub-xxxx.r2.dev
                               （bucket Settings → Public Development URL，
                                或綁自訂網域）

金鑰與 Workers AI 那把 token 不同：R2 要在
dash.cloudflare.com → R2 → Manage R2 API Tokens 另外建，權限選 Object Read & Write。
"""

from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Optional

_client = None
_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "webp": "image/webp",
}


def config() -> dict:
    # 與生圖設定同一套來源：環境變數優先，其次 .ainews_llm_config.json
    from config import IMAGE_CFG, _local_json_cfg
    f = _local_json_cfg()

    def pick(env_key: str, file_key: str, default: str = "") -> str:
        return (os.getenv(env_key, "").strip()
                or str(f.get(file_key, "") or "").strip()
                or default)

    return {
        "account_id": pick("AINEWS_R2_ACCOUNT_ID", "r2_account_id") or IMAGE_CFG.get("cf_account_id", ""),
        "access_key": pick("AINEWS_R2_ACCESS_KEY_ID", "r2_access_key_id"),
        "secret_key": pick("AINEWS_R2_SECRET_ACCESS_KEY", "r2_secret_access_key"),
        "bucket": pick("AINEWS_R2_BUCKET", "r2_bucket", "ainews-covers"),
        "public_base": pick("AINEWS_R2_PUBLIC_BASE", "r2_public_base").rstrip("/"),
    }


def is_configured() -> bool:
    c = config()
    return bool(c["account_id"] and c["access_key"] and c["secret_key"])


def check_config() -> Optional[str]:
    """設定有問題就回一句人話，沒問題回 None。"""
    c = config()
    if not c["account_id"]:
        return "AINEWS_R2_ACCOUNT_ID（或 AINEWS_CF_ACCOUNT_ID）沒有設定"
    if not c["access_key"] or not c["secret_key"]:
        return ("AINEWS_R2_ACCESS_KEY_ID / AINEWS_R2_SECRET_ACCESS_KEY 沒有設定。\n"
                "    到 dash.cloudflare.com → R2 → Manage R2 API Tokens 建一組，"
                "權限選 Object Read & Write。\n"
                "    注意這跟 Workers AI 的 token 是兩把不同的金鑰。")
    if not c["public_base"]:
        return ("AINEWS_R2_PUBLIC_BASE 沒有設定 —— 沒有它就算上傳成功，網站也拿不到圖。\n"
                "    到 bucket 的 Settings 開啟 Public Development URL，"
                "把 https://pub-xxxx.r2.dev 填進來（或綁自訂網域）。")
    try:
        import boto3  # noqa: F401
    except ImportError:
        return "boto3 沒有安裝 —— 執行 pip install -r requirements.txt"
    return None


def _get_client():
    global _client
    if _client is not None:
        return _client
    import boto3
    from botocore.config import Config

    c = config()
    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{c['account_id']}.r2.cloudflarestorage.com",
        aws_access_key_id=c["access_key"],
        aws_secret_access_key=c["secret_key"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )
    return _client


def ensure_bucket() -> bool:
    """bucket 不存在就建一個。已存在回 True。"""
    from botocore.exceptions import ClientError
    c = config()
    cli = _get_client()
    try:
        cli.head_bucket(Bucket=c["bucket"])
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code not in ("404", "NoSuchBucket", "NotFound"):
            print(f"  [r2] 檢查 bucket 失敗：{e}")
            return False
    try:
        cli.create_bucket(Bucket=c["bucket"])
        print(f"  [r2] 已建立 bucket {c['bucket']}")
        return True
    except ClientError as e:
        print(f"  [r2] 建立 bucket 失敗：{e}")
        return False


def upload(local_path: Path, key: str) -> Optional[str]:
    """上傳單一檔案，回傳公開網址；失敗回 None。

    網址帶內容 hash 當版本參數：封面檔名是來源 URL 的固定 hash，重生後檔名不變，
    沒有版本參數的話瀏覽器/CDN 會一直給舊圖。
    """
    from botocore.exceptions import ClientError, BotoCoreError

    local_path = Path(local_path)
    if not local_path.exists():
        print(f"  [r2] 找不到本地檔：{local_path}")
        return None

    c = config()
    ext = local_path.suffix.lstrip(".").lower()
    ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
    data = local_path.read_bytes()

    try:
        _get_client().put_object(
            Bucket=c["bucket"],
            Key=key,
            Body=data,
            ContentType=ctype,
            # 圖是不可變的（換內容就換 URL 版本參數），可以放心長快取
            CacheControl="public, max-age=31536000, immutable",
        )
    except (ClientError, BotoCoreError) as e:
        print(f"  [r2] 上傳失敗 {key}：{e}")
        return None

    ver = hashlib.sha1(data).hexdigest()[:8]
    return f"{c['public_base']}/{key}?v={ver}"
