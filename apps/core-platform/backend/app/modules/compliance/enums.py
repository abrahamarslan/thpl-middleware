"""Vocabularies for the compliance module (DPDP Act, 2023)."""

from __future__ import annotations

import enum


class ConsentType(str, enum.Enum):
    AADHAAR_EKYC = "aadhaar_ekyc"
    AADHAAR_OFFLINE_EKYC = "aadhaar_offline_ekyc"
    DPDP_DATA_PROCESSING = "dpdp_data_processing"
    BIOMETRIC_CAPTURE = "biometric_capture"
    BACKGROUND_VERIFICATION = "background_verification"
    POLICE_VERIFICATION = "police_verification"
    LOCATION_TRACKING = "location_tracking"
    TERMS_OF_SERVICE = "terms_of_service"
    MARKETING_COMMUNICATIONS = "marketing_communications"


class ConsentChannel(str, enum.Enum):
    MOBILE_APP = "mobile_app"
    WEB_PORTAL = "web_portal"
    PAPER_FORM = "paper_form"


class RetentionAction(str, enum.Enum):
    """What a purge/anonymize job does once a record's retention period lapses."""

    DELETE = "delete"
    ANONYMIZE = "anonymize"


class DataPrincipalRequestType(str, enum.Enum):
    """DPDP Act, 2023 data-principal rights that must be serviced within SLA."""

    ACCESS = "access"
    CORRECTION = "correction"
    ERASURE = "erasure"
    GRIEVANCE = "grievance"
    NOMINATION = "nomination"


class DataPrincipalRequestStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class AuditEntityType(str, enum.Enum):
    """Starter set of entity types for ``kyc_audit_logs.entity_type``.

    The column is an open String (treated as DATA); this enum is the canonical
    vocabulary the code emits, not a closed database constraint.
    """

    USER = "user"
    KYC_PROFILE = "kyc_profile"
    AADHAAR_VERIFICATION = "aadhaar_verification"
    PAN_VERIFICATION = "pan_verification"
    CONSENT_RECORD = "consent_record"
    BACKGROUND_VERIFICATION = "background_verification"
    MEDICAL_FITNESS_CERTIFICATE = "medical_fitness_certificate"
    TRAINING_CERTIFICATION = "training_certification"
    BANK_ACCOUNT = "bank_account"
    EMPLOYMENT_RECORD = "employment_record"
    GIG_WORKER_REGISTRATION = "gig_worker_registration"
    DATA_PRINCIPAL_REQUEST = "data_principal_request"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = [
    "AuditEntityType",
    "ConsentChannel",
    "ConsentType",
    "DataPrincipalRequestStatus",
    "DataPrincipalRequestType",
    "RetentionAction",
    "values",
]
