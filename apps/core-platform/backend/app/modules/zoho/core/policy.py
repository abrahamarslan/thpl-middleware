"""Retry & classification policy — pure functions, no I/O, fully table-tested.

Doctrine (docs/zoho-sync-platform-architecture.md §12):
  - One place decides what a failure *means* (``classify``) and one place
    decides what happens next (``decide``). The transport executes; it never
    interprets.
  - **A write that was already sent is never retried blindly.** POST creates
    and non-idempotent actions raise ``AMBIGUOUS`` on 5xx / read timeouts so
    the outbox can resolve them with an identity lookup. This is the defect
    that duplicated invoices in the PHP engine and was reintroduced in the
    first Python client (finding P1).
  - **429 is not a breaker failure.** Throttling is normal traffic shaping;
    treating it as an outage opened the circuit under load (finding P2).
  - Backoff is full jitter, bounded by the operation's deadline. Anything
    longer than a few seconds belongs to a durable retry (outbox
    ``next_attempt_at`` / record-error ``next_retry_at``), never to a sleep.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import httpx

from app.modules.zoho.core.errors import ZOHO_CODE_CATEGORY, ErrorCategory

HttpMethod = Literal["GET", "POST", "PUT", "DELETE"]

#: Methods whose repetition cannot create a second record by definition.
IDEMPOTENT_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "PUT", "DELETE"})

#: In-client retry budget (R1). Longer waits are R4's job.
MAX_ATTEMPTS = 4          # 1 initial + 3 retries
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 8.0

#: httpx exceptions raised *before* any byte reached Zoho — safe to retry even
#: for POST, because the request provably never arrived.
_PRE_SEND_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ProxyError,
    httpx.UnsupportedProtocol,
)

#: httpx exceptions raised after the request was written — outcome unknown.
_POST_SEND_EXCEPTIONS = (
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)


def is_retry_safe(method: str, *, declared: bool | None = None) -> bool:
    """Can this operation be replayed after an unknown outcome?

    ``declared`` lets an adapter mark a POST as safe — e.g. an upsert via
    ``X-Unique-Identifier``/``X-Upsert`` or an idempotent status transition
    (``POST /invoices/{id}/status/sent``). Default: methods only.
    """
    if declared is not None:
        return declared
    return method.upper() in IDEMPOTENT_METHODS


@dataclass(frozen=True, slots=True)
class Outcome:
    """Everything known about one HTTP attempt."""

    method: str
    retry_safe: bool
    http_status: int | None = None
    zoho_code: int | None = None
    exception: BaseException | None = None
    sent: bool = True            # did the request leave the client?
    token_retried: bool = False  # has a 401 already been retried once?


def classify(outcome: Outcome) -> ErrorCategory:
    """Map one attempt's result onto an :class:`ErrorCategory`."""
    exc = outcome.exception
    if exc is not None:
        if isinstance(exc, _PRE_SEND_EXCEPTIONS):
            return ErrorCategory.TRANSIENT
        if isinstance(exc, _POST_SEND_EXCEPTIONS):
            # Sent, outcome unknown: retry only if replay cannot duplicate.
            return ErrorCategory.TRANSIENT if outcome.retry_safe else ErrorCategory.AMBIGUOUS
        if isinstance(exc, httpx.TransportError):
            return ErrorCategory.TRANSIENT if not outcome.sent or outcome.retry_safe else ErrorCategory.AMBIGUOUS
        return ErrorCategory.BUG

    status = outcome.http_status
    code = outcome.zoho_code

    if status is None:
        return ErrorCategory.BUG

    if status == 401:
        return ErrorCategory.AUTH
    if status == 403:
        return ErrorCategory.FORBIDDEN
    if status == 404:
        return ErrorCategory.NOT_FOUND
    if status == 405:
        return ErrorCategory.BUG
    if status == 429:
        # Zoho distinguishes per-minute (44), daily (45) and concurrency (1070);
        # an unlabelled 429 is throttling, never a quota stop.
        return ZOHO_CODE_CATEGORY.get(code, ErrorCategory.RATE_LIMITED) if code else ErrorCategory.RATE_LIMITED
    if status >= 500:
        return ErrorCategory.TRANSIENT if outcome.retry_safe else ErrorCategory.AMBIGUOUS
    if status == 400:
        # A known Zoho code sharpens a 400 (e.g. 6041 = wrong organization id
        # → FORBIDDEN: configuration, not data; ERRORS E35).
        return ZOHO_CODE_CATEGORY.get(code, ErrorCategory.VALIDATION) if code else ErrorCategory.VALIDATION
    if 200 <= status < 300:
        # A 2xx with a non-zero Zoho code is a business error in disguise.
        if code:
            return ZOHO_CODE_CATEGORY.get(code, ErrorCategory.VALIDATION)
        return ErrorCategory.BUG  # caller should not classify a success
    if 400 <= status < 500:
        return ZOHO_CODE_CATEGORY.get(code, ErrorCategory.VALIDATION) if code else ErrorCategory.VALIDATION
    return ErrorCategory.BUG


class Action(StrEnum):
    RETRY = "retry"                     # sleep `delay` and try again
    RETRY_WITH_NEW_TOKEN = "retry_token"  # invalidate the access token first
    RAISE = "raise"                     # give up in the client; caller decides


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    delay: float = 0.0
    category: ErrorCategory = ErrorCategory.BUG
    reason: str = ""


def backoff(attempt: int, *, base: float = BACKOFF_BASE_SECONDS, cap: float = BACKOFF_CAP_SECONDS,
            rng: random.Random | None = None) -> float:
    """Full-jitter exponential backoff: ``U(0, min(cap, base·2^(attempt-1)))``.

    Full jitter (rather than equal jitter or plain exponential) is what keeps
    a fleet of workers from re-synchronising into a thundering herd after a
    Zoho outage.
    """
    ceiling = min(cap, base * (2 ** max(attempt - 1, 0)))
    return (rng or random).uniform(0.0, ceiling)


def decide(
    outcome: Outcome,
    *,
    attempt: int,
    elapsed: float,
    deadline: float,
    retry_after: float | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    rng: random.Random | None = None,
) -> Decision:
    """What should the transport do after ``outcome``?

    ``attempt`` is 1-based; ``elapsed``/``deadline`` are seconds of wall clock
    for the whole operation including waits.
    """
    category = classify(outcome)

    if category is ErrorCategory.AUTH and not outcome.token_retried:
        # A 401 is worth exactly one retry with a freshly minted token.
        return Decision(Action.RETRY_WITH_NEW_TOKEN, 0.0, category, "token_invalidated")

    if category not in (
        ErrorCategory.TRANSIENT,
        ErrorCategory.RATE_LIMITED,
    ):
        return Decision(Action.RAISE, 0.0, category, "non_retryable")

    if attempt >= max_attempts:
        return Decision(Action.RAISE, 0.0, category, "attempts_exhausted")

    wait = retry_after if retry_after is not None else backoff(attempt, rng=rng)
    if elapsed + wait >= deadline:
        # Waiting would blow the caller's budget: let the durable layer retry.
        return Decision(Action.RAISE, 0.0, category, "deadline_exceeded")

    return Decision(Action.RETRY, wait, category, "retry_after" if retry_after is not None else "backoff")


def parse_retry_after(value: str | None) -> float | None:
    """Zoho sends ``Retry-After`` in seconds when it sends it at all."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


__all__ = [
    "Action",
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_CAP_SECONDS",
    "Decision",
    "IDEMPOTENT_METHODS",
    "MAX_ATTEMPTS",
    "Outcome",
    "backoff",
    "classify",
    "decide",
    "is_retry_safe",
    "parse_retry_after",
]
