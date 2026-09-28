"""Pieces shared by the async (storage.py) and sync (storage_sync.py) providers.

Nothing here does I/O or imports an S3 client, so the Celery worker can import
it without pulling in aioboto3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from botocore.config import Config as BotoConfig

from app.core.conf import settings

Visibility = Literal["public", "private"]

DISK_LOCAL = "local"
DISK_GARAGE = "garage"
DISKS = (DISK_LOCAL, DISK_GARAGE)


class StorageConfigError(RuntimeError):
    """Storage is misconfigured or a required bucket is missing (fail fast at boot)."""


def resolve_local_path(base_path: Path, visibility: Visibility, key: str) -> Path:
    """``<base>/<visibility>/<key>``, refusing anything that escapes ``<base>/<visibility>``.

    Public and private files live in separate directory trees for the same
    reason they live in separate buckets: a bug in one collection's policy must
    not be able to expose the other.
    """
    if visibility not in ("public", "private"):
        raise ValueError(f"unknown visibility: {visibility!r}")
    root = (base_path / visibility).resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError(f"storage key escapes the storage root: {key!r}")
    return path


@dataclass(frozen=True, slots=True)
class S3Settings:
    bucket_public: str
    bucket_private: str
    endpoint_url: str
    access_key: str
    secret_key: str
    region: str

    def bucket(self, visibility: Visibility) -> str:
        return self.bucket_public if visibility == "public" else self.bucket_private

    @property
    def buckets(self) -> tuple[str, str]:
        return self.bucket_public, self.bucket_private

    def client_kwargs(self) -> dict:
        return dict(
            service_name="s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            # Required: Garage serves path-style; virtual-host style needs wildcard DNS.
            config=BotoConfig(s3={"addressing_style": "path"}),
        )


def s3_settings() -> S3Settings:
    cfg = S3Settings(
        bucket_public=settings.S3_BUCKET_PUBLIC,
        bucket_private=settings.S3_BUCKET_PRIVATE,
        endpoint_url=settings.S3_ENDPOINT_URL,
        access_key=settings.S3_ACCESS_KEY_ID,
        secret_key=settings.S3_SECRET_ACCESS_KEY,
        region=settings.S3_REGION,
    )
    missing = [
        name for name, value in (
            ("S3_ENDPOINT_URL", cfg.endpoint_url),
            ("S3_ACCESS_KEY_ID", cfg.access_key),
            ("S3_SECRET_ACCESS_KEY", cfg.secret_key),
            ("S3_BUCKET_PUBLIC", cfg.bucket_public),
            ("S3_BUCKET_PRIVATE", cfg.bucket_private),
        ) if not value
    ]
    if missing:
        raise StorageConfigError(f"garage storage is not configured: set {', '.join(missing)}")
    if cfg.bucket_public == cfg.bucket_private:
        raise StorageConfigError("S3_BUCKET_PUBLIC and S3_BUCKET_PRIVATE must be different buckets")
    return cfg


def is_missing_object(error: Exception) -> bool:
    """A botocore ClientError meaning "no such key" (as opposed to an outage)."""
    response = getattr(error, "response", None) or {}
    code = str(response.get("Error", {}).get("Code", ""))
    return code in ("NoSuchKey", "404", "NotFound")


def content_type_for(ext: str) -> str:
    return {"webp": "image/webp", "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg"}.get(
        ext.lower(), "application/octet-stream"
    )
