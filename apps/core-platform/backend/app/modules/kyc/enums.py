"""Vocabularies for the KYC / verification module."""

from __future__ import annotations

import enum


# ---------------------------------------------------------------------------
# KYC cycle
# ---------------------------------------------------------------------------
class KYCType(str, enum.Enum):
    INITIAL = "initial"
    PERIODIC_RE_KYC = "periodic_re_kyc"
    TRIGGERED_RE_KYC = "triggered_re_kyc"
    ADDRESS_UPDATE = "address_update"


class KYCVerificationLevel(str, enum.Enum):
    BASIC = "basic"
    STANDARD = "standard"
    ENHANCED = "enhanced"


class KYCStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"
    RE_KYC_REQUIRED = "re_kyc_required"


class KYCRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SubVerificationStatus(str, enum.Enum):
    """Outcome of a sub-verification (shared by KYC sub-checks and driving licenses)."""

    NOT_STARTED = "not_started"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    MANUAL_OVERRIDE = "manual_override"


class AadhaarVerificationMethod(str, enum.Enum):
    OFFLINE_EKYC_XML = "offline_ekyc_xml"
    DIGILOCKER = "digilocker"
    OKYC_OTP = "okyc_otp"
    QR_CODE_VERIFICATION = "qr_code_verification"
    CVL_KRA = "cvl_kra"
    MANUAL_DOCUMENT_UPLOAD = "manual_document_upload"


class PANVerificationSource(str, enum.Enum):
    PROTEAN_NSDL_API = "protean_nsdl_api"
    INCOME_TAX_EFILING_API = "income_tax_efiling_api"
    THIRD_PARTY_KYC_PROVIDER = "third_party_kyc_provider"
    MANUAL_DOCUMENT_UPLOAD = "manual_document_upload"


class PANType(str, enum.Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


# ---------------------------------------------------------------------------
# Background verification
# ---------------------------------------------------------------------------
class BGVType(str, enum.Enum):
    POLICE_VERIFICATION_CERTIFICATE = "police_verification_certificate"
    THIRD_PARTY_BGV_AGENCY_CHECK = "third_party_bgv_agency_check"
    CRIMINAL_RECORD_CHECK = "criminal_record_check"
    REFERENCE_CHECK = "reference_check"
    ADDRESS_VERIFICATION_FIELD_VISIT = "address_verification_field_visit"
    PREVIOUS_EMPLOYMENT_VERIFICATION = "previous_employment_verification"


class BGVStatus(str, enum.Enum):
    NOT_INITIATED = "not_initiated"
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    CLEAR = "clear"
    DISCREPANCY_FOUND = "discrepancy_found"
    ADVERSE = "adverse"
    INCONCLUSIVE = "inconclusive"
    EXPIRED = "expired"


class BGVCheckStatus(str, enum.Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    INCONCLUSIVE = "inconclusive"
    MANUAL_OVERRIDE = "manual_override"


# ---------------------------------------------------------------------------
# Medical & training
# ---------------------------------------------------------------------------
class MedicalCertificateType(str, enum.Enum):
    DRIVING_FITNESS_FORM_1A = "driving_fitness_form_1a"
    GENERAL_MEDICAL_FITNESS = "general_medical_fitness"
    EYE_TEST_CERTIFICATE = "eye_test_certificate"


class MedicalCertificateStatus(str, enum.Enum):
    VALID = "valid"
    EXPIRED = "expired"
    PENDING_RENEWAL = "pending_renewal"


class TrainingType(str, enum.Enum):
    APP_USAGE_INDUCTION = "app_usage_induction"
    ROAD_SAFETY = "road_safety"
    DEFENSIVE_DRIVING = "defensive_driving"
    GOODS_HANDLING_SOP = "goods_handling_sop"
    FIRST_AID = "first_aid"
    POSH_WORKPLACE_CONDUCT = "posh_workplace_conduct"
    DATA_PRIVACY_AWARENESS = "data_privacy_awareness"


class TrainingStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = [
    "AadhaarVerificationMethod",
    "BGVCheckStatus",
    "BGVStatus",
    "BGVType",
    "KYCStatus",
    "KYCType",
    "KYCVerificationLevel",
    "KYCRiskLevel",
    "MedicalCertificateStatus",
    "MedicalCertificateType",
    "PANType",
    "PANVerificationSource",
    "SubVerificationStatus",
    "TrainingStatus",
    "TrainingType",
    "values",
]
