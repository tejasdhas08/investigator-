"""S3/MinIO object storage. All browser media access is via 15-minute pre-signed URLs;
the API never proxies media bytes (ARCHITECTURE.md Section 2)."""
import boto3
from botocore.client import Config

from app.core.config import settings


def _client(endpoint: str | None = None):
    return boto3.client(
        "s3",
        endpoint_url=endpoint or settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def _presign_client():
    # Pre-signed URLs must be valid from the browser, which may reach MinIO on a
    # different hostname than the backend does.
    return _client(settings.s3_public_endpoint_url or settings.s3_endpoint_url)


def ensure_bucket() -> None:
    c = _client()
    try:
        c.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        c.create_bucket(Bucket=settings.s3_bucket)


def presign_put(key: str, content_type: str) -> str:
    return _presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.presign_expiry_seconds,
    )


def presign_get(key: str | None) -> str | None:
    if not key:
        return None
    return _presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.presign_expiry_seconds,
    )


def upload_file(local_path: str, key: str) -> None:
    _client().upload_file(local_path, settings.s3_bucket, key)


def upload_bytes(data: bytes, key: str, content_type: str = "application/octet-stream") -> None:
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)


def download_file(key: str, local_path: str) -> None:
    _client().download_file(settings.s3_bucket, key, local_path)


def get_bytes(key: str) -> bytes:
    return _client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def object_exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except Exception:
        return False


def delete_prefix(prefix: str) -> int:
    """Hard-delete every object under prefix (retention purge). Returns count deleted."""
    c = _client()
    deleted = 0
    paginator = c.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            c.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": objs})
            deleted += len(objs)
    return deleted
