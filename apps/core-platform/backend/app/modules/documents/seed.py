"""The ``document_types`` catalog — seed data and the idempotent seeder.

The catalog is DATA (compliance adds or retires a type without a code deploy).
This module holds the starting set; ``seed_document_types`` inserts what is
missing and NEVER overwrites a row that already exists, so an operator's edit
(a renamed type, a changed requirement, a deactivation) survives a re-seed.
Correcting an existing row is a data migration, not a re-seed.

Uses a lightweight Core table, not the ORM model, so the seeder keeps working
from an old migration after the model has grown new columns.

Called from the migration that creates the table and from ``scripts/seed.py``.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.modules.documents.enums import DocumentPurpose, PersonnelType, Requirement

#: Generic file attachments (email attachments, exports, scans with no
#: compliance meaning) are documents of this type. Never a checklist item.
GENERAL_TYPE_CODE = "GENERAL"

_KEYS = tuple(p.value for p in PersonnelType)


def _req(mandatory: set[str], not_applicable: set[str] | None = None,
         extra_mandatory: set[str] | None = None) -> dict[str, str]:
    """Build an ``agent_type_requirement`` map; anything unnamed is optional."""
    na = not_applicable or set()
    return {
        k: (
            Requirement.NOT_APPLICABLE.value if k in na
            else Requirement.MANDATORY.value if (k in mandatory or (extra_mandatory and k in extra_mandatory))
            else Requirement.OPTIONAL.value
        )
        for k in _KEYS
    }


_MANDATORY_ALL = _req(
    {"delivery_agent", "driver", "helper", "supervisor", "hub_manager", "hub_staff",
     "third_party_vendor_staff", "other"},
    not_applicable={"fleet_owner"},
)

# Driving/vehicle documents: required only for drivers (and the fleet owners
# who own the vehicles); not applicable to pure helper/supervisor/manager roles.
_DRIVER_AND_FLEET_ONLY = _req(
    {"driver", "fleet_owner"},
    not_applicable={"delivery_agent", "helper", "supervisor", "hub_manager", "hub_staff", "other"},
    extra_mandatory=set(),
)

_OPTIONAL_INDIVIDUAL = _req(set(), not_applicable={"fleet_owner"})

_ENTITY_ONLY = _req({"fleet_owner"}, not_applicable={
    "delivery_agent", "driver", "helper", "supervisor", "hub_manager", "hub_staff",
    "third_party_vendor_staff", "other"})

_NOT_APPLICABLE_ALL = {k: Requirement.NOT_APPLICABLE.value for k in _KEYS}

_P = DocumentPurpose

#: The starting catalog, in display order (``sort_order`` follows the position).
#: Two-sided types are ONE logical type; the sides are files of one document.
SEED_DOCUMENT_TYPES: list[dict[str, Any]] = [
    # -- Generic ------------------------------------------------------------
    dict(code=GENERAL_TYPE_CODE, display_name="General document", category=_P.OTHER,
         description="Any file with no compliance meaning (attachments, exports, scans)",
         agent_type_requirement=_NOT_APPLICABLE_ALL),

    # -- Identity -----------------------------------------------------------
    dict(code="AADHAAR", display_name="Aadhaar Card", category=_P.IDENTITY_PROOF,
         requires_front_and_back=True, has_expiry=False, allows_full_number_storage=False,
         agent_type_requirement=_MANDATORY_ALL,
         regulatory_reference="Aadhaar Act 2016; UIDAI masking circular -- store masked copy + last 4 digits only"),
    dict(code="PAN_CARD", display_name="PAN Card", category=_P.IDENTITY_PROOF,
         has_expiry=False, agent_type_requirement=_MANDATORY_ALL,
         regulatory_reference="Income Tax Act -- required for TDS on payouts above threshold"),
    dict(code="VOTER_ID", display_name="Voter ID Card", category=_P.IDENTITY_PROOF,
         has_expiry=False, agent_type_requirement=_OPTIONAL_INDIVIDUAL),
    dict(code="PASSPORT", display_name="Passport", category=_P.IDENTITY_PROOF,
         has_expiry=True, default_validity_days=3650, agent_type_requirement=_OPTIONAL_INDIVIDUAL),
    dict(code="PASSPORT_PHOTOGRAPH", display_name="Recent Passport-size Photograph",
         category=_P.PHOTOGRAPH, has_expiry=True, default_validity_days=730,
         agent_type_requirement=_MANDATORY_ALL,
         regulatory_reference="Used for ID card issuance and liveness/face-match baseline"),

    # -- Address ------------------------------------------------------------
    dict(code="ADDRESS_PROOF", display_name="Address Proof (utility bill / rent agreement / bank statement)",
         category=_P.ADDRESS_PROOF, has_expiry=True, default_validity_days=90,
         agent_type_requirement=_MANDATORY_ALL),

    # -- Driving / Vehicle (drivers + fleet only) ---------------------------
    dict(code="DRIVING_LICENSE", display_name="Driving License", category=_P.IDENTITY_PROOF,
         requires_front_and_back=True, has_expiry=True, agent_type_requirement=_DRIVER_AND_FLEET_ONLY,
         regulatory_reference="Motor Vehicles Act 1988 s.3 -- commercial (transport) DL required for drivers"),
    dict(code="VEHICLE_RC", display_name="Vehicle Registration Certificate (RC)",
         category=_P.VEHICLE_COMPLIANCE, has_expiry=True, default_validity_days=5475,
         agent_type_requirement=_DRIVER_AND_FLEET_ONLY),
    dict(code="VEHICLE_INSURANCE", display_name="Vehicle Insurance Certificate",
         category=_P.VEHICLE_COMPLIANCE, has_expiry=True, default_validity_days=365,
         agent_type_requirement=_DRIVER_AND_FLEET_ONLY,
         regulatory_reference="Motor Vehicles Act 1988 s.146 -- third-party insurance is mandatory"),
    dict(code="VEHICLE_PUC", display_name="Pollution Under Control (PUC) Certificate",
         category=_P.VEHICLE_COMPLIANCE, has_expiry=True, default_validity_days=180,
         agent_type_requirement=_DRIVER_AND_FLEET_ONLY),
    dict(code="VEHICLE_FITNESS_CERTIFICATE", display_name="Vehicle Fitness Certificate",
         category=_P.VEHICLE_COMPLIANCE, has_expiry=True, default_validity_days=730,
         agent_type_requirement=_DRIVER_AND_FLEET_ONLY,
         regulatory_reference="Required for commercial/transport vehicles under Motor Vehicles Act"),
    dict(code="VEHICLE_PERMIT", display_name="Commercial Vehicle Permit",
         category=_P.VEHICLE_COMPLIANCE, has_expiry=True, default_validity_days=1825,
         agent_type_requirement=_DRIVER_AND_FLEET_ONLY),
    dict(code="VEHICLE_OWNER_NOC", display_name="No-Objection Certificate from Vehicle Owner",
         category=_P.VEHICLE_COMPLIANCE, has_expiry=False,
         agent_type_requirement=_req({"driver"}, not_applicable={
             "helper", "supervisor", "hub_manager", "hub_staff", "other"}),
         regulatory_reference="Required only when ownership_type != self_owned"),

    # -- Bank ---------------------------------------------------------------
    dict(code="BANK_PASSBOOK_OR_CANCELLED_CHEQUE", display_name="Bank Passbook / Cancelled Cheque",
         category=_P.BANK_PROOF, has_expiry=False, agent_type_requirement=_MANDATORY_ALL),

    # -- Background / Police ------------------------------------------------
    dict(code="POLICE_VERIFICATION_CERTIFICATE", display_name="Police Verification Certificate",
         category=_P.BACKGROUND_VERIFICATION, has_expiry=True, default_validity_days=1095,
         agent_type_requirement=_MANDATORY_ALL,
         regulatory_reference="Commonly mandated by state police acts for door-to-door delivery/courier personnel"),
    dict(code="BGV_CONSENT_FORM", display_name="Background Verification Consent Form",
         category=_P.CONSENT_PROOF, has_expiry=False, agent_type_requirement=_MANDATORY_ALL),

    # -- Employment / training ----------------------------------------------
    dict(code="EMPLOYMENT_AGREEMENT", display_name="Signed Employment / Engagement Agreement",
         category=_P.EMPLOYMENT_PROOF, has_expiry=False, agent_type_requirement=_MANDATORY_ALL),
    dict(code="EDUCATIONAL_CERTIFICATE", display_name="Highest Educational Qualification Certificate",
         category=_P.EMPLOYMENT_PROOF, has_expiry=False,
         agent_type_requirement=_req({"supervisor", "hub_manager"}, not_applicable={"fleet_owner"})),
    dict(code="TRAINING_COMPLETION_CERTIFICATE", display_name="Onboarding/Safety Training Completion Certificate",
         category=_P.TRAINING_COMPLIANCE, has_expiry=True, default_validity_days=365,
         agent_type_requirement=_MANDATORY_ALL),
    dict(code="SAFETY_GEAR_ACKNOWLEDGEMENT",
         display_name="Safety Gear (helmet/reflective jacket) Issuance Acknowledgement",
         category=_P.TRAINING_COMPLIANCE, has_expiry=False,
         agent_type_requirement=_req({"delivery_agent", "driver", "helper", "third_party_vendor_staff"},
                                     not_applicable={"fleet_owner"})),
    dict(code="MEDICAL_FITNESS_CERTIFICATE", display_name="Medical Fitness Certificate",
         category=_P.MEDICAL_PROOF, has_expiry=True, default_validity_days=365,
         agent_type_requirement=_req({"driver"}, not_applicable={
             "supervisor", "hub_manager", "hub_staff", "fleet_owner", "other"})),

    # -- Statutory IDs ------------------------------------------------------
    dict(code="UAN_PROOF", display_name="UAN (EPFO) Proof", category=_P.EMPLOYMENT_PROOF, has_expiry=False,
         agent_type_requirement=_req({"supervisor", "hub_manager"}, not_applicable={"fleet_owner"}),
         regulatory_reference="Applicable to full_time_employee / part_time_employee, not gig_worker"),
    dict(code="ESIC_CARD", display_name="ESIC Card", category=_P.EMPLOYMENT_PROOF, has_expiry=False,
         agent_type_requirement=_req({"supervisor", "hub_manager"}, not_applicable={"fleet_owner"})),
    dict(code="E_SHRAM_REGISTRATION_PROOF", display_name="e-Shram Registration Proof",
         category=_P.STATUTORY_COMPLIANCE, has_expiry=False,
         agent_type_requirement=_MANDATORY_ALL,
         regulatory_reference="Code on Social Security 2020 / Social Security (Central) Rules 2026 -- "
                              "gig/platform worker registration on the central portal"),

    # -- Entity-level (only for fleet/franchise partners, not individuals) --
    dict(code="GST_CERTIFICATE", display_name="GST Registration Certificate",
         category=_P.ENTITY_PROOF, has_expiry=False, agent_type_requirement=_ENTITY_ONLY),
    dict(code="CIN_CERTIFICATE", display_name="Certificate of Incorporation (CIN)",
         category=_P.ENTITY_PROOF, has_expiry=False, agent_type_requirement=_ENTITY_ONLY),
    dict(code="FLEET_PARTNER_AGREEMENT", display_name="Fleet Partner / Vendor Agreement",
         category=_P.ENTITY_PROOF, has_expiry=True, default_validity_days=365,
         agent_type_requirement=_ENTITY_ONLY,
         regulatory_reference="Signed contract with a third-party fleet/staffing vendor "
                              "(replaces a raw agreement_storage_key on fleet_partners)"),
]

_DEFAULTS: dict[str, Any] = dict(
    description=None, requires_front_and_back=False, has_expiry=False, default_validity_days=None,
    allows_full_number_storage=True, regulatory_reference=None,
)

#: The columns this seeder writes — a frozen set on purpose: it must keep
#: working on a database that has not yet received later columns.
_TABLE = sa.table(
    "document_types",
    sa.column("code", sa.String), sa.column("display_name", sa.String), sa.column("category", sa.String),
    sa.column("description", sa.Text), sa.column("requires_front_and_back", sa.Boolean),
    sa.column("has_expiry", sa.Boolean), sa.column("default_validity_days", sa.Integer),
    sa.column("allows_full_number_storage", sa.Boolean), sa.column("agent_type_requirement", JSONB),
    sa.column("regulatory_reference", sa.Text), sa.column("sort_order", sa.Integer),
)


def catalog() -> list[dict[str, Any]]:
    """The seed rows, normalised: defaults filled, enums as their string
    values, ``sort_order`` from the list position."""
    rows = []
    for position, spec in enumerate(SEED_DOCUMENT_TYPES, start=1):
        row = {**_DEFAULTS, **spec}
        row["category"] = DocumentPurpose(row["category"]).value
        row["sort_order"] = position * 10
        rows.append(row)
    return rows


def seed_document_types(conn: Connection) -> int:
    """Insert the catalog rows that are missing; return how many were added."""
    stmt = pg_insert(_TABLE).values(catalog()).on_conflict_do_nothing(index_elements=["code"])
    return conn.execute(stmt).rowcount or 0
