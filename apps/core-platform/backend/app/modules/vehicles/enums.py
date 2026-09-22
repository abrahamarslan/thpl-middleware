"""Vocabularies for the vehicle module (Motor Vehicles Act, 1988 compliance)."""

from __future__ import annotations

import enum


class VehicleType(str, enum.Enum):
    """Form factor. Fuel is separate — an electric two-wheeler is TWO_WHEELER + fuel=electric."""

    BICYCLE = "bicycle"
    TWO_WHEELER = "two_wheeler"
    THREE_WHEELER = "three_wheeler"
    FOUR_WHEELER_LIGHT = "four_wheeler_light"
    FOUR_WHEELER_HEAVY = "four_wheeler_heavy"
    VAN = "van"
    OTHER = "other"


class VehicleOwnershipType(str, enum.Enum):
    SELF_OWNED = "self_owned"
    COMPANY_OWNED = "company_owned"
    LEASED = "leased"
    THIRD_PARTY = "third_party"


class FuelType(str, enum.Enum):
    PETROL = "petrol"
    DIESEL = "diesel"
    CNG = "cng"
    LPG = "lpg"
    ELECTRIC = "electric"
    HYBRID = "hybrid"


class VehicleStatus(str, enum.Enum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEREGISTERED = "deregistered"
    BLACKLISTED = "blacklisted"


class VehicleComplianceType(str, enum.Enum):
    REGISTRATION_CERTIFICATE = "registration_certificate"   # RC
    INSURANCE = "insurance"
    FITNESS_CERTIFICATE = "fitness_certificate"
    PUC = "puc"
    ROAD_TAX = "road_tax"
    PERMIT = "permit"
    VLTD = "vltd"
    SPEED_GOVERNOR = "speed_governor"
    HSRP = "hsrp"


class InsuranceType(str, enum.Enum):
    THIRD_PARTY = "third_party"
    COMPREHENSIVE = "comprehensive"
    PACKAGE = "package"


class PermitType(str, enum.Enum):
    NATIONAL_PERMIT = "national_permit"
    STATE_PERMIT = "state_permit"
    LOCAL_PERMIT = "local_permit"
    PRIVATE = "private"
    COMMERCIAL = "commercial"
    TOURIST = "tourist"


class ComplianceDocStatus(str, enum.Enum):
    """Certificate *validity* (distinct from the scan's verification state)."""

    VALID = "valid"
    EXPIRED = "expired"
    PENDING_RENEWAL = "pending_renewal"
    NOT_REQUIRED = "not_required"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = [
    "ComplianceDocStatus",
    "FuelType",
    "InsuranceType",
    "PermitType",
    "VehicleComplianceType",
    "VehicleOwnershipType",
    "VehicleStatus",
    "VehicleType",
    "values",
]
