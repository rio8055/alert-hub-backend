"""Cloudflare R2 (S3-compatible). When credentials are unset, helpers no-op and the app uses local disk only."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings

SESSION_FILE_DIR = Path("telegram_sessions")


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url.rstrip("/"),
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def media_key(relative_under_media: str) -> str:
    """Build object key: media/<path> (path uses forward slashes, no leading slash)."""
    rel = relative_under_media.replace("\\", "/").lstrip("/")
    return f"media/{rel}"


def session_object_key(session_name: str) -> str:
    return f"telegram_sessions/{session_name}.session"


def session_file_path(session_name: str) -> Path:
    return SESSION_FILE_DIR / f"{session_name}.session"


def _put_object_sync(key: str, body: bytes, content_type: str | None) -> None:
    kw: dict = {"Bucket": settings.r2_bucket_name, "Key": key, "Body": body}
    if content_type:
        kw["ContentType"] = content_type
    _s3_client().put_object(**kw)


def _get_object_bytes_sync(key: str) -> bytes | None:
    try:
        obj = _s3_client().get_object(Bucket=settings.r2_bucket_name, Key=key)
        return obj["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        raise


def _head_last_modified_sync(key: str) -> float | None:
    try:
        resp = _s3_client().head_object(Bucket=settings.r2_bucket_name, Key=key)
        lm = resp.get("LastModified")
        return float(lm.timestamp()) if lm is not None else None
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


async def r2_put_media(relative_under_media: str, data: bytes, content_type: str | None = None) -> None:
    if not settings.r2_enabled:
        return
    key = media_key(relative_under_media)
    ct = content_type or mimetypes.guess_type(relative_under_media)[0]
    await asyncio.to_thread(_put_object_sync, key, data, ct)


async def r2_get_media_bytes(relative_under_media: str) -> bytes | None:
    if not settings.r2_enabled:
        return None
    key = media_key(relative_under_media)
    return await asyncio.to_thread(_get_object_bytes_sync, key)


async def r2_head_media_last_modified(relative_under_media: str) -> float | None:
    if not settings.r2_enabled:
        return None
    key = media_key(relative_under_media)
    return await asyncio.to_thread(_head_last_modified_sync, key)


async def ensure_telegram_session_from_r2(session_name: str) -> None:
    """If R2 is enabled and local .session is missing, download it from R2."""
    if not settings.r2_enabled:
        return
    local = session_file_path(session_name)
    if local.exists() and local.stat().st_size > 0:
        return
    key = session_object_key(session_name)
    data = await asyncio.to_thread(_get_object_bytes_sync, key)
    if not data:
        return
    SESSION_FILE_DIR.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)


async def push_telegram_session_to_r2(session_name: str) -> None:
    """Upload local Telethon .session file to R2 (call after disconnect so SQLite is flushed)."""
    if not settings.r2_enabled:
        return
    local = session_file_path(session_name)
    if not local.exists() or local.stat().st_size == 0:
        return
    key = session_object_key(session_name)
    body = local.read_bytes()
    await asyncio.to_thread(_put_object_sync, key, body, "application/octet-stream")
