"""Storage strategy — the database never knows WHERE bytes live.

Swap providers via MEDIA_STORAGE_DRIVER (local | s3); call sites depend only
on the StorageProvider protocol. Local IO runs through asyncio.to_thread so
the event loop never blocks on disk.
"""

import asyncio
from pathlib import Path
from typing import Protocol

from app.core.conf import settings


class StorageProvider(Protocol):
    disk: str

    async def save(self, file_bytes: bytes, filename: str) -> str:
        """Persist bytes; returns the disk name recorded on the Media row."""
        ...

    async def read(self, filename: str) -> bytes: ...

    async def delete(self, filename: str) -> None: ...

    def local_path(self, filename: str) -> Path | None:
        """Filesystem path when the provider is disk-backed (for Pillow)."""
        ...


class LocalStorageProvider:
    disk = "local"

    def __init__(self, base_path: str | None = None) -> None:
        self.base_path = Path(base_path or settings.MEDIA_LOCAL_BASE_PATH)

    def local_path(self, filename: str) -> Path:
        return self.base_path / filename

    async def save(self, file_bytes: bytes, filename: str) -> str:
        def _write() -> None:
            self.base_path.mkdir(parents=True, exist_ok=True)
            (self.base_path / filename).write_bytes(file_bytes)

        await asyncio.to_thread(_write)
        return self.disk

    async def read(self, filename: str) -> bytes:
        return await asyncio.to_thread((self.base_path / filename).read_bytes)

    async def delete(self, filename: str) -> None:
        def _unlink() -> None:
            path = self.base_path / filename
            path.unlink(missing_ok=True)

        await asyncio.to_thread(_unlink)


class S3StorageProvider:
    """Placeholder — wire aioboto3 here when the S3 bucket is provisioned.

    The strategy seam is already in place: implementing these four methods
    and setting MEDIA_STORAGE_DRIVER=s3 migrates the module with zero call-
    site changes.
    """

    disk = "s3"

    def local_path(self, filename: str) -> None:
        return None

    async def save(self, file_bytes: bytes, filename: str) -> str:
        raise NotImplementedError("S3 media storage not configured yet (MEDIA_STORAGE_DRIVER=s3)")

    async def read(self, filename: str) -> bytes:
        raise NotImplementedError("S3 media storage not configured yet")

    async def delete(self, filename: str) -> None:
        raise NotImplementedError("S3 media storage not configured yet")


def get_storage() -> StorageProvider:
    if settings.MEDIA_STORAGE_DRIVER == "s3":
        return S3StorageProvider()
    return LocalStorageProvider()
