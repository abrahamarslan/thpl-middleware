"""Self-service consent (DPDP Act, 2023) — ``/api/me/consents`` (docs/compliance/consents.md).

A consent is a ``compliance.consent_records`` row: who, what (``consent_type``), which notice text
(``consent_text_version``, ``consent_language``), when, from where (IP, device). Rules:

* GIVING is idempotent per (user, type, version): giving the same version again returns the live row;
  giving a NEW version supersedes the previous live one (``is_active = false``, kept as history).
* WITHDRAWING stamps ``withdrawal_requested_at`` / ``withdrawn_at`` and deactivates the live row(s) — and
  fires the registered withdrawal listeners in the same transaction. Field operations registers one: a
  withdrawn ``location_tracking`` consent ends the open shift (``end_reason = consent_withdrawn``); under
  DPDP a withdrawal must not be ignored while tracking carries on.

``compliance`` must not import feature modules, so features REGISTER listeners (``on_withdrawal``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.compliance.enums import ConsentChannel, ConsentType
from app.modules.compliance.model import ConsentRecord

logger = structlog.get_logger("app.compliance.consents")

WithdrawalListener = Callable[[AsyncSession, Any, str], Awaitable[None]]
_listeners: list[WithdrawalListener] = []


def on_withdrawal(listener: WithdrawalListener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_type: ConsentType
    consent_given: bool = True
    consent_text_version: str = Field(..., min_length=1, max_length=20,
                                      description="Version of the notice text the user saw")
    consent_language: str | None = Field(None, max_length=20)
    purpose_text: str | None = Field(None, max_length=255)
    consent_channel: ConsentChannel = ConsentChannel.MOBILE_APP
    device_info: dict[str, Any] | None = None


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    consent_type: str
    consent_given: bool
    consent_text_version: str | None
    consent_language: str | None
    purpose_text: str | None
    consent_channel: str
    consented_at: dt.datetime
    withdrawn_at: dt.datetime | None
    is_active: bool


async def list_mine(db: AsyncSession, user: Any, *, include_inactive: bool = False) -> list[ConsentRecord]:
    stmt = select(ConsentRecord).where(ConsentRecord.user_id == user.id)
    if not include_inactive:
        stmt = stmt.where(ConsentRecord.is_active.is_(True), ConsentRecord.withdrawn_at.is_(None))
    return list((await db.scalars(stmt.order_by(ConsentRecord.consented_at.desc()))).all())


async def live(db: AsyncSession, user_id: int, consent_type: str) -> list[ConsentRecord]:
    return list((await db.scalars(select(ConsentRecord).where(
        ConsentRecord.user_id == user_id, ConsentRecord.consent_type == consent_type,
        ConsentRecord.is_active.is_(True), ConsentRecord.withdrawn_at.is_(None),
    ))).all())


async def give(db: AsyncSession, user: Any, body: ConsentIn, *, ip: str | None = None) -> tuple[ConsentRecord, bool]:
    """Record a consent. Returns (row, created)."""
    if not body.consent_given and await live(db, user.id, body.consent_type.value):
        await withdraw(db, user, body.consent_type.value)       # declining after agreeing = withdrawal
    current = await live(db, user.id, body.consent_type.value)
    for row in current:
        if row.consent_given and row.consent_text_version == body.consent_text_version and body.consent_given:
            return row, False
    now = dt.datetime.now(dt.UTC)
    for row in current:
        row.is_active = False                 # superseded by the new version (kept as history)
    record = ConsentRecord(
        user_id=user.id, organization_id=user.organization_id, consent_type=body.consent_type.value,
        consent_given=body.consent_given, consent_text_version=body.consent_text_version,
        consent_language=body.consent_language, purpose_text=body.purpose_text,
        legal_basis_reference="DPDP Act 2023 s.6", consent_channel=body.consent_channel.value, consented_at=now,
        consent_ip_address=ip, consent_device_info=body.device_info, is_active=body.consent_given,
        withdrawn_at=None if body.consent_given else now,
    )
    db.add(record)
    await db.flush()
    logger.info("compliance.consent_given", user_id=user.id, consent_type=record.consent_type,
                version=record.consent_text_version, given=record.consent_given)
    return record, True


async def withdraw(db: AsyncSession, user: Any, consent_type: str) -> int:
    rows = await live(db, user.id, consent_type)
    if not rows:
        raise NotFoundError(f"No active {consent_type} consent to withdraw")
    now = dt.datetime.now(dt.UTC)
    for row in rows:
        row.withdrawal_requested_at = row.withdrawal_requested_at or now
        row.withdrawn_at = now
        row.is_active = False
    await db.flush()
    for listener in _listeners:
        await listener(db, user, consent_type)
    logger.info("compliance.consent_withdrawn", user_id=user.id, consent_type=consent_type, rows=len(rows))
    return len(rows)


__all__ = ["ConsentIn", "ConsentOut", "give", "list_mine", "live", "on_withdrawal", "withdraw"]
