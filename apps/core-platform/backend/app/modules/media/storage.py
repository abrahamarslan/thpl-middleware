"""Storage abstraction for the media subsystem — ASYNC, FastAPI request path only.

  - LocalStorageProvider  -> disk-backed: local dev / air-gapped fallback
  - S3StorageProvider     -> GarageFS / any S3-compatible backend (aioboto3)

Celery workers use the synchronous counterparts in storage_sync.py — see that
module for why the two are kept separate.

The database never knows WHERE bytes live beyond one word: every media row
carries its own ``disk``. ``MEDIA_STORAGE_DRIVER`` only chooses the disk for
NEW uploads, so flipping it never breaks a URL that was already issued.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

import aioboto3
from botocore.exceptions import ClientError

from app.core.conf import settings
from app.modules.media.storage_common import (
    DISK_GARAGE,
    DISK_LOCAL,
    S3Settings,
    StorageConfigError,
    Visibility,
    is_missing_object,
    resolve_local_path,
    s3_settings,
)


class StorageProvider(Protocol):
    disk: str

    async def save(self, file_bytes: bytes, key: str, content_type: str, *, visibility: Visibility = "public") -> None: ...

    async def read(self, key: str, *, visibility: Visibility = "public") -> bytes: ...

    async def delete(self, key: str, *, visibility: Visibility = "public") -> None: ...

    async def exists(self, key: str, *, visibility: Visibility = "public") -> bool: ...


def public_media_url(media_id: str, variant: str) -> str:
    """The ONLY URL shape ever handed to a client for public media.

    Never a raw bucket URL — that is what makes the design driver-agnostic and
    immune to breakage when MEDIA_STORAGE_DRIVER changes for new uploads.
    """
    base = settings.MEDIA_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/public/m/{media_id}/{variant}"


class LocalStorageProvider:
    disk = DISK_LOCAL

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)

    def _path(self, key: str, visibility: Visibility) -> Path:
        return resolve_local_path(self.base_path, visibility, key)

    async def save(self, file_bytes: bytes, key: str, content_type: str, *, visibility: Visibility = "public") -> None:
        path = self._path(key, visibility)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file_bytes)

        await asyncio.to_thread(_write)

    async def read(self, key: str, *, visibility: Visibility = "public") -> bytes:
        path = self._path(key, visibility)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise FileNotFoundError(key) from None

    async def delete(self, key: str, *, visibility: Visibility = "public") -> None:
        await asyncio.to_thread(self._path(key, visibility).unlink, missing_ok=True)

    async def exists(self, key: str, *, visibility: Visibility = "public") -> bool:
        return await asyncio.to_thread(self._path(key, visibility).is_file)


class S3StorageProvider:
    """Async S3-compatible client (GarageFS / AWS) for the FastAPI request path."""

    disk = DISK_GARAGE

    def __init__(self, cfg: S3Settings):
        self._cfg = cfg
        self._session = aioboto3.Session()

    def _client(self):
        return self._session.client(**self._cfg.client_kwargs())

    async def save(self, file_bytes: bytes, key: str, content_type: str, *, visibility: Visibility = "public") -> None:
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._cfg.bucket(visibility), Key=key, Body=file_bytes, ContentType=content_type,
            )

    async def read(self, key: str, *, visibility: Visibility = "public") -> bytes:
        async with self._client() as s3:
            try:
                resp = await s3.get_object(Bucket=self._cfg.bucket(visibility), Key=key)
            except ClientError as e:
                if is_missing_object(e):
                    raise FileNotFoundError(key) from None
                raise
            async with resp["Body"] as stream:
                return await stream.read()

    async def delete(self, key: str, *, visibility: Visibility = "public") -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._cfg.bucket(visibility), Key=key)

    async def exists(self, key: str, *, visibility: Visibility = "public") -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._cfg.bucket(visibility), Key=key)
                return True
            except ClientError as e:
                if is_missing_object(e):
                    return False
                raise                      # an outage is not "the file is absent"

    async def verify_buckets(self) -> None:
        """HeadBucket on both buckets. Verify, never provision: creating the
        buckets and the key is `manage.sh garage-init`'s job, and creating them
        here would mask a skipped bootstrap with a bucket that has none of the
        intended access policy."""
        async with self._client() as s3:
            for bucket in self._cfg.buckets:
                try:
                    await s3.head_bucket(Bucket=bucket)
                except ClientError as e:
                    code = e.response.get("Error", {}).get("Code", "")
                    raise StorageConfigError(
                        f"S3 bucket {bucket!r} is not usable at {self._cfg.endpoint_url} ({code or e}). "
                        "Run `./manage.sh garage-init` to create the buckets and grant the key."
                    ) from e
                except Exception as e:  # noqa: BLE001 — connection refused, DNS, TLS, …
                    raise StorageConfigError(
                        f"cannot reach S3 endpoint {self._cfg.endpoint_url} while checking {bucket!r}: {e}"
                    ) from e


_provider_cache: dict[str, StorageProvider] = {}


def get_storage_provider(disk: str) -> StorageProvider:
    """Provider for one media row's ``disk`` (cached per process)."""
    if disk not in _provider_cache:
        if disk == DISK_LOCAL:
            _provider_cache[disk] = LocalStorageProvider(settings.MEDIA_LOCAL_BASE_PATH)
        elif disk == DISK_GARAGE:
            _provider_cache[disk] = S3StorageProvider(s3_settings())
        else:
            raise ValueError(f"unknown storage disk: {disk!r}")
    return _provider_cache[disk]


def default_disk() -> str:
    """Disk for NEW uploads — the only thing ``MEDIA_STORAGE_DRIVER`` decides."""
    return settings.MEDIA_STORAGE_DRIVER


async def verify_storage_ready() -> None:
    """Startup check: with the garage driver, both buckets must already exist."""
    if settings.MEDIA_STORAGE_DRIVER != DISK_GARAGE:
        return
    provider = get_storage_provider(DISK_GARAGE)
    await provider.verify_buckets()      # type: ignore[attr-defined]
