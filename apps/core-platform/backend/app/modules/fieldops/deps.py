"""Request-side dependencies of the field-ops API.

``DeviceClock``     the device's clocks AT SEND, from headers, plus the server's receipt time —
                    the ``SendContext`` every ``clock.derive`` call needs:

                        X-Device-Sent-At      device wall clock when the request was sent (ISO-8601)
                        X-Device-Elapsed-Ms   device monotonic clock at send
                        X-Device-Boot-Count   device boot counter
                        X-Device-Session      the app session uuid (POST /me/devices)

                    All optional: a legacy client that sends none still works, its times simply
                    get a weaker ``time_basis``. A malformed header is ignored, never a 400 — a
                    device with a broken clock must still be able to report.
``IdempotencyKey``  ``X-Idempotency-Key`` (uuid), optional — see app/modules/idempotency.
row targets         ``Perm(..., target=shift_target)`` judges manager actions at the row's
                    organization.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Annotated

from fastapi import Depends, Header, Request

from app.common.exception.errors import AppError
from app.modules.fieldops.clock import SendContext
from app.modules.rbac.deps import org_of


def _parse_dt(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        value = dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _parse_int(raw: str | None) -> int | None:
    try:
        value = int(raw) if raw not in (None, "") else None
    except ValueError:
        return None
    return value if value is None or value >= 0 else None


def _parse_uuid(raw: str | None) -> uuid_lib.UUID | None:
    try:
        return uuid_lib.UUID(raw) if raw else None
    except ValueError:
        return None


async def device_clock(
    request: Request,
    x_device_sent_at: Annotated[str | None, Header()] = None,
    x_device_elapsed_ms: Annotated[str | None, Header()] = None,
    x_device_boot_count: Annotated[str | None, Header()] = None,
    x_device_session: Annotated[str | None, Header()] = None,
) -> SendContext:
    received = getattr(request.state, "fieldops_received_at", None)
    if received is None:
        received = dt.datetime.now(dt.UTC)
        request.state.fieldops_received_at = received
    return SendContext(
        received_at=received,
        sent_at=_parse_dt(x_device_sent_at),
        sent_elapsed_ms=_parse_int(x_device_elapsed_ms),
        boot_count=_parse_int(x_device_boot_count),
        session_uuid=_parse_uuid(x_device_session),
    )


DeviceClock = Annotated[SendContext, Depends(device_clock)]


class InvalidIdempotencyKey(AppError):
    status_code = 400
    code = "invalid_idempotency_key"


async def idempotency_key(
    x_idempotency_key: Annotated[str | None, Header()] = None,
) -> uuid_lib.UUID | None:
    if not x_idempotency_key:
        return None
    try:
        return uuid_lib.UUID(x_idempotency_key)
    except ValueError:
        raise InvalidIdempotencyKey("X-Idempotency-Key must be a UUID") from None


IdempotencyKeyDep = Annotated[uuid_lib.UUID | None, Depends(idempotency_key)]


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


#: Manager routes on one row judge the action at that row's organization.
shift_target = org_of("app.modules.fieldops.model.shift:Shift")
visit_target = org_of("app.modules.fieldops.model.visit:Visit")
anomaly_target = org_of("app.modules.fieldops.model.ledger:Anomaly")
policy_target = org_of("app.modules.fieldops.model.policy:WorkPolicy")

__all__ = [
    "DeviceClock", "IdempotencyKeyDep", "anomaly_target", "device_clock", "idempotency_key",
    "policy_target", "request_id", "shift_target", "visit_target",
]
