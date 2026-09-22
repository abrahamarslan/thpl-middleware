"""Vocabularies for the HR / employment module."""

from __future__ import annotations

import enum


class PersonnelType(str, enum.Enum):
    SUPERVISOR = "supervisor"
    HUB_MANAGER = "hub_manager"
    THIRD_PARTY_VENDOR_STAFF = "third_party_vendor_staff"
    DELIVERY_AGENT = "delivery_agent"
    DRIVER = "driver"
    HELPER = "helper"
    HUB_STAFF = "hub_staff"
    FLEET_OWNER = "fleet_owner"
    OTHER = "other"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    FIX_TERM_CONTRACT = "fixed_term_contract"
    THIRD_PARTY_VENDOR_CONTRACTED = "third_party_vendor_contracted"
    APPRENTICE = "apprentice"
    GIG_PLATFORM_WORKER = "gig_platform_worker"
    CONTRACT_STAFFING = "contract_staffing"
    THIRD_PARTY_FLEET_VENDOR = "third_party_fleet_vendor"
    TRAINEE = "trainee"


class EmploymentStatus(str, enum.Enum):
    PENDING_ONBOARDING = "pending_onboarding"
    ONBOARDING = "onboarding"
    ON_PROBATION = "on_probation"
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    SUSPENDED = "suspended"
    RESIGNED = "resigned"
    TERMINATED = "terminated"
    ABSCONDED = "absconded"
    BLACKLISTED = "blacklisted"


class OnboardingStage(str, enum.Enum):
    REGISTERED = "registered"
    DOCUMENT_UPLOAD_PENDING = "document_upload_pending"
    DOCUMENT_UNDER_REVIEW = "document_under_review"
    DOCUMENT_RESUBMISSION_REQUIRED = "document_resubmission_required"
    BACKGROUND_VERIFICATION_PENDING = "background_verification_pending"
    BACKGROUND_VERIFICATION_FAILED = "background_verification_failed"
    TRAINING_PENDING = "training_pending"
    TRAINING_COMPLETED = "training_completed"
    FINAL_APPROVAL_PENDING = "final_approval_pending"
    ACTIVE = "active"
    REJECTED = "rejected"


class WorkLocationType(str, enum.Enum):
    HUB_BASED = "hub_based"
    FIELD_BASED = "field_based"
    HYBRID = "hybrid"


class WorkerCategory(str, enum.Enum):
    TRADITIONAL_EMPLOYEE = "traditional_employee"
    GIG_WORKER = "gig_worker"
    PLATFORM_WORKER = "platform_worker"


class EshramRegistrationStatus(str, enum.Enum):
    NOT_REGISTERED = "not_registered"
    SELF_REGISTERED = "self_registered"
    AGGREGATOR_REGISTERED = "aggregator_registered"
    UAN_VERIFIED = "uan_verified"


class AggregatorSyncStatus(str, enum.Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class GigBenefitEligibilityStatus(str, enum.Enum):
    NOT_ELIGIBLE = "not_eligible"
    THRESHOLD_IN_PROGRESS = "threshold_in_progress"
    ELIGIBLE_PENDING_ENROLLMENT = "eligible_pending_enrollment"
    ENROLLED = "enrolled"


class BankAccountType(str, enum.Enum):
    SAVINGS = "savings"
    CURRENT = "current"


class BankVerificationMethod(str, enum.Enum):
    PENNY_DROP = "penny_drop"
    CANCELLED_CHEQUE = "cancelled_cheque"
    PASSBOOK_STATEMENT = "passbook_statement"
    BANK_API = "bank_api"
    MANUAL_REVIEW = "manual_review"


class BankVerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    NAME_MISMATCH = "name_mismatch"
    FAILED = "failed"


class BankAccountOwnerType(str, enum.Enum):
    USER = "user"
    FLEET_PARTNER = "fleet_partner"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = [
    "AggregatorSyncStatus",
    "BankAccountOwnerType",
    "BankAccountType",
    "BankVerificationMethod",
    "BankVerificationStatus",
    "EmploymentStatus",
    "EmploymentType",
    "EshramRegistrationStatus",
    "GigBenefitEligibilityStatus",
    "OnboardingStage",
    "PersonnelType",
    "WorkLocationType",
    "WorkerCategory",
    "values",
]
