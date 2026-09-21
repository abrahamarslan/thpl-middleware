"""Policy tests — the table that decides every retry.

The two rules worth breaking the build over:
  * a POST that was already sent is NEVER retried (duplicate invoices);
  * a 429 is never a circuit-breaker failure (throttling is not an outage).
"""

import random

import httpx
import pytest

from app.modules.zoho.core import policy
from app.modules.zoho.core.errors import (
    BREAKER_FAILURE_CATEGORIES,
    ErrorCategory,
    ZohoTransientError,
    ZohoValidationError,
    normalise_message,
)
from app.modules.zoho.core.policy import Action, Outcome


def out(method="GET", *, retry_safe=None, **kwargs):
    if retry_safe is None:
        retry_safe = policy.is_retry_safe(method)
    return Outcome(method=method, retry_safe=retry_safe, **kwargs)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (out("GET", http_status=500), ErrorCategory.TRANSIENT),
        (out("PUT", http_status=503), ErrorCategory.TRANSIENT),
        (out("DELETE", http_status=502), ErrorCategory.TRANSIENT),
        # POST after the bytes left us: unknown outcome, must be resolved by lookup
        (out("POST", http_status=500), ErrorCategory.AMBIGUOUS),
        (out("POST", http_status=504), ErrorCategory.AMBIGUOUS),
        # ...unless the adapter declared the create idempotent (X-Upsert)
        (out("POST", retry_safe=True, http_status=500), ErrorCategory.TRANSIENT),
        # 429 variants come from Zoho's own code
        (out("GET", http_status=429, zoho_code=44), ErrorCategory.RATE_LIMITED),
        (out("GET", http_status=429, zoho_code=1070), ErrorCategory.RATE_LIMITED),
        (out("GET", http_status=429, zoho_code=45), ErrorCategory.QUOTA_EXHAUSTED),
        (out("POST", http_status=429), ErrorCategory.RATE_LIMITED),   # rejected, nothing created
        (out("GET", http_status=401), ErrorCategory.AUTH),
        (out("GET", http_status=403), ErrorCategory.FORBIDDEN),
        (out("GET", http_status=404), ErrorCategory.NOT_FOUND),
        (out("GET", http_status=405), ErrorCategory.BUG),
        (out("POST", http_status=400), ErrorCategory.VALIDATION),
        (out("GET", http_status=200, zoho_code=1002), ErrorCategory.NOT_FOUND),
        (out("GET", http_status=200, zoho_code=1000), ErrorCategory.TRANSIENT),
        # transport failures
        (out("POST", exception=httpx.ConnectError("refused"), sent=False), ErrorCategory.TRANSIENT),
        (out("POST", exception=httpx.ConnectTimeout("t")), ErrorCategory.TRANSIENT),
        (out("POST", exception=httpx.PoolTimeout("t")), ErrorCategory.TRANSIENT),
        (out("POST", exception=httpx.ReadTimeout("t")), ErrorCategory.AMBIGUOUS),
        (out("GET", exception=httpx.ReadTimeout("t")), ErrorCategory.TRANSIENT),
        (out("PUT", exception=httpx.RemoteProtocolError("t")), ErrorCategory.TRANSIENT),
    ],
)
def test_classify(outcome, expected):
    assert policy.classify(outcome) is expected


def test_post_is_not_retry_safe_by_default():
    assert policy.is_retry_safe("POST") is False
    assert policy.is_retry_safe("PUT") is True
    assert policy.is_retry_safe("DELETE") is True
    assert policy.is_retry_safe("GET") is True
    assert policy.is_retry_safe("POST", declared=True) is True


def test_ambiguous_is_never_retried_by_the_client():
    decision = policy.decide(
        out("POST", http_status=500), attempt=1, elapsed=0.0, deadline=30.0
    )
    assert decision.action is Action.RAISE
    assert decision.category is ErrorCategory.AMBIGUOUS


def test_transient_retries_then_gives_up():
    first = policy.decide(out("GET", http_status=500), attempt=1, elapsed=0.0, deadline=30.0)
    assert first.action is Action.RETRY and 0 <= first.delay <= policy.BACKOFF_BASE_SECONDS

    last = policy.decide(
        out("GET", http_status=500), attempt=policy.MAX_ATTEMPTS, elapsed=1.0, deadline=30.0
    )
    assert last.action is Action.RAISE and last.reason == "attempts_exhausted"


def test_retry_after_is_honoured_when_it_fits_the_deadline():
    fits = policy.decide(
        out("GET", http_status=429, zoho_code=44), attempt=1, elapsed=0.0, deadline=30.0,
        retry_after=5.0,
    )
    assert fits.action is Action.RETRY and fits.delay == 5.0

    too_long = policy.decide(
        out("GET", http_status=429, zoho_code=44), attempt=1, elapsed=0.0, deadline=3.0,
        retry_after=120.0,
    )
    assert too_long.action is Action.RAISE and too_long.reason == "deadline_exceeded"


def test_quota_exhausted_is_never_retried_in_the_client():
    decision = policy.decide(
        out("GET", http_status=429, zoho_code=45), attempt=1, elapsed=0.0, deadline=30.0
    )
    assert decision.action is Action.RAISE
    assert decision.category is ErrorCategory.QUOTA_EXHAUSTED


def test_401_retries_once_with_a_new_token():
    first = policy.decide(out("GET", http_status=401), attempt=1, elapsed=0.0, deadline=30.0)
    assert first.action is Action.RETRY_WITH_NEW_TOKEN

    second = policy.decide(
        out("GET", http_status=401, token_retried=True), attempt=2, elapsed=0.1, deadline=30.0
    )
    assert second.action is Action.RAISE


def test_429_does_not_trip_the_breaker():
    assert ErrorCategory.RATE_LIMITED not in BREAKER_FAILURE_CATEGORIES
    assert ErrorCategory.QUOTA_EXHAUSTED not in BREAKER_FAILURE_CATEGORIES
    assert ErrorCategory.VALIDATION not in BREAKER_FAILURE_CATEGORIES
    assert ErrorCategory.TRANSIENT in BREAKER_FAILURE_CATEGORIES


def test_backoff_is_bounded_and_jittered():
    rng = random.Random(7)
    values = [policy.backoff(attempt, rng=rng) for attempt in range(1, 8)]
    assert all(0.0 <= v <= policy.BACKOFF_CAP_SECONDS for v in values)
    assert len(set(values)) > 1          # jitter, not a fixed ladder


def test_parse_retry_after():
    assert policy.parse_retry_after("12") == 12.0
    assert policy.parse_retry_after(None) is None
    assert policy.parse_retry_after("soon") is None


def test_error_fingerprints_group_similar_failures():
    a = ZohoValidationError("Invoice 982000000567114 does not exist", http_status=400)
    b = ZohoValidationError("Invoice 982000000567115 does not exist", http_status=400)
    c = ZohoValidationError("Customer name is required", http_status=400)
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != c.fingerprint()
    assert normalise_message("Invoice 982000000567114 is 5 days overdue") == "invoice <id> is <n> days overdue"


def test_error_flags_follow_the_category():
    assert ZohoTransientError("boom").retryable is True
    assert ZohoTransientError("boom").counts_for_breaker is True
    assert ZohoValidationError("bad").retryable is False
    assert ZohoValidationError("bad").log_fields()["error_category"] == "validation"
