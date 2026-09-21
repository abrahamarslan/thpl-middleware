"""Zoho error model — every failure carries a category, and the category decides.

Doctrine (docs/zoho-sync-platform-architecture.md §12):
  - Callers never branch on HTTP status codes or Zoho's numeric codes; they
    branch on ``ErrorCategory``. Classification happens exactly once, in
    ``policy.classify()``.
  - Every exception subclasses the application's ``UpstreamError``, so the
    global handlers translate it into the standard envelope with no extra
    wiring.
  - ``fingerprint()`` is the stable grouping key used by logs, metrics,
    alerts and the dead-letter triage UI: two "Invoice 9549…150 does not
    exist" / "…151 does not exist" failures group together.
  - Retry semantics live in the category, not in the call site: ``retryable``
    means "a later attempt may succeed"; ``AMBIGUOUS`` means "we do not know
    whether Zoho applied the write" and must be resolved by a lookup, never
    by a blind retry.

The legacy module ``app.modules.zoho.core.exceptions`` re-exports these names
so existing imports keep working during the migration.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Any

from app.common.exception.errors import UpstreamError


class ErrorCategory(StrEnum):
    """What kind of failure this is — drives retry, logging level and metrics."""

    TRANSIENT = "transient"              # may succeed later; safe to retry
    RATE_LIMITED = "rate_limited"        # Zoho 429 (code 44/1070) or our own budget
    QUOTA_EXHAUSTED = "quota_exhausted"  # Zoho 429 code 45 / our daily ceiling
    CIRCUIT_OPEN = "circuit_open"        # local breaker refused the call
    AUTH = "auth"                        # token problem, recoverable
    AUTH_REVOKED = "auth_revoked"        # refresh token gone — human action needed
    AMBIGUOUS = "ambiguous"              # write sent, outcome unknown — resolve, don't retry
    NOT_FOUND = "not_found"              # 404 / Zoho code 1002
    VALIDATION = "validation"            # 400 / business rule — retrying cannot help
    CONFLICT = "conflict"                # remote changed under us
    FORBIDDEN = "forbidden"              # 403 — scope/permission problem
    CONTRACT = "contract"                # response did not match the documented shape
    BUG = "bug"                          # anything we failed to classify


#: Categories a later attempt may resolve on its own.
RETRYABLE_CATEGORIES: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.TRANSIENT,
        ErrorCategory.RATE_LIMITED,
        ErrorCategory.CIRCUIT_OPEN,
        ErrorCategory.AUTH,
    }
)

#: Categories that count as "Zoho is unhealthy" for the circuit breaker.
#: 429s are deliberately excluded — throttling is normal traffic shaping and
#: must never open the circuit (v3 finding P2).
BREAKER_FAILURE_CATEGORIES: frozenset[ErrorCategory] = frozenset(
    {ErrorCategory.TRANSIENT, ErrorCategory.AMBIGUOUS}
)

#: Log level each category is reported at when it becomes terminal.
CATEGORY_LOG_LEVEL: dict[ErrorCategory, str] = {
    ErrorCategory.TRANSIENT: "warning",
    ErrorCategory.RATE_LIMITED: "info",
    ErrorCategory.QUOTA_EXHAUSTED: "critical",
    ErrorCategory.CIRCUIT_OPEN: "info",
    ErrorCategory.AUTH: "error",
    ErrorCategory.AUTH_REVOKED: "critical",
    ErrorCategory.AMBIGUOUS: "warning",
    ErrorCategory.NOT_FOUND: "info",
    ErrorCategory.VALIDATION: "error",
    ErrorCategory.CONFLICT: "warning",
    ErrorCategory.FORBIDDEN: "error",
    ErrorCategory.CONTRACT: "error",
    ErrorCategory.BUG: "error",
}

_ID_PATTERN = re.compile(r"\b\d{6,}\b")          # Zoho ids are long digit runs
_NUM_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")  # remaining numbers
_QUOTED_PATTERN = re.compile(r"'[^']*'|\"[^\"]*\"")


def normalise_message(message: str) -> str:
    """Strip ids, numbers and quoted values so similar failures group together."""
    text = _QUOTED_PATTERN.sub("'?'", message or "")
    text = _ID_PATTERN.sub("<id>", text)
    text = _NUM_PATTERN.sub("<n>", text)
    return " ".join(text.split()).lower()[:200]


class ZohoError(UpstreamError):
    """Base class for every Zoho failure (HTTP 502 envelope by default)."""

    code = "zoho_error"
    category: ErrorCategory = ErrorCategory.BUG

    def __init__(
        self,
        msg: str,
        *,
        zoho_code: int | None = None,
        http_status: int | None = None,
        retry_after: float | None = None,
        module: str | None = None,
        zoho_id: str | None = None,
        request_id: str | None = None,
        category: ErrorCategory | None = None,
        data: dict | None = None,
    ) -> None:
        payload: dict[str, Any] = dict(data or {})
        if zoho_code is not None:
            payload["zoho_code"] = zoho_code
        if http_status is not None:
            payload["zoho_http_status"] = http_status
        if retry_after is not None:
            payload["retry_after"] = retry_after
        super().__init__(msg, data=payload)
        self.zoho_code = zoho_code
        self.http_status = http_status
        self.retry_after = retry_after
        self.module = module
        self.zoho_id = zoho_id
        self.request_id = request_id
        if category is not None:          # allow a call site to sharpen the category
            self.category = category

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE_CATEGORIES

    @property
    def counts_for_breaker(self) -> bool:
        return self.category in BREAKER_FAILURE_CATEGORIES

    @property
    def log_level(self) -> str:
        return CATEGORY_LOG_LEVEL.get(self.category, "error")

    def fingerprint(self) -> str:
        """Stable 16-char grouping key: class | status | zoho code | shape of message."""
        raw = f"{type(self).__name__}|{self.http_status}|{self.zoho_code}|{normalise_message(self.msg)}"
        return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

    def log_fields(self) -> dict[str, Any]:
        """Structured fields every terminal log event carries (docs §14.2)."""
        return {
            "error_class": type(self).__name__,
            "error_category": str(self.category),
            "error_fingerprint": self.fingerprint(),
            "http_status": self.http_status,
            "zoho_code": self.zoho_code,
            "retry_after": self.retry_after,
            "module": self.module,
            "zoho_id": self.zoho_id,
            "zoho_request_id": self.request_id,
        }


class ZohoUnclassifiedError(ZohoError):
    """A failure we could not classify — always investigated, never retried."""

    code = "zoho_api_error"
    category = ErrorCategory.BUG


#: Legacy name. The pre-v3 hierarchy had ``ZohoApiError`` as the base of every
#: Zoho exception, and existing call sites (engine, Celery ``autoretry_for``)
#: rely on ``except ZohoApiError`` catching everything — so it aliases the new
#: base rather than the unclassified leaf. New code raises the typed classes.
ZohoApiError = ZohoError


class ZohoTransientError(ZohoError):
    """5xx, timeout or connection failure on a retry-safe operation."""

    status_code = 503
    code = "zoho_transient"
    category = ErrorCategory.TRANSIENT


class ZohoRateLimitedError(ZohoError):
    """Zoho 429 (code 44/1070) or a local per-minute budget refusal."""

    status_code = 503
    code = "zoho_rate_limited"
    category = ErrorCategory.RATE_LIMITED


class ZohoQuotaExhaustedError(ZohoRateLimitedError):
    """The daily ceiling is reached (Zoho code 45 or our own governor)."""

    status_code = 503
    code = "zoho_quota_exhausted"
    category = ErrorCategory.QUOTA_EXHAUSTED

    def __init__(self, msg: str, *, resets_at: str | None = None, **kwargs: Any) -> None:
        data = dict(kwargs.pop("data", None) or {})
        if resets_at:
            data["resets_at"] = resets_at
        super().__init__(msg, data=data, **kwargs)
        self.resets_at = resets_at


class ZohoBudgetDeferred(ZohoRateLimitedError):
    """Background work refused by the governor (pacing / state) — not a failure.

    Raised to the *caller inside our own process* so a lane can yield and be
    rescheduled; never surfaced to an end user.
    """

    code = "zoho_budget_deferred"
    category = ErrorCategory.RATE_LIMITED

    def __init__(self, msg: str, *, reason: str, retry_at: str | None = None, **kwargs: Any) -> None:
        data = dict(kwargs.pop("data", None) or {})
        data["reason"] = reason
        if retry_at:
            data["retry_at"] = retry_at
        super().__init__(msg, data=data, **kwargs)
        self.reason = reason
        self.retry_at = retry_at


class ZohoCircuitOpenError(ZohoError):
    """The local circuit breaker refused the call (no quota was spent)."""

    status_code = 503
    code = "zoho_circuit_open"
    category = ErrorCategory.CIRCUIT_OPEN


class ZohoAuthError(ZohoError):
    """Token refresh failed or a fresh token was rejected."""

    status_code = 502
    code = "zoho_auth_error"
    category = ErrorCategory.AUTH


class ZohoAuthThrottledError(ZohoAuthError):
    """We are about to hit Zoho's 10-refreshes-per-10-minutes cap: a caching bug."""

    code = "zoho_auth_throttled"
    category = ErrorCategory.AUTH


class ZohoAuthRevokedError(ZohoAuthError):
    """Zoho rejected the refresh token (invalid_code/invalid_grant). Engine pauses."""

    code = "zoho_auth_revoked"
    category = ErrorCategory.AUTH_REVOKED


class ZohoAmbiguousOutcome(ZohoError):
    """A non-idempotent write was sent and the outcome is unknown.

    The dispatcher resolves it with an identity lookup (docs §10.4); it is
    never retried blindly, because Zoho may already have created the record.
    """

    status_code = 502
    code = "zoho_ambiguous_outcome"
    category = ErrorCategory.AMBIGUOUS


class ZohoNotFoundError(ZohoError):
    """HTTP 404 or Zoho code 1002 — the resource does not exist."""

    status_code = 404
    code = "zoho_not_found"
    category = ErrorCategory.NOT_FOUND


class ZohoValidationError(ZohoError):
    """HTTP 400 / business validation — retrying cannot help."""

    status_code = 400
    code = "zoho_validation_error"
    category = ErrorCategory.VALIDATION


class ZohoConflictError(ZohoError):
    """The remote record changed since the base version we edited from."""

    status_code = 409
    code = "zoho_conflict"
    category = ErrorCategory.CONFLICT


class ZohoForbiddenError(ZohoError):
    """HTTP 403 — the OAuth scope or the user's permissions are insufficient."""

    status_code = 403
    code = "zoho_forbidden"
    category = ErrorCategory.FORBIDDEN


class ZohoContractError(ZohoError):
    """A 2xx response did not match the documented shape (missing root key,
    missing page_context on a paginated call, oversized body).

    Never treated as "no more data" — that was the Laravel engine's D01.
    """

    status_code = 502
    code = "zoho_contract_error"
    category = ErrorCategory.CONTRACT


#: Mapping of the Zoho error codes documented in docs/zoho-docs-md/.
#: Code 0 means success and is deliberately absent: a lookup miss must fall
#: back to the HTTP-status default, never to a category.
ZOHO_CODE_CATEGORY: dict[int, ErrorCategory] = {
    44: ErrorCategory.RATE_LIMITED,  # per-minute limit; the ORG gets blocked if repeated
    45: ErrorCategory.QUOTA_EXHAUSTED,  # daily plan limit
    1000: ErrorCategory.TRANSIENT,   # "Internal error"
    1002: ErrorCategory.NOT_FOUND,   # "<resource> does not exist"
    1070: ErrorCategory.RATE_LIMITED,  # too many concurrent calls
    6041: ErrorCategory.FORBIDDEN,   # "This user is not associated with the CompanyID" — wrong org id
}

#: Operator hints appended to the message of well-known configuration errors.
ZOHO_CODE_HINTS: dict[int, str] = {
    6041: ("ZOHO_ORGANIZATION_ID is not an organization of the connected Zoho user — run "
           "`python -m app.modules.zoho.cli check --live` to list the organizations it can see, "
           "put the right id in deployment/.env and recreate backend + celery-worker + celery-beat"),
}

#: Exception class used for each category when the client raises.
CATEGORY_EXCEPTION: dict[ErrorCategory, type[ZohoError]] = {
    ErrorCategory.TRANSIENT: ZohoTransientError,
    ErrorCategory.RATE_LIMITED: ZohoRateLimitedError,
    ErrorCategory.QUOTA_EXHAUSTED: ZohoQuotaExhaustedError,
    ErrorCategory.CIRCUIT_OPEN: ZohoCircuitOpenError,
    ErrorCategory.AUTH: ZohoAuthError,
    ErrorCategory.AUTH_REVOKED: ZohoAuthRevokedError,
    ErrorCategory.AMBIGUOUS: ZohoAmbiguousOutcome,
    ErrorCategory.NOT_FOUND: ZohoNotFoundError,
    ErrorCategory.VALIDATION: ZohoValidationError,
    ErrorCategory.CONFLICT: ZohoConflictError,
    ErrorCategory.FORBIDDEN: ZohoForbiddenError,
    ErrorCategory.CONTRACT: ZohoContractError,
    ErrorCategory.BUG: ZohoUnclassifiedError,
}


def error_for(category: ErrorCategory, msg: str, **kwargs: Any) -> ZohoError:
    """Build the canonical exception for a category (used by the transport)."""
    hint = ZOHO_CODE_HINTS.get(kwargs.get("zoho_code") or 0)
    if hint:
        msg = f"{msg} [{hint}]"
    return CATEGORY_EXCEPTION.get(category, ZohoUnclassifiedError)(msg, **kwargs)


__all__ = [
    "BREAKER_FAILURE_CATEGORIES",
    "CATEGORY_EXCEPTION",
    "CATEGORY_LOG_LEVEL",
    "RETRYABLE_CATEGORIES",
    "ZOHO_CODE_CATEGORY",
    "ErrorCategory",
    "ZohoAmbiguousOutcome",
    "ZohoApiError",
    "ZohoAuthError",
    "ZohoAuthRevokedError",
    "ZohoAuthThrottledError",
    "ZohoBudgetDeferred",
    "ZohoCircuitOpenError",
    "ZohoConflictError",
    "ZohoContractError",
    "ZohoError",
    "ZohoForbiddenError",
    "ZohoNotFoundError",
    "ZohoQuotaExhaustedError",
    "ZohoRateLimitedError",
    "ZohoTransientError",
    "ZohoUnclassifiedError",
    "ZohoValidationError",
    "error_for",
    "normalise_message",
]
