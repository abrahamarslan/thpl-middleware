"""Compliance module — DPDP Act 2023 cross-cutting records.

    consent_records            ENTITY   explicit consent ledger (single source of truth)
    data_retention_schedules   GLOBAL   per-category retention rules (reference data)
    data_principal_requests    ENTITY   DPDP data-principal rights lifecycle + SLA
    kyc_audit_logs             LEDGER   immutable before/after compliance audit trail

Every record is anchored to a ``user_id`` (except the global retention catalog).
"""

from app.modules.compliance.model import (
    ConsentRecord,
    DataPrincipalRequest,
    DataRetentionSchedule,
    KYCAuditLog,
)

__all__ = [
    "ConsentRecord",
    "DataPrincipalRequest",
    "DataRetentionSchedule",
    "KYCAuditLog",
]
