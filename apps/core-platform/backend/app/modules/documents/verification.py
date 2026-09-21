"""The verification lifecycle of a document — state machine, transitions, trail.

    pending_upload ─► uploaded ─► in_review ─► verified ─► expired
                          │           │           │
                          └───────────┴─► rejected ┴─► resubmission_required

Every transition goes through ``transition()``: it checks ``ALLOWED_TRANSITIONS``,
keeps ``is_verified`` (a cache the database also checks) in step with the status,
and appends a row to ``document_verification_logs`` in the same transaction.

A resubmission is not a transition. It creates a NEW version of the document
(``service.resubmit_document``) that starts at ``uploaded`` and leaves the old
row as evidence of what was rejected and why.

Authorisation is the caller's business (the API requires ``TenantAdmin`` for
the reviewer actions until RBAC lands — docs/tenancy/README.md §4).
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError
from app.database.tenancy import current_actor
from app.modules.documents import crud, schema
from app.modules.documents.enums import (
    ALLOWED_TRANSITIONS,
    DocumentAuditAction,
    DocumentPageSide,
    DocumentVerificationStatus,
    VerificationActorType,
)
from app.modules.documents.errors import DocumentRuleError
from app.modules.documents.model import Document, DocumentType

logger = structlog.get_logger("app.documents")

_S = DocumentVerificationStatus

#: The audit action a transition INTO a status is recorded as.
_ACTION_FOR = {
    _S.UPLOADED: DocumentAuditAction.UPLOADED,
    _S.IN_REVIEW: DocumentAuditAction.IN_REVIEW,
    _S.VERIFIED: DocumentAuditAction.VERIFIED,
    _S.REJECTED: DocumentAuditAction.REJECTED,
    _S.EXPIRED: DocumentAuditAction.EXPIRED,
    _S.RESUBMISSION_REQUIRED: DocumentAuditAction.RESUBMISSION_REQUESTED,
}


def is_complete(document_type: DocumentType, page_sides: Iterable[object]) -> bool:
    """Does this set of files satisfy the type? One file, or — for two-sided
    types — a front AND a back."""
    sides = {getattr(s, "value", s) for s in page_sides}
    if document_type.requires_front_and_back:
        return {DocumentPageSide.FRONT.value, DocumentPageSide.BACK.value} <= sides
    return bool(sides)


async def record_event(
    db: AsyncSession, document: Document, *, action: DocumentAuditAction,
    previous_status: str | None, new_status: str | None,
    actor_id: int | None = None, actor_type: VerificationActorType = VerificationActorType.STAFF,
    remarks: str | None = None,
):
    """Append one row to the trail, snapshotting the document's owner link."""
    actor = current_actor()
    owner = await crud.find_owner_link(db, document.id)
    ctx = structlog.contextvars.get_contextvars()
    return await crud.add_log(db, {
        "document_id": document.id, "tenant_id": document.tenant_id,
        "organization_id": document.organization_id,
        "primary_link_type": owner.linkable_type if owner else None,
        "primary_link_id": owner.linkable_id if owner else None,
        "action": action.value, "previous_status": previous_status, "new_status": new_status,
        "actor_type": actor_type.value,
        "performed_by": actor_id if actor_id is not None else actor.user_id,
        "performed_by_name": actor.name,
        "remarks": remarks, "ip_address": ctx.get("client_ip"),
    })


def check_transition(document: Document, new_status: DocumentVerificationStatus) -> DocumentVerificationStatus:
    """Return the current status, or raise 409 if ``new_status`` is not reachable from it."""
    previous = DocumentVerificationStatus(document.verification_status)
    if new_status not in ALLOWED_TRANSITIONS[previous]:
        raise ConflictError(
            f"A document cannot move from '{previous.value}' to '{new_status.value}'",
            data={"from": previous.value, "to": new_status.value,
                  "allowed": sorted(s.value for s in ALLOWED_TRANSITIONS[previous])},
        )
    return previous


async def transition(
    db: AsyncSession, document: Document, new_status: DocumentVerificationStatus, *,
    action: DocumentAuditAction | None = None, actor_id: int | None = None,
    actor_type: VerificationActorType = VerificationActorType.STAFF, remarks: str | None = None,
) -> Document:
    previous = check_transition(document, new_status)
    document.verification_status = new_status.value
    document.is_verified = new_status is _S.VERIFIED
    await db.flush()
    await record_event(
        db, document, action=action or _ACTION_FOR[new_status], previous_status=previous.value,
        new_status=new_status.value, actor_id=actor_id, actor_type=actor_type, remarks=remarks,
    )
    return document


# ── the reviewer's actions ──────────────────────────────────────────────────

async def submit_for_review(db: AsyncSession, document: Document, *, actor_id: int | None = None,
                            remarks: str | None = None) -> Document:
    return await transition(db, document, _S.IN_REVIEW, actor_id=actor_id, remarks=remarks)


async def verify(db: AsyncSession, document: Document, req: schema.VerifyRequest, *,
                 actor_id: int | None = None) -> Document:
    check_transition(document, _S.VERIFIED)
    if not is_complete(document.document_type, (f.page_side for f in document.files)):
        raise DocumentRuleError(
            "The document is incomplete and cannot be verified",
            data={"requires_front_and_back": document.document_type.requires_front_and_back},
        )
    # Not VerificationMixin.mark_verified(): it also writes verification_status,
    # and transition() must remain the only place the status changes.
    document.verification_method = req.method.value
    document.verification_data = req.provider_payload
    document.verified_by = actor_id if actor_id is not None else current_actor().user_id
    document.verified_at = datetime.now(UTC)
    document.rejection_reason = None
    document.third_party_verification_provider = req.third_party_provider
    document.third_party_verification_reference_id = req.third_party_reference_id
    document.third_party_verification_cost_inr = req.third_party_cost_inr
    return await transition(db, document, _S.VERIFIED, actor_id=actor_id, remarks=req.remarks)


async def reject(db: AsyncSession, document: Document, reason: str, *, actor_id: int | None = None) -> Document:
    check_transition(document, _S.REJECTED)
    document.rejection_reason = reason
    document.verified_by = None
    document.verified_at = None
    return await transition(db, document, _S.REJECTED, actor_id=actor_id, remarks=reason)


async def request_resubmission(db: AsyncSession, document: Document, reason: str, *,
                               actor_id: int | None = None) -> Document:
    check_transition(document, _S.RESUBMISSION_REQUIRED)
    document.rejection_reason = reason
    return await transition(db, document, _S.RESUBMISSION_REQUIRED, actor_id=actor_id, remarks=reason)


# ── expiry ──────────────────────────────────────────────────────────────────

async def expire_due_documents(db: AsyncSession, *, today: date | None = None) -> int:
    """Move every verified document past its ``expiry_date`` to ``expired``.

    Run daily by Celery (``app.tasks.documents.expire_due_documents``), in system
    scope — so across tenants. Returns how many documents expired.
    """
    today = today or datetime.now(UTC).date()
    due = (await db.scalars(
        select(Document).where(
            Document.verification_status == _S.VERIFIED.value,
            Document.expiry_date.is_not(None),
            Document.expiry_date < today,
        )
    )).unique().all()
    for document in due:
        await transition(
            db, document, _S.EXPIRED, actor_type=VerificationActorType.SYSTEM,
            remarks=f"Expired on {document.expiry_date.isoformat()}",
        )
    if due:
        logger.info("documents_expired", count=len(due))
    return len(due)
