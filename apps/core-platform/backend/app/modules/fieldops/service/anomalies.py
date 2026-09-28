"""Anomalies — what a manager must look at. Opening one is IDEMPOTENT: every detector names
its finding with a ``dedupe_key``, and a second detection of the same thing is a no-op
(``INSERT … ON CONFLICT DO NOTHING`` on ``uq_anomalies_dedupe``). Detectors can therefore
re-run freely (a metrics recompute, a retried task)."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.modules.fieldops.enums import AnomalyState, AnomalyType, Severity, SubjectType
from app.modules.fieldops.errors import FieldOpsNotFound, FieldOpsRuleError
from app.modules.fieldops.model import Anomaly

logger = structlog.get_logger("app.fieldops.anomalies")

_OPEN_STATES = (AnomalyState.OPEN.value, AnomalyState.ACKNOWLEDGED.value)


async def open_anomaly(
    db: AsyncSession,
    *,
    anomaly_type: AnomalyType,
    severity: Severity,
    subject_type: SubjectType,
    subject: Any,
    dedupe_key: str,
    detector: str,
    user_id: int | None = None,
    shift_id: int | None = None,
    evidence: dict | None = None,
) -> bool:
    """Open an anomaly about ``subject`` (anything with tenant_id / organization_id / id). True if new."""
    label = detector if detector.startswith("system:") else f"system:fieldops-{detector}"
    inserted = await db.scalar(
        pg_insert(Anomaly)
        .values(
            tenant_id=subject.tenant_id, organization_id=subject.organization_id,
            anomaly_type=anomaly_type.value, severity=severity.value, status=AnomalyState.OPEN.value,
            subject_type=subject_type.value, subject_id=subject.id, user_id=user_id, shift_id=shift_id,
            detector=label, evidence=evidence or {}, dedupe_key=dedupe_key[:200],
            created_by_name=label, app_version=settings.VERSION, app_metadata={},
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "dedupe_key"], index_where=text("deleted_at IS NULL"))
        .returning(Anomaly.id)
    )
    if inserted is not None:
        logger.info("fieldops.anomaly_opened", anomaly_type=anomaly_type.value, subject_type=subject_type.value,
                    subject_id=subject.id, severity=severity.value)
    return inserted is not None


async def count_open(db: AsyncSession, *, shift_id: int) -> int:
    return int(await db.scalar(
        select(func.count()).select_from(Anomaly).where(Anomaly.shift_id == shift_id,
                                                        Anomaly.status.in_(_OPEN_STATES))
    ) or 0)


async def get_anomaly(db: AsyncSession, ref: str) -> Anomaly:
    cond = Anomaly.id == int(ref) if str(ref).isdigit() else Anomaly.uuid == uuid_lib.UUID(str(ref))
    row = await db.scalar(select(Anomaly).where(cond))
    if row is None:
        raise FieldOpsNotFound(f"Anomaly '{ref}' not found")
    return row


async def resolve(db: AsyncSession, ref: str, *, status: str, resolution_code: str | None, note: str | None,
                  actor_id: int) -> Anomaly:
    row = await get_anomaly(db, ref)
    if row.status in (AnomalyState.RESOLVED.value, AnomalyState.DISMISSED.value) and status != row.status:
        raise FieldOpsRuleError("anomaly_closed", "This anomaly is already closed")
    row.status = status
    row.resolution_code = resolution_code
    row.resolution_note = note
    if status in (AnomalyState.RESOLVED.value, AnomalyState.DISMISSED.value):
        row.resolved_by = actor_id
        row.resolved_at = dt.datetime.now(dt.UTC)
    await db.flush()
    return row


__all__ = ["count_open", "get_anomaly", "open_anomaly", "resolve"]
