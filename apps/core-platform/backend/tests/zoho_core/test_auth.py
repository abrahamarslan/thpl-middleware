"""Token manager v2 — single-flight refresh and credential safety.

Zoho allows 10 access tokens per refresh token per 10 minutes and keeps only
15 alive, so a refresh stampede does not merely waste calls: it invalidates
tokens other workers are using. These tests pin that behaviour.
"""

import asyncio
import uuid

import httpx
import pytest

from app.core.conf import settings
from app.modules.zoho.core.auth import (
    Credential,
    CredentialStore,
    CredentialUnavailable,
    ZohoTokenManager,
)
from app.modules.zoho.core.errors import ZohoAuthRevokedError, ZohoAuthThrottledError


class StubStore(CredentialStore):
    """A credential store that never touches the database."""

    def __init__(self, token: str = "refresh-abc"):
        super().__init__()
        self._cached = Credential(token, source="test")
        self.stored: list[str] = []

    async def load(self) -> Credential:
        if self._cached is None:
            raise CredentialUnavailable("no credential")
        return self._cached

    async def store(self, refresh_token, **kwargs):
        self.stored.append(refresh_token)
        self._cached = Credential(refresh_token, source="test")

    async def revoke(self) -> None:
        self._cached = None


def token_response(access="access-1", *, expires_in=3600, **extra):
    return httpx.Response(200, json={"access_token": access, "expires_in": expires_in, **extra})


def make_manager(redis, handler, store: CredentialStore | None = None) -> ZohoTokenManager:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return ZohoTokenManager(store=store or StubStore(), redis=redis, http_client_factory=factory)


@pytest.fixture(autouse=True)
def isolated_org(monkeypatch):
    """Each test gets its own Redis key namespace."""
    monkeypatch.setattr(settings, "ZOHO_ORGANIZATION_ID", f"test{uuid.uuid4().hex[:8]}")


@pytest.fixture
async def redis(redis_available):
    yield redis_available


# ── refresh & caching ───────────────────────────────────────────────────────

async def test_token_is_fetched_once_and_then_cached(redis):
    calls = []
    manager = make_manager(redis, lambda r: (calls.append(r), token_response())[1])

    assert await manager.get_token() == "access-1"
    assert await manager.get_token() == "access-1"
    assert len(calls) == 1                      # second call served from Redis


async def test_refresh_is_single_flight_under_a_stampede(redis):
    calls = []

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await asyncio.sleep(0.2)                # long enough for everyone to pile up
        return token_response()

    manager = make_manager(redis, slow_handler)
    tokens = await asyncio.gather(*(manager.get_token() for _ in range(25)))

    assert tokens == ["access-1"] * 25
    assert len(calls) == 1                      # ONE refresh for the whole fleet


async def test_expiry_margin_is_applied_to_the_cache_ttl(redis, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_TOKEN_REFRESH_MARGIN", 120)
    manager = make_manager(redis, lambda r: token_response(expires_in=3600))
    await manager.get_token()

    health = await manager.health()
    assert 3400 < health["token_ttl_seconds"] <= 3480     # 3600 − 120
    assert health["has_token"] is True


# ── invalidation ────────────────────────────────────────────────────────────

async def test_invalidate_only_removes_the_token_it_was_given(redis):
    manager = make_manager(redis, lambda r: token_response("access-fresh"))
    await manager.get_token()

    await manager.invalidate("access-stale")              # a late 401 from an old token
    assert (await manager.health())["has_token"] is True  # the fresh token survived

    await manager.invalidate("access-fresh")
    assert (await manager.health())["has_token"] is False


# ── throttle & revocation ───────────────────────────────────────────────────

async def test_refresh_throttle_fails_loudly_before_zoho_locks_us_out(redis):
    manager = make_manager(redis, lambda r: token_response())
    for _ in range(8):                                    # limit is 8 per 10 minutes
        await manager.get_token()
        await manager.invalidate()

    with pytest.raises(ZohoAuthThrottledError):
        await manager.get_token()


async def test_revoked_refresh_token_raises_auth_revoked(redis):
    store = StubStore()
    manager = make_manager(
        redis,
        lambda r: httpx.Response(200, json={"error": "invalid_code"}),
        store=store,
    )
    from app.modules.zoho.control.switches import zoho_switches

    try:
        with pytest.raises(ZohoAuthRevokedError) as excinfo:
            await manager.get_token()
        assert excinfo.value.data["zoho_error"] == "invalid_code"
        assert excinfo.value.category == "auth_revoked"
        # the whole engine is now paused until someone reconnects
        zoho_switches.invalidate()
        state = await zoho_switches.snapshot()
        assert state.auth_paused is True
        assert state.auth_paused_reason == "refresh_token_invalid_code"
    finally:
        await zoho_switches.clear_auth_paused()


async def test_rotated_refresh_token_is_persisted(redis):
    store = StubStore("refresh-old")
    manager = make_manager(
        redis, lambda r: token_response(refresh_token="refresh-new"), store=store
    )
    await manager.get_token()
    assert store.stored == ["refresh-new"]


async def test_missing_credential_is_an_explicit_error(redis):
    store = StubStore()
    await store.revoke()
    manager = make_manager(redis, lambda r: token_response(), store=store)
    with pytest.raises(CredentialUnavailable):
        await manager.get_token()


async def test_clear_tokens_disconnects(redis):
    store = StubStore()
    manager = make_manager(redis, lambda r: token_response(), store=store)
    await manager.get_token()

    await manager.clear_tokens()
    assert (await manager.health())["has_token"] is False
    assert await manager.get_refresh_token() is None


# ── credential store ────────────────────────────────────────────────────────

async def test_store_falls_back_to_the_environment_seed(monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_TOKEN_PERSISTENCE_ENABLED", False)
    monkeypatch.setattr(settings, "ZOHO_REFRESH_TOKEN", "env-refresh-token")

    credential = await CredentialStore(cache_ttl=0).load()
    assert credential.refresh_token == "env-refresh-token"
    assert credential.source == "environment"


async def test_store_refuses_to_persist_without_an_encryption_key(monkeypatch):
    """Better an in-memory credential than a plaintext secret in the database."""
    monkeypatch.setattr(settings, "ZOHO_TOKEN_PERSISTENCE_ENABLED", True)
    monkeypatch.setattr(settings, "ZOHO_TOKEN_ENCRYPTION_KEY", "")

    store = CredentialStore()
    assert store.db_enabled is False
    await store.store("secret-token")
    assert (await store.load()).source == "environment"


async def test_encrypted_round_trip_through_postgres(db, monkeypatch):
    """The refresh token is stored encrypted and read back through pgcrypto."""
    monkeypatch.setattr(settings, "ZOHO_TOKEN_PERSISTENCE_ENABLED", True)
    monkeypatch.setattr(settings, "ZOHO_TOKEN_ENCRYPTION_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "ZOHO_ORGANIZATION_ID", f"org{uuid.uuid4().hex[:8]}")

    # The store must use THIS test's engine: the module-level factory is pooled
    # and its connections belong to whichever event loop created them.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    store = CredentialStore(cache_ttl=0, session_factory=async_sessionmaker(db.bind, expire_on_commit=False))
    await store.store("refresh-secret-value", api_domain="https://www.zohoapis.in", actor_id=1)

    loaded = await store.load()
    assert loaded.refresh_token == "refresh-secret-value"
    assert loaded.source == "database"

    from sqlalchemy import text

    row = (
        await db.execute(
            text("SELECT refresh_token_enc, credential_version FROM zoho_oauth_credentials "
                 "WHERE org_id = :org"),
            {"org": settings.ZOHO_ORGANIZATION_ID},
        )
    ).mappings().first()
    assert row is not None
    assert b"refresh-secret-value" not in bytes(row["refresh_token_enc"])   # ciphertext at rest
    assert row["credential_version"] == 1

    await store.store("refresh-rotated", actor_id=2)
    assert (await store.load()).refresh_token == "refresh-rotated"
