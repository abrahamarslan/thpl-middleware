"""Vocabularies for the document module (docs/documents/README.md).

The document *vocabulary* is data-driven: the canonical set of document types
lives in the ``document_types`` table, NOT in a Python enum, so compliance can
add or retire a type with a seed/data migration instead of a schema migration
and a code deploy. What IS closed, and guarded by a CHECK constraint, is
everything the code branches on — purposes, page sides, lifecycle states,
verification methods, link roles, storage providers.
"""

from __future__ import annotations

import enum


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum, so the
    constraint and the vocabulary can never drift apart."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


# ── the catalog ─────────────────────────────────────────────────────────────

class DocumentPurpose(str, enum.Enum):
    """The category taxonomy ``document_types.category`` (and the denormalised
    ``documents.document_purpose``) draw from."""

    IDENTITY_PROOF = "identity_proof"
    ADDRESS_PROOF = "address_proof"
    AGE_PROOF = "age_proof"
    BANK_PROOF = "bank_proof"
    EMPLOYMENT_PROOF = "employment_proof"
    VEHICLE_COMPLIANCE = "vehicle_compliance"
    BANKING = "banking"
    EMPLOYMENT_RECORD = "employment_record"
    BACKGROUND_VERIFICATION = "background_verification"
    TRAINING_COMPLIANCE = "training_compliance"
    CONSENT_PROOF = "consent_proof"              # BGV / DPDP consent forms
    STATUTORY_COMPLIANCE = "statutory_compliance"
    ENTITY_PROOF = "entity_proof"                # GST/CIN of a fleet/franchise entity, not an individual
    MEDICAL_PROOF = "medical_proof"              # driving / general medical-fitness certificates
    PHOTOGRAPH = "photograph"                    # selfie/liveness + passport-photograph files
    OTHER = "other"


class PersonnelType(str, enum.Enum):
    """The keys of ``document_types.agent_type_requirement``.

    Defined here because the users module does not model personnel yet; move
    it there when it does — the catalog only depends on the string values.
    """

    DELIVERY_AGENT = "delivery_agent"
    DRIVER = "driver"
    HELPER = "helper"
    SUPERVISOR = "supervisor"
    HUB_MANAGER = "hub_manager"
    HUB_STAFF = "hub_staff"
    FLEET_OWNER = "fleet_owner"
    THIRD_PARTY_VENDOR_STAFF = "third_party_vendor_staff"
    OTHER = "other"


class Requirement(str, enum.Enum):
    """The values of ``document_types.agent_type_requirement[<personnel type>]``."""

    MANDATORY = "mandatory"
    OPTIONAL = "optional"
    NOT_APPLICABLE = "not_applicable"


# ── one logical document, many files ────────────────────────────────────────

class DocumentPageSide(str, enum.Enum):
    FRONT = "front"
    BACK = "back"
    SINGLE_PAGE = "single_page"
    EXTRA_PAGE = "extra_page"
    NOT_APPLICABLE = "not_applicable"


class FileProcessingStatus(str, enum.Enum):
    """State of the per-file pipeline (virus scan, OCR extraction)."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class FileStorageProvider(str, enum.Enum):
    S3 = "s3"
    GCS = "gcs"
    AZURE_BLOB = "azure_blob"
    LOCAL_DISK = "local_disk"


class SourceChannel(str, enum.Enum):
    MOBILE_APP = "mobile_app"                    # FieldMate / partner app
    WEB_PORTAL = "web_portal"
    ADMIN_UPLOAD = "admin_upload"
    FIELD_AGENT_ASSISTED_UPLOAD = "field_agent_assisted_upload"


# ── what a document belongs to ──────────────────────────────────────────────

class DocumentLinkableType(str, enum.Enum):
    """Polymorphic target class for a ``document_links`` row (``linkable_type``).

    The pivot is the single truth of "what this logical document belongs to",
    so one document can be linked to several entities (a vehicle RC scan to
    the vehicle *and* its owner user). Names are the snake_case of the owning
    model class (``Email`` → ``email``), which is what ``HasDocumentsMixin``
    derives. Open at the DATABASE level (no CHECK) so a new owner class needs
    no migration; the API validates against this list.
    """

    USER = "user"
    VEHICLE = "vehicle"
    INVOICE = "invoice"
    CUSTOMER = "customer"
    ORGANIZATION = "organization"
    HUB = "hub"
    BRAND_OWNER = "brand_owner"
    EMAIL = "email"
    OTHER = "other"


class DocumentLinkRole(str, enum.Enum):
    """WHAT KIND of link a ``document_links`` row is.

    ``owner`` is the KYC subject the document is *about* (at most one per
    document); the others attach or reference the same logical document.
    """

    OWNER = "owner"
    ATTACHMENT = "attachment"
    EVIDENCE = "evidence"
    REFERENCE = "reference"
    VERSION_OF = "version_of"


# ── verification lifecycle ──────────────────────────────────────────────────

class DocumentVerificationStatus(str, enum.Enum):
    NOT_UPLOADED = "not_uploaded"
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"
    RESUBMISSION_REQUIRED = "resubmission_required"


_S = DocumentVerificationStatus

#: Where a document row may go from each state. A resubmission is NOT a
#: transition: it creates a new version (a new row, ``supersedes_document_id``)
#: that starts at ``uploaded``, and leaves the old row as evidence.
ALLOWED_TRANSITIONS: dict[DocumentVerificationStatus, frozenset[DocumentVerificationStatus]] = {
    _S.NOT_UPLOADED: frozenset({_S.PENDING_UPLOAD, _S.UPLOADED}),
    _S.PENDING_UPLOAD: frozenset({_S.UPLOADED}),
    _S.UPLOADED: frozenset({_S.IN_REVIEW, _S.VERIFIED, _S.REJECTED}),
    _S.IN_REVIEW: frozenset({_S.VERIFIED, _S.REJECTED, _S.RESUBMISSION_REQUIRED}),
    _S.VERIFIED: frozenset({_S.EXPIRED, _S.REJECTED, _S.IN_REVIEW}),
    _S.REJECTED: frozenset({_S.RESUBMISSION_REQUIRED}),
    _S.EXPIRED: frozenset({_S.RESUBMISSION_REQUIRED}),
    _S.RESUBMISSION_REQUIRED: frozenset(),
}


class DocumentVerificationMethod(str, enum.Enum):
    MANUAL_REVIEW = "manual_review"
    OCR_AUTO_EXTRACT = "ocr_auto_extract"
    THIRD_PARTY_API = "third_party_api"            # Digilocker, NSDL, Karza, IDfy, HyperVerge, Signzy
    PARIVAHAN_API = "parivahan_api"                # RTO / DL / RC verification via Parivahan/Vahan
    AADHAAR_OFFLINE_EKYC = "aadhaar_offline_ekyc"  # UIDAI offline XML/OTP flow, no full number ever seen


# ── audit trail ─────────────────────────────────────────────────────────────

class VerificationActorType(str, enum.Enum):
    STAFF = "staff"
    SYSTEM = "system"
    THIRD_PARTY_WEBHOOK = "third_party_webhook"


class DocumentAuditAction(str, enum.Enum):
    UPLOADED = "uploaded"
    RESUBMITTED = "resubmitted"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    RESUBMISSION_REQUESTED = "resubmission_requested"
    EXPIRED = "expired"
    DELETED = "deleted"
    DOWNLOADED = "downloaded"                      # access log, DPDP accountability
