"""Storage providers: local and Garage behave identically, sync and async.

The Garage half needs a real S3 endpoint and is skipped unless one is provided
(the bucket names are created by `manage.sh garage-init`):

    TEST_GARAGE_ENDPOINT=http://localhost:3900
    TEST_GARAGE_ACCESS_KEY=GK…   TEST_GARAGE_SECRET_KEY=…
    [TEST_GARAGE_BUCKET_PUBLIC / TEST_GARAGE_BUCKET_PRIVATE]
"""

import os
import uuid

import pytest

from app.core.conf import Settings
from app.modules.media import storage, storage_common, storage_sync
from app.modules.media.storage import LocalStorageProvider, S3StorageProvider, public_media_url
from app.modules.media.storage_common import S3Settings, StorageConfigError, resolve_local_path, s3_settings
from app.modules.media.storage_sync import LocalStorageProviderSync, S3StorageProviderSync

GARAGE = os.environ.get("TEST_GARAGE_ENDPOINT")


def _garage_cfg() -> S3Settings:
    return S3Settings(
        bucket_public=os.environ.get("TEST_GARAGE_BUCKET_PUBLIC", "core-platform-media-public"),
        bucket_private=os.environ.get("TEST_GARAGE_BUCKET_PRIVATE", "core-platform-media-private"),
        endpoint_url=GARAGE or "",
        access_key=os.environ.get("TEST_GARAGE_ACCESS_KEY", ""),
        secret_key=os.environ.get("TEST_GARAGE_SECRET_KEY", ""),
        region="garage",
    )


@pytest.fixture(params=["local", pytest.param("garage", marks=pytest.mark.skipif(not GARAGE, reason="no TEST_GARAGE_ENDPOINT"))])
def async_provider(request, tmp_path):
    if request.param == "local":
        return LocalStorageProvider(tmp_path)
    return S3StorageProvider(_garage_cfg())


@pytest.fixture(params=["local", pytest.param("garage", marks=pytest.mark.skipif(not GARAGE, reason="no TEST_GARAGE_ENDPOINT"))])
def sync_provider(request, tmp_path):
    if request.param == "local":
        return LocalStorageProviderSync(tmp_path)
    return S3StorageProviderSync(_garage_cfg())


def _key(name="original.png") -> str:
    return f"{uuid.uuid4()}/{name}"          # unique per test: the Garage buckets are shared


# ── async (FastAPI path) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_async_round_trip(async_provider, visibility):
    key = _key()
    assert not await async_provider.exists(key, visibility=visibility)

    await async_provider.save(b"\x89PNG-bytes", key, "image/png", visibility=visibility)

    assert await async_provider.exists(key, visibility=visibility)
    assert await async_provider.read(key, visibility=visibility) == b"\x89PNG-bytes"

    await async_provider.delete(key, visibility=visibility)
    assert not await async_provider.exists(key, visibility=visibility)


async def test_async_missing_key_is_file_not_found_on_every_backend(async_provider):
    with pytest.raises(FileNotFoundError):
        await async_provider.read(_key("nope.webp"), visibility="public")


async def test_async_delete_of_a_missing_key_is_a_noop(async_provider):
    await async_provider.delete(_key("never-existed.webp"), visibility="public")


async def test_public_and_private_are_physically_separate(async_provider):
    key = _key()
    await async_provider.save(b"secret", key, "image/png", visibility="private")
    assert not await async_provider.exists(key, visibility="public")     # other bucket / directory
    with pytest.raises(FileNotFoundError):
        await async_provider.read(key, visibility="public")
    await async_provider.delete(key, visibility="private")


async def test_async_overwrite_replaces_the_bytes(async_provider):
    key = _key()
    await async_provider.save(b"one", key, "image/png")
    await async_provider.save(b"two", key, "image/png")
    assert await async_provider.read(key) == b"two"
    await async_provider.delete(key)


# ── sync (Celery path) ───────────────────────────────────────────────────────

@pytest.mark.parametrize("visibility", ["public", "private"])
def test_sync_round_trip(sync_provider, visibility):
    key = _key()
    assert not sync_provider.exists(key, visibility=visibility)
    sync_provider.save(b"abc", key, "image/webp", visibility=visibility)
    assert sync_provider.exists(key, visibility=visibility)
    assert sync_provider.read(key, visibility=visibility) == b"abc"
    sync_provider.delete(key, visibility=visibility)
    assert not sync_provider.exists(key, visibility=visibility)


def test_sync_missing_key_is_file_not_found(sync_provider):
    with pytest.raises(FileNotFoundError):
        sync_provider.read(_key("nope.webp"))


async def test_sync_and_async_see_the_same_bytes(tmp_path):
    """The API writes with one client and the worker reads with another."""
    key = _key()
    await LocalStorageProvider(tmp_path).save(b"api-wrote-this", key, "image/png")
    assert LocalStorageProviderSync(tmp_path).read(key) == b"api-wrote-this"


@pytest.mark.skipif(not GARAGE, reason="no TEST_GARAGE_ENDPOINT")
async def test_sync_and_async_garage_clients_interoperate():
    key = _key()
    await S3StorageProvider(_garage_cfg()).save(b"api-wrote-this", key, "image/png")
    sync = S3StorageProviderSync(_garage_cfg())
    assert sync.read(key) == b"api-wrote-this"
    sync.delete(key)


@pytest.mark.skipif(not GARAGE, reason="no TEST_GARAGE_ENDPOINT")
async def test_garage_content_type_is_stored():
    key = _key("medium.webp")
    provider = S3StorageProviderSync(_garage_cfg())
    provider.save(b"x", key, "image/webp")
    head = provider._client.head_object(Bucket=_garage_cfg().bucket_public, Key=key)
    assert head["ContentType"] == "image/webp"
    provider.delete(key)


# ── local path safety ────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["../escape.png", "a/../../escape.png", "/etc/passwd", "..", ""])
def test_local_keys_cannot_escape_the_storage_root(tmp_path, key):
    with pytest.raises(ValueError):
        resolve_local_path(tmp_path, "public", key)


def test_local_paths_are_namespaced_by_visibility(tmp_path):
    assert resolve_local_path(tmp_path, "public", "x/y.png") == (tmp_path / "public" / "x" / "y.png").resolve()
    assert resolve_local_path(tmp_path, "private", "x/y.png") == (tmp_path / "private" / "x" / "y.png").resolve()
    with pytest.raises(ValueError):
        resolve_local_path(tmp_path, "public-ish", "x.png")           # type: ignore[arg-type]


async def test_local_provider_refuses_a_traversal_key(tmp_path):
    provider = LocalStorageProvider(tmp_path)
    with pytest.raises(ValueError):
        await provider.save(b"x", "../../boom.png", "image/png")
    assert not (tmp_path.parent / "boom.png").exists()


# ── configuration ────────────────────────────────────────────────────────────

def test_public_media_url_is_never_a_bucket_url(monkeypatch):
    monkeypatch.setattr(storage.settings, "MEDIA_PUBLIC_BASE_URL", "https://dlp.example.com/")
    assert public_media_url("abc", "medium") == "https://dlp.example.com/public/m/abc/medium"
    monkeypatch.setattr(storage.settings, "MEDIA_PUBLIC_BASE_URL", "")
    assert public_media_url("abc", "original") == "/public/m/abc/original"


def test_garage_config_must_be_complete(monkeypatch):
    monkeypatch.setattr(storage_common.settings, "S3_ACCESS_KEY_ID", "")
    with pytest.raises(StorageConfigError, match="S3_ACCESS_KEY_ID"):
        s3_settings()


def test_public_and_private_buckets_must_differ(monkeypatch):
    for name, value in (("S3_ACCESS_KEY_ID", "k"), ("S3_SECRET_ACCESS_KEY", "s"),
                        ("S3_BUCKET_PUBLIC", "same"), ("S3_BUCKET_PRIVATE", "same")):
        monkeypatch.setattr(storage_common.settings, name, value)
    with pytest.raises(StorageConfigError, match="different buckets"):
        s3_settings()


def test_unknown_disk_is_rejected():
    with pytest.raises(ValueError):
        storage.get_storage_provider("floppy")
    with pytest.raises(ValueError):
        storage_sync.get_storage_provider_sync("floppy")


@pytest.mark.parametrize(("raw", "expected"), [("local", "local"), ("garage", "garage"), ("s3", "garage"),
                                               ("GARAGE", "garage"), ("", "local")])
def test_driver_setting_is_normalised(raw, expected):
    assert Settings(MEDIA_STORAGE_DRIVER=raw).MEDIA_STORAGE_DRIVER == expected


def test_a_typo_in_the_driver_stops_the_app_at_boot():
    with pytest.raises(ValueError, match="MEDIA_STORAGE_DRIVER"):
        Settings(MEDIA_STORAGE_DRIVER="minio")


async def test_boot_check_is_a_noop_for_the_local_driver(monkeypatch):
    monkeypatch.setattr(storage.settings, "MEDIA_STORAGE_DRIVER", "local")
    await storage.verify_storage_ready()          # must not try to reach any endpoint


@pytest.mark.skipif(not GARAGE, reason="no TEST_GARAGE_ENDPOINT")
async def test_boot_check_passes_when_both_buckets_exist():
    await S3StorageProvider(_garage_cfg()).verify_buckets()


@pytest.mark.skipif(not GARAGE, reason="no TEST_GARAGE_ENDPOINT")
async def test_boot_check_fails_fast_naming_the_missing_bucket_and_the_fix():
    cfg = _garage_cfg()
    broken = S3Settings(
        bucket_public=cfg.bucket_public, bucket_private="bucket-nobody-created",
        endpoint_url=cfg.endpoint_url, access_key=cfg.access_key, secret_key=cfg.secret_key, region=cfg.region,
    )
    with pytest.raises(StorageConfigError) as err:
        await S3StorageProvider(broken).verify_buckets()
    assert "bucket-nobody-created" in str(err.value)
    assert "garage-init" in str(err.value)


async def test_boot_check_reports_an_unreachable_endpoint():
    cfg = S3Settings(bucket_public="a", bucket_private="b", endpoint_url="http://127.0.0.1:9",
                     access_key="k", secret_key="s", region="garage")
    with pytest.raises(StorageConfigError, match="cannot reach"):
        await S3StorageProvider(cfg).verify_buckets()
