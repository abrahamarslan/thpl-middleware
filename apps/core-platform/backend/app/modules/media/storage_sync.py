"""Synchronous counterparts of storage.py, used ONLY inside Celery tasks.

Celery workers are synchronous prefork processes. Driving the async aioboto3
client from a task means either a fresh ``asyncio.run`` per call — a new event
loop and aiohttp pool for every invocation, and every avatar upload fans out to
several variant round-trips — or sharing the worker's DB loop with an HTTP
client that has different lifetime rules. Plain boto3 keeps ONE client per
worker process, reused across every task the process handles.

Database access from tasks is a separate matter: it goes through the worker's
single event loop (app/tasks/_loop.py, ADR-3) — see repository_worker.py.
"""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.core.conf import settings
from app.modules.media.storage_common import (
    DISK_GARAGE,
    DISK_LOCAL,
    S3Settings,
    Visibility,
    is_missing_object,
    resolve_local_path,
    s3_settings,
)


class LocalStorageProviderSync:
    disk = DISK_LOCAL

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)

    def _path(self, key: str, visibility: Visibility) -> Path:
        return resolve_local_path(self.base_path, visibility, key)

    def save(self, file_bytes: bytes, key: str, content_type: str, *, visibility: Visibility = "public") -> None:
        path = self._path(key, visibility)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_bytes)

    def read(self, key: str, *, visibility: Visibility = "public") -> bytes:
        try:
            return self._path(key, visibility).read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(key) from None

    def delete(self, key: str, *, visibility: Visibility = "public") -> None:
        self._path(key, visibility).unlink(missing_ok=True)

    def exists(self, key: str, *, visibility: Visibility = "public") -> bool:
        return self._path(key, visibility).is_file()


class S3StorageProviderSync:
    disk = DISK_GARAGE

    def __init__(self, cfg: S3Settings):
        self._cfg = cfg
        # ONE client per worker PROCESS (see the factory below), reused by every task.
        self._client = boto3.client(**cfg.client_kwargs())

    def save(self, file_bytes: bytes, key: str, content_type: str, *, visibility: Visibility = "public") -> None:
        self._client.put_object(
            Bucket=self._cfg.bucket(visibility), Key=key, Body=file_bytes, ContentType=content_type,
        )

    def read(self, key: str, *, visibility: Visibility = "public") -> bytes:
        try:
            resp = self._client.get_object(Bucket=self._cfg.bucket(visibility), Key=key)
        except ClientError as e:
            if is_missing_object(e):
                raise FileNotFoundError(key) from None
            raise
        return resp["Body"].read()

    def delete(self, key: str, *, visibility: Visibility = "public") -> None:
        self._client.delete_object(Bucket=self._cfg.bucket(visibility), Key=key)

    def exists(self, key: str, *, visibility: Visibility = "public") -> bool:
        try:
            self._client.head_object(Bucket=self._cfg.bucket(visibility), Key=key)
            return True
        except ClientError as e:
            if is_missing_object(e):
                return False
            raise


_provider_cache: dict[str, object] = {}


def get_storage_provider_sync(disk: str):
    """Provider for one media row's ``disk``, cached per worker process."""
    if disk not in _provider_cache:
        if disk == DISK_LOCAL:
            _provider_cache[disk] = LocalStorageProviderSync(settings.MEDIA_LOCAL_BASE_PATH)
        elif disk == DISK_GARAGE:
            _provider_cache[disk] = S3StorageProviderSync(s3_settings())
        else:
            raise ValueError(f"unknown storage disk: {disk!r}")
    return _provider_cache[disk]
