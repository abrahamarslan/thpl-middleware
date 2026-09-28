"""Run a mutation at most once per client key.

    return await idempotency.run(
        db, user=user, key=x_idempotency_key, route="POST /me/shifts/{uuid}/end",
        payload=body.model_dump(mode="json"), status_code=200,
        handler=lambda: _end(...),          # returns the ResponseModel to send
    )

Semantics
---------
* no key → the handler simply runs (keys are optional; creates are already idempotent
  through the client-generated entity uuid);
* first use of a key → an ``in_flight`` row is inserted IN THE REQUEST'S TRANSACTION, the
  handler runs, the row becomes ``completed`` with the response. If the handler raises, the
  transaction rolls back and the row with it — errors are not stored, so a client that fixes
  its request may retry with the same key;
* replay (same key, same fingerprint) → the stored response, status and body, with the
  ``Idempotent-Replayed: true`` header; the handler does not run;
* same key, different request → 409 ``idempotency_key_reused``.

Concurrency: two requests racing on one key serialise on the unique index; the loser sees
the winner's committed row and replays it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid as uuid_lib
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError
from app.modules.idempotency.model import IdempotencyKey

#: Rural devices do stay offline for days; the entity uuid still protects creates after expiry.
RETENTION = dt.timedelta(days=30)
REPLAY_HEADER = "Idempotent-Replayed"


class IdempotencyKeyReused(ConflictError):
    code = "idempotency_key_reused"


class IdempotencyInFlight(ConflictError):
    code = "idempotency_in_flight"


def fingerprint(route: str, payload: Any) -> str:
    canonical = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{route}\n{canonical}".encode()).hexdigest()


async def run(
    db: AsyncSession,
    *,
    user: Any,
    key: uuid_lib.UUID | None,
    route: str,
    payload: Any,
    status_code: int,
    handler: Callable[[], Awaitable[BaseModel | tuple[BaseModel, int]]],
    entity_type: str | None = None,
) -> JSONResponse:
    """``handler`` returns the response model, or ``(model, status)`` to override ``status_code``
    (e.g. 201 for a create, 200 when the create was a replay of an existing entity)."""
    if key is None:
        model, status = _unpack(await handler(), status_code)
        return JSONResponse(status_code=status, content=jsonable_encoder(model))

    digest = fingerprint(route, payload)
    now = dt.datetime.now(dt.UTC)
    inserted = await db.scalar(
        pg_insert(IdempotencyKey)
        .values(tenant_id=user.tenant_id, user_id=user.id, key=key, route=route, request_fingerprint=digest,
                state="in_flight", expires_at=now + RETENTION, app_metadata={})
        .on_conflict_do_nothing(constraint="uq_idempotency_keys_user_key")
        .returning(IdempotencyKey.id)
    )
    if inserted is None:
        existing = await db.scalar(select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == user.tenant_id, IdempotencyKey.user_id == user.id,
            IdempotencyKey.key == key,
        ))
        if existing is None:                                       # pragma: no cover — deleted mid-flight
            raise IdempotencyInFlight("The request is being processed; retry shortly")
        if existing.request_fingerprint != digest:
            raise IdempotencyKeyReused(
                "This idempotency key was already used for a different request",
                data={"route": existing.route},
            )
        if existing.state != "completed":
            raise IdempotencyInFlight("The request with this key is still being processed; retry shortly")
        return JSONResponse(status_code=existing.response_status or 200, content=existing.response_body,
                            headers={REPLAY_HEADER: "true"})

    model, status = _unpack(await handler(), status_code)
    body = jsonable_encoder(model)
    data = body.get("data") if isinstance(body, dict) else None
    entity_uuid = data.get("uuid") if isinstance(data, dict) else None
    await db.execute(
        update(IdempotencyKey).where(IdempotencyKey.id == inserted).values(
            state="completed", response_status=status, response_body=body, entity_type=entity_type,
            entity_uuid=uuid_lib.UUID(str(entity_uuid)) if entity_uuid else None,
        )
    )
    return JSONResponse(status_code=status, content=body)


def _unpack(result: BaseModel | tuple[BaseModel, int], default_status: int) -> tuple[BaseModel, int]:
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, default_status


async def purge_expired(db: AsyncSession) -> int:
    """Delete keys past their window (nightly maintenance). Returns rows deleted."""
    from sqlalchemy import delete

    result = await db.execute(
        delete(IdempotencyKey).where(IdempotencyKey.expires_at < dt.datetime.now(dt.UTC))
        .execution_options(all_tenants=True)
    )
    return result.rowcount or 0


__all__ = ["REPLAY_HEADER", "IdempotencyInFlight", "IdempotencyKeyReused", "fingerprint", "purge_expired", "run"]
