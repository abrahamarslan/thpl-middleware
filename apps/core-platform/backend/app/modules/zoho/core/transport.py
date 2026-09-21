"""The Zoho transport — the only code in the platform that speaks HTTP to Zoho.

Every call, from any process, walks the same pipeline:

    switches.check()            # operator/auth kill switches — nothing below runs if off
    breaker.allow(group)        # local: is this endpoint group healthy?
      → governor.acquire()      # shared: quota state, daily ceiling, pacing, rate, concurrency
        → token_manager.get()   # one access token for the fleet
          → httpx request       # connect 5 s / read ZOHO_TIMEOUT_SECONDS
            → policy.classify() # what does this outcome mean?
              → policy.decide() # retry with jitter, retry with a new token, or raise

Guarantees:
  * nothing reaches ``zohoapis.*`` without a governor lease, so the daily
    ceiling cannot be exceeded and a paused engine really is paused;
  * a POST whose outcome is unknown raises ``ZohoAmbiguousOutcome`` — it is
    never retried, because Zoho has no idempotency key and a replay would
    duplicate the record;
  * ``paginate()`` **raises** on any error and stops only when Zoho says
    ``has_more_page == false``. An error is never mistaken for "end of list"
    (the defect that silently truncated the PHP crawls);
  * both Books and Inventory are reachable through one client, one budget and
    one set of logs.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

import httpx
import structlog

from app.core.conf import settings
from app.modules.zoho.core import policy
from app.modules.zoho.core.auth import zoho_token_manager
from app.modules.zoho.core.breaker import endpoint_group, zoho_breaker
from app.modules.zoho.core.errors import (
    ErrorCategory,
    ZohoContractError,
    ZohoError,
    error_for,
)
from app.modules.zoho.core.governor import Priority, zoho_governor
from app.modules.zoho.core.policy import Action, Outcome
from app.modules.zoho.core.schemas import ZohoResponse

logger = structlog.get_logger("app.zoho.transport")

#: Bodies larger than this are refused rather than parsed — a worker that OOMs
#: mid-run loses its slice; the PHP workers died exactly this way.
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

#: Path segments that are record ids (long digit runs) — replaced in the
#: `http_path_template` log/metric field so cardinality stays bounded.
def _path_template(path: str) -> str:
    parts = []
    for segment in path.strip("/").split("/"):
        parts.append("{id}" if segment.isdigit() else segment)
    return "/" + "/".join(parts)


class Api(StrEnum):
    """Which Zoho product a call goes to. One org, two APIs, one budget."""

    BOOKS = "books"
    INVENTORY = "inventory"

    @property
    def base_url(self) -> str:
        return {
            Api.BOOKS: settings.ZOHO_API_BASE_URL,
            Api.INVENTORY: settings.ZOHO_INVENTORY_API_URL,
        }[self]


@dataclass(frozen=True, slots=True)
class ZohoOp:
    """One intended call. Immutable so it can be logged, retried and replayed."""

    method: str
    path: str
    api: Api = Api.BOOKS
    params: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    json: Mapping[str, Any] | None = None
    headers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    priority: Priority = Priority.INCREMENTAL
    module: str | None = None
    purpose: str = "unspecified"        # list | detail | bulk_detail | create | update | action | lookup
    deadline_s: float = 60.0
    #: None → derived from the method. Set True for upserts (`X-Upsert`) and
    #: idempotent status actions; that is the only way a POST becomes retryable.
    retry_safe: bool | None = None
    #: "pull" | "push" for the engine switches; None → GET is pull, anything else push.
    direction: str | None = None

    @property
    def effective_direction(self) -> str:
        if self.direction:
            return self.direction
        return "pull" if self.method.upper() == "GET" else "push"

    @property
    def is_retry_safe(self) -> bool:
        return policy.is_retry_safe(self.method, declared=self.retry_safe)

    @property
    def group(self) -> str:
        return endpoint_group(str(self.api), self.path)

    @property
    def path_template(self) -> str:
        return _path_template(self.path)


@dataclass(slots=True)
class ZohoPage:
    """One page of a list endpoint."""

    records: list[dict[str, Any]]
    page: int
    per_page: int
    has_more_page: bool
    response: ZohoResponse


class ZohoClient:
    """The single async Zoho client. Import ``zoho_client``; don't construct one."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        governor=None,
        breaker=None,
        token_manager=None,
        switches=None,
        default_priority: Priority = Priority.INCREMENTAL,
        default_module: str | None = None,
    ) -> None:
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.ZOHO_TIMEOUT_SECONDS,
                connect=settings.ZOHO_CONNECT_TIMEOUT_SECONDS,
            )
        )
        self._governor = governor if governor is not None else zoho_governor
        self._breaker = breaker if breaker is not None else zoho_breaker
        self._tokens = token_manager if token_manager is not None else zoho_token_manager
        # Resolved lazily (see _switches): importing the switches module here
        # closes a cycle — switches → core.errors → core/__init__ → transport
        # → switches — whenever switches is the first Zoho module imported
        # (e.g. `cli check`; ERRORS E33).
        self._switches_override = switches
        # Applied by the verb helpers when the caller does not say otherwise —
        # lets a Celery task run the v1 engine at RECONCILE priority and have
        # every call attributed to its module in the governor and the logs.
        self._default_priority = default_priority
        self._default_module = default_module

    @property
    def _switches(self):
        if self._switches_override is None:
            from app.modules.zoho.control.switches import zoho_switches

            self._switches_override = zoho_switches
        return self._switches_override

    # ── verb helpers (v1-compatible signatures) ─────────────────────────────

    async def get(self, path: str, *, params: dict | None = None, **kwargs: Any) -> ZohoResponse:
        return await self.request(self._op("GET", path, params=params, **kwargs))

    async def post(self, path: str, *, json: dict | None = None, params: dict | None = None,
                   **kwargs: Any) -> ZohoResponse:
        return await self.request(self._op("POST", path, params=params, json=json, **kwargs))

    async def put(self, path: str, *, json: dict | None = None, params: dict | None = None,
                  **kwargs: Any) -> ZohoResponse:
        return await self.request(self._op("PUT", path, params=params, json=json, **kwargs))

    async def delete(self, path: str, *, params: dict | None = None, **kwargs: Any) -> ZohoResponse:
        return await self.request(self._op("DELETE", path, params=params, **kwargs))

    def _op(self, method: str, path: str, **kwargs: Any) -> ZohoOp:
        params = kwargs.pop("params", None) or {}
        json_body = kwargs.pop("json", None)
        kwargs.setdefault("priority", self._default_priority)
        kwargs.setdefault("module", self._default_module)
        return ZohoOp(method=method, path=path, params=params, json=json_body, **kwargs)

    # ── pagination ──────────────────────────────────────────────────────────

    async def iter_pages(
        self,
        op: ZohoOp,
        *,
        per_page: int = 200,
        start_page: int = 1,
        max_pages: int | None = None,
        root: str | None = None,
    ) -> AsyncIterator[ZohoPage]:
        """Walk a list endpoint. Raises on **any** error; never swallows a page.

        Stops when Zoho reports ``has_more_page == false``. A list response
        without ``page_context`` is a contract violation, not an empty list.
        """
        page = start_page
        pages_read = 0
        while True:
            response = await self.request(
                ZohoOp(
                    method=op.method, path=op.path, api=op.api,
                    params={**dict(op.params), "page": page, "per_page": per_page},
                    json=op.json, headers=op.headers, priority=op.priority,
                    module=op.module, purpose=op.purpose or "list",
                    deadline_s=op.deadline_s, retry_safe=op.retry_safe,
                )
            )
            context = response.page_context
            if context is None:
                raise ZohoContractError(
                    f"list response for {op.path_template} has no page_context",
                    module=op.module, request_id=response.request_id,
                    data={"path": op.path_template},
                )
            records = self._records(response, root=root, op=op)
            yield ZohoPage(
                records=records, page=context.page or page,
                per_page=context.per_page or per_page,
                has_more_page=bool(context.has_more_page), response=response,
            )

            pages_read += 1
            if not context.has_more_page:
                return
            if max_pages is not None and pages_read >= max_pages:
                logger.info(
                    "zoho.transport.page_budget_reached",
                    module=op.module, path=op.path_template, pages=pages_read,
                )
                return
            page += 1

    async def paginate(
        self,
        path: str,
        *,
        params: dict | None = None,
        per_page: int = 200,
        max_pages: int | None = None,
        start_page: int = 1,
        **kwargs: Any,
    ) -> AsyncIterator[ZohoResponse]:
        """v1-compatible pagination: yields raw responses (used by the v1 engine).
        ``start_page`` resumes a scan a previous slice yielded."""
        op = self._op("GET", path, params=params, **kwargs)
        async for page in self.iter_pages(op, per_page=per_page, start_page=start_page, max_pages=max_pages):
            yield page.response

    @staticmethod
    def _records(response: ZohoResponse, *, root: str | None, op: ZohoOp) -> list[dict[str, Any]]:
        data = response.raw.get(root) if root else response.data
        if data is None:
            raise ZohoContractError(
                f"list response for {op.path_template} is missing its records"
                + (f" (root '{root}')" if root else ""),
                module=op.module, request_id=response.request_id,
            )
        if isinstance(data, dict):
            return [data]
        if not isinstance(data, list):
            raise ZohoContractError(
                f"list response for {op.path_template} is not a list",
                module=op.module, request_id=response.request_id,
            )
        return data

    # ── the request pipeline ────────────────────────────────────────────────

    async def request(self, op: ZohoOp) -> ZohoResponse:
        request_id = (
            structlog.contextvars.get_contextvars().get("request_id")
            or f"zoho-{uuid.uuid4().hex[:12]}"
        )
        started = time.monotonic()
        attempt = 0
        token_retried = False

        # First gate: a paused engine spends no quota, takes no rate token and
        # never touches the breaker.
        await self._switches.check(
            direction=op.effective_direction,  # type: ignore[arg-type]
            module=op.module,
            interactive=op.priority is Priority.INTERACTIVE,
        )

        while True:
            attempt += 1
            elapsed = time.monotonic() - started
            admission = await self._breaker.allow(op.group)     # raises ZohoCircuitOpenError

            async with self._governor.slot(
                op.priority, module=op.module, purpose=op.purpose
            ) as lease:
                token = await self._tokens.get_token()
                call_started = time.perf_counter()
                try:
                    lease.mark_sent()                            # bytes are about to leave
                    http_response = await self._send(op, token=token, request_id=request_id)
                    if settings.ZOHO_HTTP_LOG_BODIES:
                        self._log_exchange(op, http_response, request_id)
                except httpx.HTTPError as exc:
                    duration = time.perf_counter() - call_started
                    outcome = Outcome(
                        method=op.method, retry_safe=op.is_retry_safe, exception=exc,
                        sent=not isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout),
                        token_retried=token_retried,
                    )
                    decision = policy.decide(
                        outcome, attempt=attempt, elapsed=elapsed, deadline=op.deadline_s
                    )
                    await self._breaker.record_failure(
                        admission, category=decision.category, duration=duration
                    )
                    self._log_attempt(op, request_id, attempt, duration, None, decision, error=str(exc))
                    if decision.action is Action.RETRY:
                        await self._sleep(decision.delay)
                        continue
                    await _record(ok=False, path=op.path_template, module=op.module,
                                  category=str(decision.category), message=str(exc))
                    raise self._error(op, decision.category, str(exc), request_id=request_id) from exc

            duration = time.perf_counter() - call_started
            payload, size = self._parse(http_response, op=op, request_id=request_id)
            response = ZohoResponse.from_payload(
                request_id=request_id, http_status=http_response.status_code, payload=payload
            )

            if response.ok:
                await self._breaker.record_success(admission, duration=duration)
                self._log_attempt(op, request_id, attempt, duration, http_response.status_code, None,
                                  response_bytes=size)
                await _record(ok=True, path=op.path_template, module=op.module)
                return response

            outcome = Outcome(
                method=op.method, retry_safe=op.is_retry_safe,
                http_status=http_response.status_code, zoho_code=response.zoho_code or None,
                token_retried=token_retried,
            )
            retry_after = policy.parse_retry_after(http_response.headers.get("Retry-After"))
            decision = policy.decide(
                outcome, attempt=attempt, elapsed=time.monotonic() - started,
                deadline=op.deadline_s, retry_after=retry_after,
            )
            await self._record_outcome(admission, decision.category, duration)
            self._log_attempt(op, request_id, attempt, duration, http_response.status_code, decision,
                              zoho_code=response.zoho_code, message=response.message)

            if decision.category is ErrorCategory.QUOTA_EXHAUSTED:
                # Zoho's own answer beats our counter — stop the whole engine.
                await self._governor.mark_quota_exhausted(reason="zoho_code_45")

            if decision.action is Action.RETRY_WITH_NEW_TOKEN:
                await self._tokens.invalidate(token)
                token_retried = True
                continue
            if decision.action is Action.RETRY:
                await self._sleep(decision.delay)
                continue

            await _record(ok=False, path=op.path_template, module=op.module, zoho_code=response.zoho_code,
                          category=str(decision.category), message=response.message)
            raise self._error(
                op, decision.category,
                response.message or f"Zoho API error (HTTP {http_response.status_code})",
                request_id=request_id, http_status=http_response.status_code,
                zoho_code=response.zoho_code, retry_after=retry_after,
            )

    # ── internals ───────────────────────────────────────────────────────────

    async def _send(self, op: ZohoOp, *, token: str, request_id: str) -> httpx.Response:
        params = {"organization_id": settings.ZOHO_ORGANIZATION_ID, **dict(op.params)}
        headers = {
            "Authorization": f"Zoho-oauthtoken {token}",
            "X-Request-Id": request_id,
            "Accept": "application/json",
            **dict(op.headers),
        }
        return await self._http.request(
            op.method,
            f"{op.api.base_url.rstrip('/')}/{op.path.lstrip('/')}",
            params=params,
            json=dict(op.json) if op.json is not None else None,
            headers=headers,
        )

    def _parse(self, response: httpx.Response, *, op: ZohoOp, request_id: str) -> tuple[dict, int]:
        body = response.content
        if len(body) > MAX_RESPONSE_BYTES:
            raise ZohoContractError(
                f"Zoho response for {op.path_template} is {len(body)} bytes "
                f"(limit {MAX_RESPONSE_BYTES}); refusing to parse",
                module=op.module, request_id=request_id, http_status=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {"code": -1, "message": response.text[:500]}
        if not isinstance(payload, dict):
            payload = {"code": -1, "message": "Zoho returned a non-object body"}
        return payload, len(body)

    async def _record_outcome(self, admission, category: ErrorCategory, duration: float) -> None:
        await self._breaker.record_failure(admission, category=category, duration=duration)

    @staticmethod
    def _error(
        op: ZohoOp,
        category: ErrorCategory,
        message: str,
        *,
        request_id: str,
        http_status: int | None = None,
        zoho_code: int | None = None,
        retry_after: float | None = None,
    ) -> ZohoError:
        return error_for(
            category, message, http_status=http_status, zoho_code=zoho_code or None,
            retry_after=retry_after, module=op.module, request_id=request_id,
            data={"path": op.path_template, "purpose": op.purpose, "method": op.method},
        )

    @staticmethod
    async def _sleep(delay: float) -> None:
        import asyncio

        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _log_exchange(op: ZohoOp, http_response: httpx.Response, request_id: str) -> None:
        """Opt-in (ZOHO_HTTP_LOG_BODIES) request/response dump for debugging.

        The OAuth token is a header and is never logged; query parameters and
        bodies can hold business data and personal data — enable in dev or for
        a short diagnosis only. Bodies are truncated to ZOHO_HTTP_LOG_BODY_MAX.
        """
        limit = settings.ZOHO_HTTP_LOG_BODY_MAX
        request = http_response.request
        logger.info(
            "zoho.transport.http_exchange",
            module=op.module, http_method=op.method, url=str(request.url.copy_with(query=None)),
            query=dict(request.url.params), request_body=(request.content or b"")[:limit].decode("utf-8", "replace"),
            http_status=http_response.status_code, response_body=http_response.text[:limit],
            response_bytes=len(http_response.content), zoho_request_id=request_id,
        )

    @staticmethod
    def _log_attempt(
        op: ZohoOp,
        request_id: str,
        attempt: int,
        duration: float,
        status: int | None,
        decision,
        **extra: Any,
    ) -> None:
        fields = {
            "module": op.module,
            "http_method": op.method,
            "http_path_template": op.path_template,   # never the raw path: ids blow up cardinality
            "api": str(op.api),
            "purpose": op.purpose,
            "priority": op.priority.name.lower(),
            "http_status": status,
            "attempt": attempt,
            "duration_ms": round(duration * 1000, 2),
            "zoho_request_id": request_id,
            **{k: v for k, v in extra.items() if v is not None},
        }
        if decision is None:
            logger.info("zoho.transport.call_completed", outcome="success", **fields)
        elif decision.action in (Action.RETRY, Action.RETRY_WITH_NEW_TOKEN):
            logger.warning(
                "zoho.transport.retrying", outcome="retry",
                error_category=str(decision.category), reason=decision.reason,
                retry_in=round(decision.delay, 2), **fields,
            )
        else:
            logger.warning(
                "zoho.transport.call_failed", outcome="failed",
                error_category=str(decision.category), reason=decision.reason, **fields,
            )

    async def aclose(self) -> None:
        await self._http.aclose()


async def _record(**kwargs: Any) -> None:
    """Evidence for the connection report (core/connection.py) — best-effort."""
    from app.modules.zoho.core.connection import record_outcome

    await record_outcome(**kwargs)


#: Process-wide client. Celery tasks get their own per-process event loop and
#: therefore their own instance (see app/tasks/_loop.py).
zoho_client = ZohoClient()

__all__ = ["Api", "MAX_RESPONSE_BYTES", "ZohoClient", "ZohoOp", "ZohoPage", "zoho_client"]
