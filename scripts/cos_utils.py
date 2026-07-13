"""COS 公共工具：从 test_cos_upload.py 抽出的可复用函数."""

import os
from pathlib import Path

from dotenv import load_dotenv
from qcloud_cos import CosConfig, CosS3Client

load_dotenv()

SECRET_ID = os.getenv("COS_SECRET_ID", "")
SECRET_KEY = os.getenv("COS_SECRET_KEY", "")
REGION = os.getenv("COS_REGION", "ap-guangzhou")
BUCKET = os.getenv("COS_BUCKET", "")


def make_client() -> CosS3Client:
    if not (SECRET_ID and SECRET_KEY and BUCKET):
        missing = [
            n
            for n, v in [
                ("COS_SECRET_ID", SECRET_ID),
                ("COS_SECRET_KEY", SECRET_KEY),
                ("COS_BUCKET", BUCKET),
            ]
            if not v
        ]
        raise RuntimeError(f".env 缺少配置: {', '.join(missing)}")
    cfg = CosConfig(Region=REGION, SecretId=SECRET_ID, SecretKey=SECRET_KEY)
    return CosS3Client(cfg)


def make_public_url(cos_key: str) -> str:
    return f"https://{BUCKET}.cos.{REGION}.myqcloud.com/{cos_key}"


_CONTENT_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


def content_type_for(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    return _CONTENT_TYPE.get(ext, "application/octet-stream")


def upload_file(client: CosS3Client, key: str, local_path: str | Path) -> str:
    """上传并返回公开 URL.

    ACL=public-read，公开可访问，适合喂多模态模型."""
    local_path = Path(local_path)
    with open(local_path, "rb") as f:
        data = f.read()
    client.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type_for(local_path),
        ACL="public-read",
    )
    return make_public_url(key)


def exists(client: CosS3Client, key: str) -> bool:
    """HEAD 检查，True 表示 COS 上已存在."""
    try:
        client.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False
