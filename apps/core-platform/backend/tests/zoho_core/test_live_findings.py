"""Fixes for what the first live run against the Tarrina Health org showed (ERRORS E33–E35)."""

import httpx
import pytest
from sqlalchemy import text

from app.core.conf import settings
from app.modules.zoho.core.errors import ErrorCategory, ZohoForbiddenError, error_for
from app.modules.zoho.core.transport import ZohoClient
from app.modules.zoho.sync.mapper import TRANSFORMS

# ── E34: fiscal_year_start_month arrives as a month name ────────────────────

@pytest.mark.parametrize(("raw", "expected"), [
    ("april", 3), ("April", 3), ("apr", 3), ("january", 0), ("december", 11), (3, 3), ("3", 3),
    (12, None), ("smarch", None), (True, None),
])
def test_month_index(raw, expected):
    assert TRANSFORMS["month_index"](raw) == expected


# ── E35: code 6041 is a configuration error with a hint ─────────────────────

def test_wrong_org_id_is_forbidden_with_an_actionable_hint():
    from app.modules.zoho.core.policy import Outcome, classify

    category = classify(Outcome(method="GET", retry_safe=True, http_status=400, zoho_code=6041))
    assert category is ErrorCategory.FORBIDDEN                    # never retried, not "validation"
    error = error_for(category, "This user is not associated with the CompanyID/CompanyName:60059694101.",
                      zoho_code=6041)
    assert isinstance(error, ZohoForbiddenError)
    assert "ZOHO_ORGANIZATION_ID" in error.msg and "cli check --live" in error.msg


# ── opt-in request/response logging ─────────────────────────────────────────

class _Open:
    async def check(self, **_):
        return None


class _Tokens:
    async def get_token(self):
        return "secret-token"

    async def invalidate(self, token=None):
        pass


class _Gov:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def slot(self, priority, **kwargs):
        class Lease:
            def mark_sent(self):
                pass

        yield Lease()

    async def mark_quota_exhausted(self, **_):
        pass


class _Breaker:
    async def allow(self, group):
        from app.modules.zoho.core.breaker import Admission

        return Admission(group)

    async def record_success(self, *a, **k):
        pass

    async def record_failure(self, *a, **k):
        pass


def _client(handler):
    return ZohoClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)), governor=_Gov(),
                      breaker=_Breaker(), token_manager=_Tokens(), switches=_Open())


async def test_http_exchange_is_logged_only_when_enabled_and_never_the_token(monkeypatch, capsys):
    from structlog.testing import capture_logs

    def handler(request):
        return httpx.Response(200, json={"code": 0, "message": "success", "taxes": [{"tax_id": "1"}],
                                         "page_context": {"page": 1, "has_more_page": False}})

    with capture_logs() as quiet:
        await _client(handler).get("/settings/taxes")
    assert not [e for e in quiet if e["event"] == "zoho.transport.http_exchange"]

    monkeypatch.setattr(settings, "ZOHO_HTTP_LOG_BODIES", True)
    monkeypatch.setattr(settings, "ZOHO_HTTP_LOG_BODY_MAX", 40)
    with capture_logs() as logs:
        await _client(handler).get("/settings/taxes", params={"page": 1})
    exchange = next(e for e in logs if e["event"] == "zoho.transport.http_exchange")
    assert exchange["url"].endswith("/settings/taxes") and exchange["query"]["page"] == "1"
    assert exchange["http_status"] == 200 and len(exchange["response_body"]) == 40
    assert "secret-token" not in repr(exchange)


# ── E35: the credential survives an org-id correction ───────────────────────

async def test_credential_stored_under_the_old_org_is_still_used(db, monkeypatch):
    from app.modules.zoho.core.auth import CredentialStore

    monkeypatch.setattr(settings, "ZOHO_TOKEN_PERSISTENCE_ENABLED", True)
    monkeypatch.setattr(settings, "ZOHO_TOKEN_ENCRYPTION_KEY", "k" * 40)
    monkeypatch.setattr(settings, "ZOHO_ORGANIZATION_ID", "60059694101")   # the wrong id used at connect time
    from sqlalchemy.ext.asyncio import async_sessionmaker

    store = CredentialStore(session_factory=async_sessionmaker(db.bind, expire_on_commit=False))
    await store.store("1000.refresh-from-consent")

    monkeypatch.setattr(settings, "ZOHO_ORGANIZATION_ID", "60015628348")   # corrected in .env
    store.invalidate_cache()
    assert (await store.load()).refresh_token == "1000.refresh-from-consent"   # no re-consent needed
    assert (await db.execute(text("SELECT count(*) FROM zoho_oauth_credentials"))).scalar() == 1
