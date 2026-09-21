"""Transport tests — the call pipeline, with the gates faked out.

No network, no Redis: `httpx.MockTransport` answers the requests and stub
gates record what the client asked of them. The gates have their own tests.
"""

from contextlib import asynccontextmanager

import httpx
import pytest

from app.modules.zoho.core.breaker import Admission
from app.modules.zoho.core.errors import (
    ZohoAmbiguousOutcome,
    ZohoContractError,
    ZohoNotFoundError,
    ZohoQuotaExhaustedError,
    ZohoTransientError,
    ZohoValidationError,
)
from app.modules.zoho.core.governor import Priority
from app.modules.zoho.core.transport import Api, ZohoClient, ZohoOp


class FakeLease:
    def __init__(self, priority):
        self.priority = priority
        self.sent = False
        self.settled = False

    def mark_sent(self):
        self.sent = True


class FakeGovernor:
    """Records admissions; never refuses (refusal paths are tested in test_governor)."""

    def __init__(self):
        self.leases: list[FakeLease] = []
        self.quota_exhausted_calls: list[str] = []

    @asynccontextmanager
    async def slot(self, priority, **kwargs):
        lease = FakeLease(priority)
        self.leases.append(lease)
        try:
            yield lease
        finally:
            lease.settled = True

    async def mark_quota_exhausted(self, *, reason: str) -> None:
        self.quota_exhausted_calls.append(reason)


class FakeBreaker:
    def __init__(self):
        self.successes: list[tuple[str, float]] = []
        self.failures: list[tuple[str, str]] = []

    async def allow(self, group: str) -> Admission:
        return Admission(group)

    async def record_success(self, admission, *, duration=0.0):
        self.successes.append((admission.group, duration))

    async def record_failure(self, admission, *, category, duration=0.0):
        self.failures.append((admission.group, str(category)))


class FakeTokens:
    def __init__(self):
        self.token = "token-1"
        self.invalidated: list[str] = []

    async def get_token(self) -> str:
        return self.token

    async def invalidate(self, token: str | None = None) -> None:
        self.invalidated.append(token)
        self.token = "token-2"


class OpenSwitches:
    """Every switch on; records what was checked."""

    def __init__(self):
        self.checks: list[tuple[str, str | None, bool]] = []

    async def check(self, *, direction, module, interactive):
        self.checks.append((direction, module, interactive))


def build_client(handler, switches=None):
    """A client whose HTTP layer is `handler`, with stub gates."""
    governor, breaker, tokens = FakeGovernor(), FakeBreaker(), FakeTokens()
    client = ZohoClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        governor=governor, breaker=breaker, token_manager=tokens,
        switches=switches or OpenSwitches(),
    )
    return client, governor, breaker, tokens


def json_response(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers or {})


# ── happy path ──────────────────────────────────────────────────────────────

async def test_successful_call_parses_the_envelope_and_spends_one_call():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["request_id"] = request.headers["X-Request-Id"]
        return json_response(200, {"code": 0, "message": "success", "invoice": {"invoice_id": "42"}})

    client, governor, breaker, _ = build_client(handler)
    response = await client.get("/invoices/42")

    assert response.ok and response.data == {"invoice_id": "42"}
    assert "organization_id=" in seen["url"]          # always scoped to the org
    assert seen["auth"].startswith("Zoho-oauthtoken ")
    assert seen["request_id"]
    assert len(governor.leases) == 1 and governor.leases[0].sent is True
    assert governor.leases[0].settled is True
    assert breaker.successes and not breaker.failures


async def test_inventory_api_uses_its_own_base_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["path"] = request.url.path
        return json_response(200, {"code": 0, "picklists": []})

    client, *_ = build_client(handler)
    await client.request(ZohoOp("GET", "/picklists", api=Api.INVENTORY))
    assert "/inventory/" in seen["path"]


async def test_priority_is_passed_to_the_governor():
    client, governor, *_ = build_client(lambda r: json_response(200, {"code": 0, "items": []}))
    await client.request(ZohoOp("GET", "/items", priority=Priority.INTERACTIVE))
    assert governor.leases[0].priority is Priority.INTERACTIVE


# ── the rule that protects against duplicate records ────────────────────────

async def test_post_is_never_retried_after_a_5xx():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return json_response(500, {"code": 1000, "message": "Internal error"})

    client, governor, breaker, _ = build_client(handler)
    with pytest.raises(ZohoAmbiguousOutcome):
        await client.post("/invoices", json={"customer_id": "1"})

    assert len(calls) == 1                                  # exactly one attempt
    assert governor.leases[0].sent is True                  # …and it counted
    assert breaker.failures[0][1] == "ambiguous"


async def test_post_read_timeout_is_ambiguous_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    client, *_ = build_client(handler)
    with pytest.raises(ZohoAmbiguousOutcome):
        await client.post("/invoices", json={})
    assert len(calls) == 1


async def test_post_connect_error_is_retried_because_nothing_was_sent():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("refused", request=request)
        return json_response(201, {"code": 0, "invoice": {"invoice_id": "9"}})

    client, *_ = build_client(handler)
    response = await client.post("/invoices", json={})
    assert response.ok and len(calls) == 2


async def test_declared_retry_safe_post_is_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return json_response(503, {"code": 1000, "message": "busy"})
        return json_response(200, {"code": 0, "contact": {"contact_id": "7"}})

    client, *_ = build_client(handler)
    response = await client.request(
        ZohoOp("POST", "/contacts", json={}, retry_safe=True)      # X-Upsert style
    )
    assert response.ok and len(calls) == 2


# ── retries, auth, quota ────────────────────────────────────────────────────

async def test_get_retries_transient_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return json_response(502, {"code": 1000, "message": "bad gateway"})
        return json_response(200, {"code": 0, "items": []})

    client, governor, breaker, _ = build_client(handler)
    response = await client.get("/items")
    assert response.ok and len(calls) == 3
    assert len(governor.leases) == 3                     # every attempt costs a call
    assert [c for _, c in breaker.failures] == ["transient", "transient"]


async def test_get_gives_up_after_max_attempts():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return json_response(500, {"code": 1000, "message": "boom"})

    client, *_ = build_client(handler)
    with pytest.raises(ZohoTransientError):
        await client.get("/items")
    assert len(calls) == 4                                # 1 + 3 retries


async def test_401_invalidates_the_token_and_retries_once():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["Authorization"])
        if len(calls) == 1:
            return json_response(401, {"code": 57, "message": "invalid token"})
        return json_response(200, {"code": 0, "items": []})

    client, _, _, tokens = build_client(handler)
    response = await client.get("/items")
    assert response.ok
    assert tokens.invalidated == ["token-1"]              # compare-and-delete target
    assert calls[1].endswith("token-2")


async def test_daily_quota_error_stops_the_engine():
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(429, {"code": 45, "message": "daily limit exceeded"})

    client, governor, breaker, _ = build_client(handler)
    with pytest.raises(ZohoQuotaExhaustedError):
        await client.get("/items")

    assert governor.quota_exhausted_calls == ["zoho_code_45"]
    # The transport reports the outcome; the breaker decides what counts, and
    # quota/throttle categories are not in BREAKER_FAILURE_CATEGORIES.
    assert [c for _, c in breaker.failures] == ["quota_exhausted"]


async def test_rate_limit_honours_retry_after_header():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return json_response(429, {"code": 44, "message": "slow down"}, {"Retry-After": "0"})
        return json_response(200, {"code": 0, "items": []})

    client, _, breaker, _ = build_client(handler)
    response = await client.get("/items")
    assert response.ok and len(calls) == 2
    assert [c for _, c in breaker.failures] == ["rate_limited"]   # reported, not counted


async def test_business_errors_raise_typed_exceptions():
    client, _, breaker, _ = build_client(
        lambda r: json_response(404, {"code": 1002, "message": "Invoice does not exist"})
    )
    with pytest.raises(ZohoNotFoundError) as excinfo:
        await client.get("/invoices/1")
    assert excinfo.value.zoho_code == 1002
    assert excinfo.value.data["path"] == "/invoices/{id}"     # ids templated for logs
    assert [c for _, c in breaker.failures] == ["not_found"]  # reported, never counted

    client, *_ = build_client(lambda r: json_response(400, {"code": 4, "message": "bad payload"}))
    with pytest.raises(ZohoValidationError):
        await client.put("/invoices/1", json={})


# ── pagination: an error is never "end of list" ─────────────────────────────

def paged_handler(pages: list[dict], *, fail_on: int | None = None):
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        page = int(request.url.params.get("page", 1))
        if fail_on is not None and page == fail_on:
            return json_response(500, {"code": 1000, "message": "boom"})
        return json_response(200, pages[page - 1])

    return handler, state


async def test_iter_pages_walks_until_has_more_page_is_false():
    pages = [
        {"code": 0, "items": [{"item_id": "1"}], "page_context": {"page": 1, "per_page": 1, "has_more_page": True}},
        {"code": 0, "items": [{"item_id": "2"}], "page_context": {"page": 2, "per_page": 1, "has_more_page": False}},
    ]
    handler, state = paged_handler(pages)
    client, *_ = build_client(handler)

    collected = [p async for p in client.iter_pages(ZohoOp("GET", "/items"), per_page=1)]
    assert [p.page for p in collected] == [1, 2]
    assert [r["item_id"] for p in collected for r in p.records] == ["1", "2"]
    assert state["n"] == 2                       # no extra "is it empty yet?" request


async def test_iter_pages_raises_mid_scan_instead_of_ending_quietly():
    pages = [
        {"code": 0, "items": [{"item_id": "1"}], "page_context": {"page": 1, "per_page": 1, "has_more_page": True}},
        {},
    ]
    handler, _ = paged_handler(pages, fail_on=2)
    client, *_ = build_client(handler)

    seen = []
    with pytest.raises(ZohoTransientError):
        async for page in client.iter_pages(ZohoOp("GET", "/items"), per_page=1):
            seen.append(page.page)
    assert seen == [1]                           # partial scan, loudly — never "done"


async def test_missing_page_context_is_a_contract_error():
    client, *_ = build_client(lambda r: json_response(200, {"code": 0, "items": []}))
    with pytest.raises(ZohoContractError):
        async for _ in client.iter_pages(ZohoOp("GET", "/items")):
            pass


async def test_max_pages_stops_the_scan_without_an_error():
    pages = [
        {"code": 0, "items": [{"item_id": str(i)}],
         "page_context": {"page": i, "per_page": 1, "has_more_page": True}}
        for i in range(1, 5)
    ]
    handler, state = paged_handler(pages)
    client, *_ = build_client(handler)

    collected = [p async for p in client.iter_pages(ZohoOp("GET", "/items"), per_page=1, max_pages=2)]
    assert len(collected) == 2 and state["n"] == 2


async def test_legacy_paginate_yields_responses_for_the_v1_engine():
    pages = [
        {"code": 0, "organizations": [{"organization_id": "1"}],
         "page_context": {"page": 1, "per_page": 200, "has_more_page": False}},
    ]
    handler, _ = paged_handler(pages)
    client, *_ = build_client(handler)

    responses = [r async for r in client.paginate("/organizations")]
    assert len(responses) == 1 and responses[0].data == [{"organization_id": "1"}]


# ── guards ──────────────────────────────────────────────────────────────────

async def test_oversized_body_is_refused_before_parsing():
    from app.modules.zoho.core import transport as transport_module

    big = "x" * (transport_module.MAX_RESPONSE_BYTES + 10)
    client, *_ = build_client(lambda r: httpx.Response(200, content=big.encode()))
    with pytest.raises(ZohoContractError):
        await client.get("/items")


async def test_non_json_body_becomes_a_typed_error_not_a_crash():
    client, *_ = build_client(lambda r: httpx.Response(200, content=b"<html>maintenance</html>"))
    with pytest.raises(ZohoValidationError):
        await client.get("/items")


# ── switches come first ─────────────────────────────────────────────────────

async def test_switch_refusal_happens_before_any_other_gate():
    from app.modules.zoho.control.switches import ZohoEngineDisabled

    class ClosedSwitches:
        async def check(self, *, direction, module, interactive):
            raise ZohoEngineDisabled("paused", reason="switch:engine_paused")

    calls = []
    client, governor, breaker, _ = build_client(
        lambda r: (calls.append(r), json_response(200, {"code": 0}))[1], switches=ClosedSwitches()
    )
    with pytest.raises(ZohoEngineDisabled):
        await client.get("/items")
    assert calls == [] and governor.leases == [] and breaker.successes == []


async def test_direction_and_module_are_reported_to_the_switches():
    switches = OpenSwitches()
    client, *_ = build_client(lambda r: json_response(200, {"code": 0, "x": {}}), switches=switches)
    await client.get("/items", module="items")
    await client.post("/items", json={}, module="items", priority=Priority.INTERACTIVE)
    assert switches.checks == [("pull", "items", False), ("push", "items", True)]


async def test_client_defaults_apply_to_legacy_helpers():
    client = ZohoClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: json_response(200, {"code": 0, "x": {}}))),
        governor=FakeGovernor(), breaker=FakeBreaker(), token_manager=FakeTokens(),
        switches=OpenSwitches(), default_priority=Priority.RECONCILE, default_module="organizations",
    )
    await client.get("/organizations")
    lease = client._governor.leases[0]
    assert lease.priority is Priority.RECONCILE
