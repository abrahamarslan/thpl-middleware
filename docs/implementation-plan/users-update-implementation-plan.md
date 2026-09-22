# Users & DLP Domain Update — Implementation Plan

**Document Reference:** `docs/implementation-plan/users-update-implementation-plan.md`
**Status:** DRAFT (Architecture Review)
**Author:** Principal Enterprise Systems Architect
**Date:** September 2026
**Scope:** `app/modules/users/`, `app/modules/roles/`, new `app/modules/hubs/`, new `app/modules/fleet_partners/`, new `app/modules/vehicles/`; consumes `app/modules/geo/`, `app/modules/documents/`, `app/database/mixins.py`
**Companion analysis:** [`docs/analysis-report/user-new-architecture.md`](../analysis-report/user-new-architecture.md) §10–§11

---

## 1. Summary

The platform needs a coherent, organization-scoped DLP domain. This plan covers
four workstreams:

1. **Decompose user location** off the `users` master row onto the live `geo`
   hub (addresses → `geo.place_links`; reference → `geo.admin_boundaries`) plus
   a new isolated telemetry layer (`user_live_locations` + partitioned
   `user_location_pings`).
2. **Organization-scope `users` and `roles`**, with a database-enforced
   `(tenant_id, organization_id, role_id)` composite FK and a first-class
   `users.zoho_id` crosswalk.
3. **Build the two missing FK targets** the DLP schema depends on: **`hubs`**
   and **`fleet_partners`**.
4. **Build the vehicle domain** (`vehicles`, `vehicle_compliance_documents`,
   `driving_licenses`) on repository conventions.

The schema is **greenfield**: the database may be dropped and migrations
re-run, so there are **no backfill scripts, dual-writes, or rollout windows**.

---

## 2. Locked decisions (from the author)

| # | Decision | Consequence |
|---|---|---|
| 1 | **Keep `kyc_audit_logs`.** | It is the compliance ledger (cross-entity before/after); `activity_logs` stays the operational/auth trail. Document the boundary; do not merge. |
| 2 | **A police certificate is a `BackgroundVerification` of type `police_verification_certificate`.** | Drop standalone `police_verifications`; PVC fields + renewal chain live on `BackgroundVerification`. |
| 3 | **`uid_token` is required.** | Keep it; isolate it from the demographic extract (sibling table or inside the ADV). |
| 4 | **`data_retention_schedules` is application data-retention only.** | No relation to `zoho_retention_policies`. Add `retention_expiry_date` only where the purge job reads it. |
| 5 | **Backfill not mandatory — drop schema and re-run migrations.** | Greenfield build; no data migration. |
| 6 | **RBAC managed explicitly.** | No RBAC/permission modelling in this plan; roles are org-scoped as data only. |
| 7 | **Consent is a table, not a mixin.** | `consent_records` stays authoritative; add a `ConsentBoundMixin` (FK only). |
| 8 | **No polymorphic verification table.** | Record-level state = `VerificationMixin`; field-level verification stays on identity tables. |

---

## 3. Current state (evidence)

| Fact | Source |
|---|---|
| `User` is `TenantScopedMixin` (org nullable) with ~90 location columns | `app/modules/users/model.py:61`, `:203–288` |
| `users.zoho_id` exists, plain non-unique index | `model.py:299` |
| `Role` is `TenantEntityMixin`, unique `(tenant_id, code)` | `app/modules/roles/model.py:21–28` |
| No `hubs`, `fleet_partners`, or `vehicles` models exist | grep across `app/modules` |
| `geo.place_links.OWNER_TYPES` already contains `user`/`warehouse`/`organization` | `app/modules/geo/model/link.py:88–101` |
| `DocumentLinkableType` already contains `hub` and `vehicle` | `app/modules/documents/enums.py:118–126` |
| Vehicle document types (RC/Insurance/PUC/Fitness/Permit/Owner-NOC) are seeded | `app/modules/documents/seed.py:105–126` |
| `VerificationMixin` already implements who/when/how/evidence | `app/database/mixins.py:259–300` |
| Tenancy conformance test requires ENTITY/LEDGER/GLOBAL columns | `tests/test_tenancy.py:141–193` |

---

## 4. Target models

### 4.1 `users` — organization-scoped, location-free

```python
class User(MultiTenantMixin, RowVersionMixin, AppMetaMixin, DeactivationMixin, Base):
    __tablename__ = "users"

    # ... existing non-location columns unchanged ...
    primary_place_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"),
        comment="CACHE of the primary address link's place (maintained by the address service)")
    country_code: Mapped[str | None] = mapped_column(
        String(2), comment="CACHE of user_profiles.country_iso2 for list filtering")

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
        Index("uq_users_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_users_primary_place", "primary_place_id",
              postgresql_where=text("primary_place_id IS NOT NULL")),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "role_id"],
            ["roles.tenant_id", "roles.organization_id", "roles.id"],
            name="fk_users_tenant_org_role", ondelete="RESTRICT"),
        # ... existing non-location indexes ...
    )
```

- **Removed:** all postal, polygon, coordinate, geoname and telemetry columns
  (checklist in analysis §10.4), plus legacy `timezone` (owned by `user_profiles`).
- `MultiTenantMixin` supplies `organization_id NOT NULL`, `fk_users_tenant_org`,
  `ix_users_tenant_org`. The manual audit/status/deactivation columns already
  satisfy the ENTITY conformance columns.
- **`zoho_id`:** replace the plain index with `uq_users_zoho_id_live`; narrow to
  `String(50)` to match `ZohoIdentityMixin`; document the crosswalk to
  `zoho_users.zoho_id` (email fallback).

### 4.2 `roles` — organization-scoped

```python
class Role(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_roles_tenant_org_id"),
        Index("uq_roles_tenant_org_code_live", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint("status IN ('active','inactive')", name="chk_roles_status"),
    )
```

- `seed_system_roles` seeds `owner`/`admin`/`member` **per organization**
  (invoked on organization creation). `delete_role` counts holders within the
  role's organization.
- RBAC enforcement is out of scope (decision #6); `permissions` remains the
  future payload.

### 4.3 Telemetry — `user_live_locations` + `user_location_pings`

LEDGER-class (no `row_version`/`status`/audit), organization NOT NULL.

```python
class UserLiveLocation(MultiTenantMixin, AppMetaMixin, TimestampMixin, Base):
    """One row per user — last known fix. Hot, but isolated from `users`."""
    __tablename__ = "user_live_locations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_user_live_locations_user"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_user_live_locations_user", ondelete="CASCADE"),
        CheckConstraint("accuracy_m IS NULL OR accuracy_m >= 0", name="chk_user_live_accuracy"),
        CheckConstraint("heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)",
                        name="chk_user_live_heading"),
        CheckConstraint("speed_mps IS NULL OR speed_mps >= 0", name="chk_user_live_speed"),
        Index("ix_user_live_locations_org", "tenant_id", "organization_id"),
        Index("ix_user_live_locations_recorded", "tenant_id", "recorded_at"),
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    coordinates: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True))
    place_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"))
    accuracy_m / altitude_m / altitude_accuracy_m / heading_deg / speed_mps: Mapped[float | None]
    location_source: Mapped[str | None] = mapped_column(String(20))   # gps / network / manual
    is_moving: Mapped[bool | None] = mapped_column(Boolean)
    tracking_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    background_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    device_id / device_type / network_type: Mapped[str | None]
    ip_address: Mapped[str | None] = mapped_column(String(45))
    recorded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # device clock
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
```

Write path: `INSERT ... ON CONFLICT (tenant_id, user_id) DO UPDATE` — never an
ORM read-modify-write.

```python
class UserLocationPing(MultiTenantMixin, AppMetaMixin, Base):
    """Append-only history; monthly RANGE partitions on recorded_at (pg_partman)."""
    __tablename__ = "user_location_pings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_user_location_pings_user", ondelete="CASCADE"),
        PrimaryKeyConstraint("recorded_at", "id", name="pk_user_location_pings"),
        Index("ix_user_location_pings_user_time", "tenant_id", "user_id", text("recorded_at DESC")),
        {"postgresql_partition_by": "RANGE (recorded_at)"},
    )
    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    coordinates / place_id / accuracy_m / speed_mps / heading_deg / altitude_m
    location_source / device_id
    recorded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
```

Retention: a `data_retention_schedules` row (`data_category='location_history'`);
the purge action is a partition drop.

### 4.4 New module — `hubs`

A hub is the **operational** counterpart of a place (manager, capacity, zone,
cutoff). It points at a `geo.place` and a `geo.geofence`; it does not absorb
either (Design Rule Zero).

```python
# app/modules/hubs/enums.py
class HubType(str, enum.Enum):
    WAREHOUSE = "warehouse"; BRANCH = "branch"; DARK_STORE = "dark_store"
    TRANSIT = "transit"; SPOKE = "spoke"

# app/modules/hubs/model.py
class Hub(IntPKMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
          SoftDeleteFilteredMixin, HasDocumentsMixin, Base):
    __tablename__ = "hubs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_hubs_tenant_org_id"),
        Index("uq_hubs_tenant_org_code_live", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        ForeignKeyConstraint(["tenant_id", "parent_hub_id"], ["hubs.tenant_id", "hubs.id"],
                             name="fk_hubs_parent", ondelete="RESTRICT"),
        CheckConstraint(f"hub_type IN ({values(HubType)})", name="chk_hubs_type"),
        CheckConstraint("status IN ('active','suspended','archived')", name="chk_hubs_status"),
        Index("ix_hubs_parent", "tenant_id", "parent_hub_id", postgresql_where=text("parent_hub_id IS NOT NULL")),
        Index("ix_hubs_place", "place_id", postgresql_where=text("place_id IS NOT NULL")),
        Index("uq_hubs_zoho_location_live", "tenant_id", "zoho_location_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_location_id IS NOT NULL")),
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hub_type: Mapped[str] = mapped_column(String(30), nullable=False, default=HubType.WAREHOUSE.value,
                                          server_default=text("'warehouse'"))
    parent_hub_id: Mapped[int | None] = mapped_column(BigInteger)
    place_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"))
    geofence_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("geo.geofences.id", ondelete="SET NULL"))
    manager_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    contact_phone / contact_email / timezone
    operating_hours: Mapped[dict | None] = mapped_column(JSONB)
    daily_cutoff_time: Mapped[dt.time | None] = mapped_column(Time)
    storage_capacity_sqft: Mapped[float | None] = mapped_column(Numeric(10, 2))
    dock_count / vehicle_capacity: Mapped[int | None] = mapped_column(Integer)
    serviceable_pincodes: Mapped[list | None] = mapped_column(ARRAY(String))
    zoho_location_id: Mapped[str | None] = mapped_column(String(50))
    custom_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                    server_default=text("'{}'::jsonb"))
```

Also add `"hub"` to `geo.place_links.OWNER_TYPES` + CHECK migration.

### 4.5 New module — `fleet_partners`

The legal entity (or individual) that supplies vehicles/drivers; the
`fleet_partner_id` target of `vehicles` and `employment_records`.

```python
class FleetPartner(IntPKMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
                   SoftDeleteFilteredMixin, HasDocumentsMixin, Base):
    __tablename__ = "fleet_partners"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_fleet_partners_tenant_org_id"),
        Index("uq_fleet_partners_tenant_org_code_live", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_fleet_partners_pan_live", "tenant_id", "pan_masked", unique=True,
              postgresql_where=text("deleted_at IS NULL AND pan_masked IS NOT NULL")),
        Index("uq_fleet_partners_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        CheckConstraint(f"entity_type IN ({values(FleetPartnerEntityType)})",
                        name="chk_fleet_partner_entity_type"),
        CheckConstraint("status IN ('active','suspended','archived')", name="chk_fleet_partner_status"),
        CheckConstraint("contract_end_date IS NULL OR contract_start_date IS NULL "
                        "OR contract_end_date >= contract_start_date", name="chk_fleet_partner_contract"),
    )
    code / name / entity_type
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    pan_masked / pan_encrypted / gstin / cin / tan
    registered_address_place_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"))
    contact_person_name / contact_phone / contact_email
    contract_start_date / contract_end_date / commission_rate / payment_terms_days
    notes / zoho_id / custom_attributes
```

`FleetPartnerEntityType` enum: individual / proprietorship / partnership / llp /
private_limited (from the proposed vehicle schema). Proof documents via
`HasDocumentsMixin` (GST/CIN are already seeded as `ENTITY_PROOF`).

### 4.6 New module — `vehicles`

```python
class Vehicle(BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
              SoftDeleteFilteredMixin, HasDocumentsMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_vehicles_tenant_org_id"),
        Index("uq_vehicles_registration_live", "tenant_id", "registration_number", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("uq_vehicles_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        CheckConstraint(f"vehicle_type IN ({values(VehicleType)})", name="chk_vehicle_type"),
        CheckConstraint(f"ownership_type IN ({values(VehicleOwnershipType)})", name="chk_vehicle_ownership"),
        CheckConstraint(f"status IN ({values(VehicleStatus)})", name="chk_vehicle_status"),
        CheckConstraint("manufacture_year IS NULL OR manufacture_year BETWEEN 1900 AND 2100",
                        name="chk_vehicle_year"),
        Index("ix_vehicles_owner", "tenant_id", "owner_user_id"),
        Index("ix_vehicles_fleet_partner", "tenant_id", "fleet_partner_id"),
        Index("ix_vehicles_hub", "tenant_id", "hub_id"),
    )
    registration_number / chassis_number / engine_number / make / model / color
    vehicle_type / ownership_type / fuel_type          # form factor + fuel; no EV duplicates, no is_ev
    manufacture_year / load_capacity_kg / seating_capacity / battery_capacity_kwh
    owner_user_id / fleet_partner_id / hub_id
    registered_owner_name
    vltd_device_id / gps_device_id / fastag_id
    is_company_fleet
    # status/deactivation/verification come from the mixins
    rc_status_cache: Mapped[str | None] = mapped_column(String(20))
    overall_compliance_status_cache: Mapped[str | None] = mapped_column(String(20))
    zoho_id / custom_attributes
```

`VehicleComplianceDocument` (per-certificate renewal chain):

```python
class VehicleComplianceDocument(BigIntPKWithUUIDMixin, OrgEntityMixin,
                                SoftDeleteFilteredMixin, HasDocumentsMixin, Base):
    __tablename__ = "vehicle_compliance_documents"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "vehicle_id"], ["vehicles.tenant_id", "vehicles.id"],
                             name="fk_vehicle_compliance_vehicle", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "renewed_from_id"],
                             ["vehicle_compliance_documents.tenant_id", "vehicle_compliance_documents.id"],
                             name="fk_vehicle_compliance_renewed_from", ondelete="SET NULL"),
        Index("ix_vehicle_compliance_vehicle_type_status", "vehicle_id", "compliance_type", "status"),
        CheckConstraint(f"compliance_type IN ({values(VehicleComplianceType)})", name="chk_vehicle_compliance_type"),
        CheckConstraint(f"status IN ({values(ComplianceDocStatus)})", name="chk_vehicle_compliance_status"),
        CheckConstraint("valid_upto IS NULL OR valid_from IS NULL OR valid_upto >= valid_from",
                        name="chk_vehicle_compliance_validity"),
    )
    vehicle_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="SET NULL"))
    compliance_type / certificate_number
    insurer_name / insurance_type / permit_type / permit_region
    issued_date / valid_from / valid_upto
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default=ComplianceDocStatus.PENDING_RENEWAL.value)
    renewal_reminder_sent_at / renewed_from_id
```

**Key separation (analysis §11.3c):** `VehicleComplianceDocument.status` is
*certificate validity*; the authenticity of the scanned file is
`Document.verification_status` (`VerificationMixin` +
`document_verification_logs`). Do not merge them.

### 4.7 New module — `driving_licenses`

```python
class DrivingLicense(BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin,
                     SoftDeleteFilteredMixin, Base):
    __tablename__ = "driving_licenses"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_driving_licenses_user", ondelete="CASCADE"),
        Index("uq_driving_licenses_one_current", "tenant_id", "user_id", unique=True,
              postgresql_where=text("is_current AND deleted_at IS NULL")),
        CheckConstraint("valid_upto >= valid_from", name="chk_dl_validity"),
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="SET NULL"))
    dl_number_masked / dl_number_encrypted
    dl_classes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    issuing_rto / issue_date / valid_from / valid_upto
    is_commercial_license / badge_number / badge_issuing_authority / badge_valid_upto
    # verification via VerificationMixin; verification_method CHECK to DocumentVerificationMethod
    verified_via_parivahan / parivahan_reference_id
    is_current
```

### 4.8 `bank_accounts` — payee-polymorphic

Replace `user_id` with the repository's polymorphic owner so a fleet partner
can hold a payout account:

```python
owner_type: Mapped[str] = mapped_column(String(50), nullable=False)   # 'user' | 'fleet_partner'
owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
# CHECK owner_type IN ('user','fleet_partner')
Index("ix_bank_accounts_owner", "tenant_id", "owner_type", "owner_id",
      postgresql_where=text("deleted_at IS NULL"))
Index("uq_bank_accounts_one_primary", "tenant_id", "owner_type", "owner_id", unique=True,
      postgresql_where=text("is_primary AND is_active AND deleted_at IS NULL"))
```

Keep the `account_number_last4` / `account_number_encrypted` isolation pattern.

### 4.9 Consent & verification

- **`consent_records` stays a table.** Add `ConsentBoundMixin` (a nullable
  `consent_id` FK only, no relationship) and apply it to
  `AadhaarVerification`, `PANVerification`, `BackgroundVerification` and any
  tracking/biometric record. Remove the inline consent columns from
  `AadhaarVerification`.
- **No polymorphic verification table.** Use `VerificationMixin` for
  record-level state; keep `verified_name`/`verified_dob`/`verified_gender`/
  `verified_address` on the identity tables. `Vehicle`, `Hub`, `FleetPartner`,
  `DrivingLicense` and `BackgroundVerification` all use `VerificationMixin`.
- **`uid_token`** stays on the Aadhaar flow, isolated from the demographic
  extract (sibling table or ADV).
- **`kyc_audit_logs`** stays as the compliance ledger; add tenant/org scope and
  monthly partitioning.

---

## 5. Greenfield migration sequence

The database is dropped and migrations re-run (decision #5), so this is a
straight build with no backfill.

| Step | Migration | Contents |
|---|---|---|
| G1 | org scope | `users`: `MultiTenantMixin`, `uq_users_tenant_id`, `fk_users_tenant_org`, 3-col role FK, `primary_place_id`; `roles`: `OrgEntityMixin`, `uq_roles_tenant_org_id`, `uq_roles_tenant_org_code_live` |
| G2 | zoho identity | `uq_users_zoho_id_live`; `zoho_id` → `String(50)`; drop `users_zoho_id_index` |
| G3 | hubs | `hubs` table; `geo.place_links` OWNER_TYPES += `hub` |
| G4 | fleet partners | `fleet_partners` table |
| G5 | telemetry | `user_live_locations`; `user_location_pings` (+ pg_partman partitions) |
| G6 | vehicles | `vehicles`, `vehicle_compliance_documents`, `driving_licenses` |
| G7 | KYC/compliance set | `kyc_profiles`, `aadhaar_verifications`, `pan_verifications`, `liveness_verifications`, `consent_records`, `data_retention_schedules`, `data_principal_requests`, `background_verifications`, `bgv_check_results`, `medical_fitness_certificates`, `training_certifications`, `bank_accounts`, `employment_records`, `gig_worker_registrations`, `gig_worker_fy_stats`, `kyc_audit_logs` |
| G8 | drop legacy location | drop the ~90 location columns from `users`; keep `country_code` + `primary_place_id` |

All models must be imported in `alembic/env.py` before generating.

---

## 6. Module/file layout

```
app/modules/
  hubs/                 __init__.py, model.py, enums.py, schema.py, service.py, crud.py, api.py, lang/en.py
  fleet_partners/       same FBA layout
  vehicles/             model.py (Vehicle, VehicleComplianceDocument, DrivingLicense), enums.py,
                        schema.py, service.py, crud.py, api.py, lang/en.py
  users/                model.py (User, UserProfile, ref tables, UserLiveLocation, UserLocationPing)
  geo/                  unchanged models; OWNER_TYPES += hub
```

Register each router once in `app/router.py` (`/api/hubs`,
`/api/fleet-partners`, `/api/vehicles`).

---

## 7. Testing

| Layer | Test |
|---|---|
| Unit | partition-name helper for `user_location_pings`; registration-number normalizer; vehicle-type/fuel derivation |
| Unit | zoho crosswalk index predicate; `String(50)` fit validator |
| Mocked boundary | `PATCH /api/me/location` upsert; hub/fleet/vehicle CRUD services |
| Integration | org-scope NOT NULL on users/roles; per-org role uniqueness; 3-col role FK rejects cross-org role |
| Integration | vehicle compliance renewal chain; DL one-current partial unique; bank one-primary per payee |
| Integration | list filters by `city`/`state`/`country` via the address join |
| Conformance | `test_every_table_is_entity_ledger_or_an_explained_global` passes |
| Regression | `test_profile_endpoints.py`, `test_tenancy.py`, `test_geo.py`, `test_documents.py` green |

Add all new tables to `tests/conftest.py` `_TEST_TABLES`.

---

## 8. Registration checklist (per `<table_building_doctrine>`)

- [ ] Models imported in `alembic/env.py`.
- [ ] `OrgEntityMixin` (org NOT NULL) on every new business table.
- [ ] Partial unique indexes include `deleted_at IS NULL`.
- [ ] A stated loader strategy on every relationship (`raise`/`selectin`/`joined`).
- [ ] `geo.place_links.OWNER_TYPES` += `hub`; morph CHECK updated.
- [ ] `hub`/`vehicle` already in `DocumentLinkableType`.
- [ ] Debezium `table.include.list` + search-registry decisions per table.
- [ ] `tests/conftest.py` `_TEST_TABLES`.
- [ ] Docs: `PROJECT_STRUCTURE.md`, `MODULES.md`, module READMEs, `docs/tenancy/README.md`, `docs/geo/README.md`.

---

## 9. Definition of Done

- [ ] `users` is org-scoped, location-free, has `primary_place_id` and
      `uq_users_zoho_id_live`.
- [ ] `roles` is org-scoped with `(tenant_id, organization_id, code)` uniqueness;
      system roles seeded per organization.
- [ ] `hubs` and `fleet_partners` exist and are org-scoped.
- [ ] `vehicles`, `vehicle_compliance_documents`, `driving_licenses` exist,
      org-scoped, using `VerificationMixin`, with no `is_active` double truth.
- [ ] `user_live_locations` + partitioned `user_location_pings` exist.
- [ ] `bank_accounts` is payee-polymorphic.
- [ ] `consent_records` is authoritative; `ConsentBoundMixin` used; no inline
      consent columns remain.
- [ ] `kyc_audit_logs` kept, org-scoped, partition-planned.
- [ ] No polymorphic verification table; `VerificationMixin` used throughout.
- [ ] All tests green on a bare checkout; conformance test passes.
- [ ] Docs updated.

---

## 10. Risks & open questions

| # | Risk / question | Recommendation |
|---|---|---|
| 1 | Users currently tenant-wide (NULL org) in any existing dev DB. | Greenfield: recreate; no backfill. If an existing DB must be kept, assign the tenant's single/root organization first. |
| 2 | Roles become per-organization — system roles multiply. | Seed per organization on create. If inheritance is later wanted, treat tenant-root roles as templates and copy. |
| 3 | `MultiTenantMixin` uses `ondelete=CASCADE` on tenants. | Accept; other RESTRICT tables still block tenant deletion. Document it. |
| 4 | `primary_place_id` / `country_code` / `*_cache` columns can drift. | Maintain each in one service function; add a periodic reconciliation check. |
| 5 | Pings volume/partition cost. | Live-location 1:1 is the immediate win; enable pings when tracking is actually used. |
| 6 | `users.zoho_id` values may exceed `String(50)`. | If a kept DB has longer values, keep `String(255)` and only add the unique index. |
| 7 | DPDP SLA windows per `request_type` are undefined. | Provide them in config before implementing `data_principal_requests` automation. |

---

## 11. File-by-file change index

| File | Change |
|---|---|
| `app/modules/users/model.py` | `MultiTenantMixin`; remove ~90 location columns; add `primary_place_id`, `uq_users_tenant_id`, `uq_users_zoho_id_live`, 3-col role FK; add `UserLiveLocation`, `UserLocationPing` |
| `app/modules/users/schema.py` | Remove location fields; add `primary_place_id` + optional nested `home_address`; add `LocationUpdate` |
| `app/modules/users/crud.py` | City/state/country filters via address join |
| `app/modules/users/service.py` | `set_primary_address`; remove tracking writes; location upsert; `country_code` cache upkeep |
| `app/modules/users/api.py` | Optional `/api/users/{id}/address`; `PATCH /api/me/location` |
| `app/modules/roles/model.py` | `OrgEntityMixin`; per-org uniqueness |
| `app/modules/roles/service.py` | Per-org system-role seeding; holder count within org |
| `app/modules/organizations/service.py` | Seed roles on organization create |
| `app/modules/hubs/**` | New module |
| `app/modules/fleet_partners/**` | New module |
| `app/modules/vehicles/**` | New module |
| `app/modules/geo/model/link.py` | `OWNER_TYPES` += `hub` (+ CHECK migration) |
| `alembic/versions/*` | G1–G8 |
| `app/router.py` | Register hubs/fleet-partners/vehicles routers |
| `tests/conftest.py` | New tables in `_TEST_TABLES` |
| `docs/PROJECT_STRUCTURE.md`, `docs/MODULES.md`, `docs/tenancy/README.md`, `docs/geo/README.md` | Update |
