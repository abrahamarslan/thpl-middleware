"""Activity recorder — the UTILITY for writing audit entries.

Why a utility and not a mixin / SQLAlchemy event listener?
  - Explicit calls are readable and testable; you see exactly where an audit
    entry is produced.
  - It is transaction-aware: it writes through the caller's session so the
    audit row commits atomically with the business change.
  - Event listeners fire inside arbitrary flush cycles (including ones you
    didn't intend to audit) and writing to the session from within a flush is
    fragile in async SQLAlchemy. A utility avoids all of that.

`request_id` and `ip_address` are pulled automatically from the structlog
contextvars bound by RequestContextMiddleware, so callers don't plumb the
request through every layer.

Resilience: by default `best_effort=True` wraps the insert in a SAVEPOINT, so
if writing the audit row fails it does NOT poison the caller's transaction or
break the business operation — the failure is logged operationally instead.
Set best_effort=False for compliance-critical actions that must not proceed
without a successful audit write.
"""

from typing import Any

import structlog
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.serialization import to_jsonable
from app.modules.activity.model import ActivityLog

logger = structlog.get_logger("app.activity")

# Never record these field values in a diff, even if they changed.
_SENSITIVE = {"password", "two_factor_secret", "two_factor_recovery_codes", "api_token", "remember_token"}


def _request_context() -> dict[str, Any]:
    ctx = structlog.contextvars.get_contextvars()
    return {"request_id": ctx.get("request_id"), "ip_address": ctx.get("client_ip")}


def model_changes(instance: Any, *, exclude: set[str] = frozenset()) -> dict[str, dict]:
    """Field-level {key: {old, new}} diff of a *dirty* ORM instance.

    Call BEFORE commit/flush while the unit-of-work history is still populated.
    Sensitive fields are masked to their changed-ness only (no values).
    """
    changes: dict[str, dict] = {}
    state = inspect(instance)
    for attr in state.attrs:
        if attr.key in exclude:
            continue
        hist = attr.history
        if not hist.has_changes():
            continue
        if attr.key in _SENSITIVE:
            changes[attr.key] = {"old": "***", "new": "***"}
            continue
        changes[attr.key] = {
            "old": to_jsonable(hist.deleted[0]) if hist.deleted else None,
            "new": to_jsonable(hist.added[0]) if hist.added else None,
        }
    return changes


async def record_activity(
    db: AsyncSession,
    *,
    action: str,
    actor_id: int | None = None,
    actor_type: str = "user",
    actor_label: str | None = None,
    subject_type: str | None = None,
    subject_id: Any | None = None,
    description: str | None = None,
    changes: dict | None = None,
    context: dict | None = None,
    status: str = "success",
    tenant_id=None,
    best_effort: bool = True,
) -> ActivityLog | None:
    """Persist one audit entry through the caller's session/transaction."""
    rc = _request_context()
    values = dict(
        action=action,
        status=status,
        description=description,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_label=actor_label,
        subject_type=subject_type,
        subject_id=str(subject_id) if subject_id is not None else None,
        changes=to_jsonable(changes) if changes else None,
        context=to_jsonable(context) if context else None,
        request_id=rc["request_id"],
        ip_address=rc["ip_address"],
        tenant_id=tenant_id,
    )

    if not best_effort:
        row = ActivityLog(**values)
        db.add(row)
        await db.flush()
        return row

    # SAVEPOINT-isolated: an audit failure never breaks the business op.
    try:
        async with db.begin_nested():
            row = ActivityLog(**values)
            db.add(row)
            await db.flush()
        return row
    except Exception:
        logger.error("activity_record_failed", action=action, subject_type=subject_type, exc_info=True)
        return None
