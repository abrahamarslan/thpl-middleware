# Analysis Report — Proposed User / KYC / Compliance Schema vs. the Existing `users` Module

**Document Reference:** `docs/analysis-report/user-new-architecture.md`
**Status:** Architecture Review — FINAL
**Author:** Principal Enterprise Systems Architect
**Date:** September 2026
**Review scope:** `apps/core-platform/backend/app/modules/users/` and the supporting modules it depends on (`documents`, `activity`, `database/mixins`, tenancy), against the proposed KYC/compliance schema (`audit.py`, `background_verification.py`, `banking.py`, `employment.py`, `enums.py`, `kyc.py`, plus the proposed `User` model).
**Method:** Static source review only. No migrations were generated and no tests were executed.

---

## 0. TL;DR — Verdict

> **The proposed schema is a materially better *domain model* than what exists today, and a materially worse *fit* for this codebase as written. Adopt the domain decomposition; re-implement it on the repository's own conventions. Do not merge it as-is.**

| Dimension | Grade | One-line |
|---|---|---|
| Statutory domain coverage (DPDP, UIDAI, e-Shram, MoRTH) | **A** | The current schema has essentially none of this. |
| Normalization / data modelling | **A−** | KYC-as-a-cycle, normalized BGV sub-checks, ADV isolation, employment history are all correct. |
| Multi-tenancy | **F** | Every proposed table is tenant-blind. This is a hard blocker. |
| Base package & mixin conventions | **F** | Imports `..Common.base` (`PrimaryKeyMixin`, `AuditColumnsMixin`) that do not exist here. |
| Fit with the current `User` model | **F** | Assumes a superseded, monolithic User that is not the one in the repo. |
| Duplication of existing capability | **D** | `KYCAuditLog` duplicates `activity_logs`; `BackgroundVerification` duplicates PVC columns it also models separately. |
| Integrity constraints / indexing | **B−** | Strong partial indexes and CHECKs, undercut by soft-delete-unaware partial indexes and missing tenant-leading keys. |
| Relationship / N+1 discipline | **D** | Relationships declared with no loader strategy — a `MissingGreenlet` hazard under `AsyncSession`. |
| Migration / operability | **F** | Dangling FKs to `hubs`, `fleet_partners`, `vehicles`; references to columns that do not exist. |

**Bottom line:** roughly **60–65 %** of the new schema's *tables and enums* should survive, re-parented onto `TenantEntityMixin`/`LedgerMixin`/`IntPKMixin` and re-pointed at the real `User`; the `User` model itself should be *extended*, not replaced; `KYCAuditLog` should be folded into `activity_logs`; and the BGV/PVC overlap must be resolved before any migration is written.

> **See also §10 (Addendum):** the `users` table's ~90 location columns should be decomposed onto the live `geo` location hub (`geo.place_links` + `geo.places` + `geo.admin_boundaries`) plus a new isolated telemetry layer (`user_live_locations` + `user_location_pings`); `users` should become organization-scoped (`MultiTenantMixin`), `roles` likewise (`OrgEntityMixin`, `(tenant_id, organization_id, code)`), and `users.zoho_id` should become a partial-unique crosswalk to `zoho_users`. The step-by-step work is in [`docs/implementation-plan/users-update-implementation-plan.md`](../implementation-plan/users-update-implementation-plan.md).

---

## 1. How to read this report (definitions)

The request conflated three different artifacts. This report keeps them separate, because most of the "is it better?" question is really a question about *which* baseline.

| Term used below | What it means |
|---|---|
| **Current design** | What is actually in `apps/core-platform/backend/app/modules/users/` today: a tenant-scoped `User`, the `Country`/`Timezone`/`CountryTimezone`/`UserProfile` localization tables, plus the supporting `documents`, `activity`, and tenancy layers. |
| **Fat-User design** | The monolithic `User` model pasted at the end of the proposal (`is_active_for_dispatch`, `kyc_status`, `employee_code`, `hub_id`, … all on one 200+ column table). This is the *target* the proposed modules were written against — but it is **not** the `User` in this repository. |
| **Proposed design** | The new modular schema: `audit.py`, `background_verification.py`, `banking.py`, `employment.py`, `enums.py`, `kyc.py`, and the Fat-User model. |

The phrase "your new design" below = **Proposed design**. "The old design" = **Current design**, with **Fat-User design** called out wherever it is the real point of comparison.

---

## 2. Baseline — what actually exists today (Current design)

### 2.1 The `User` model

`app/modules/users/model.py:61` defines:

```python
class User(TenantScopedMixin, RowVersionMixin, AppMetaMixin, DeactivationMixin, Base):
```

Key facts:

- **Tenant-scoped.** `tenant_id` (NOT NULL, FK → `org_management.tenants.id`) and `organization_id` (nullable) are stamped and filtered automatically by `app/database/tenancy.py`. Every ORM SELECT gets `tenant_id = :current` appended. This is the platform's central isolation mechanism (`docs/tenancy/README.md`).
- **Optimistic locking.** `row_version` is wired to `version_id_col`; stale writes raise `StaleDataError`.
- **Audit pair.** `created_by`/`created_by_name`, `updated_by`/`updated_by_name` via `AuditMixin`.
- **Deactivation, not `is_active`.** `deactivation_date IS NULL` is the single source of truth; the tenancy doctrine explicitly bans a parallel `is_active` boolean (`docs/tenancy/README.md:94`).
- **No DLP/KYC fields.** There is no `employee_code`, `personnel_type`, `kyc_status`, `background_verification_status`, `overall_compliance_status`, `is_active_for_dispatch`, `eshram_uan`, `epfo_uan`, `pan_masked`/`pan_encrypted`, `consent_*_at`, `hub_id`, `primary_vehicle_id`, or `fleet_partner_id` in the real model. Those exist only in the pasted **Fat-User design**.
- The model does carry `pan` (plaintext, Laravel legacy), `bank_details` JSONB, `payment_details` JSONB, and the full PostGIS location column set.

### 2.2 Localization (already implemented)

The plan in `docs/implementation-plan/user-localization-timezone-and-messages.md` is **already live**:

- `Country`, `Timezone`, `CountryTimezone`, `UserProfile` are in `model.py:427–516`.
- Migration `20260917_1700_f7a8b9c0d1e2_countries_timezones_user_profiles.py` exists.
- `/api/countries`, `/api/countries/{iso2}/timezones`, `/api/me/profile` are wired (`users/api.py:312–323`, `:286–299`).
- The message resolver (`app/common/response/messages.py`), `ResponseModel.ok(...)`, and `app/modules/users/lang/en.py` are implemented.
- `whenever`-based time utility lives in `app/common/time.py`.

**Implication:** the proposed schema must not reintroduce or collide with any of this. It does not — but it also does not acknowledge it.

### 2.3 Supporting modules the proposal collides with

| Existing module | Relevant capability | Source |
|---|---|---|
| `documents` | Logical document + page files + polymorphic links + verification log; already has `document_types` catalog, `retention_expiry_date`, `verification_status`, `is_verified` CHECK, versioning | `app/modules/documents/model.py:100`, `:160`, `:275`, `:412`, `:475` |
| `activity` | Cross-entity, append-only audit trail: `action`, `status`, `actor_*`, `subject_type`/`subject_id` (polymorphic), `changes` JSONB before/after, `context`, `request_id`, `ip_address`, tenant-scoped | `app/modules/activity/model.py:25` |
| `users/audit.py` | Dual-write recorder: persisted `activity_logs` row **and** structlog line, with a stable `Event` catalog | `app/modules/users/audit.py:34`, `:84` |
| `database/mixins.py` | `IntPKMixin`, `BigIntPKWithUUIDMixin`, `TimestampMixin`, `AuditMixin`, `StatusMixin`, `VerificationMixin`, `RowVersionMixin`, `SoftDeleteMixin`, `TenantEntityMixin`, `LedgerMixin`, … | `app/database/mixins.py` |
| `documents.mixins` | `HasDocumentsMixin` + `linkable_type_of()` — the sanctioned way for any model to own documents | `app/modules/documents/mixins.py:33` |

### 2.4 What the Current design genuinely lacks

This matters, because it is the strongest argument *for* the proposal:

- No KYC cycle/profile at all.
- No Aadhaar/PAN verification model (only legacy plaintext `users.pan`).
- No consent ledger.
- No background/police verification.
- No medical-fitness or training certification.
- No employment history, no gig-worker statutory registration.
- No first-class payout bank account (only `bank_details` JSONB).
- No data-retention schedule and no DPDP data-principal-request lifecycle.
- No rolled-up compliance gate for dispatch.

The proposal fills all of these. That is its central value.

---

## 3. Inventory of the Proposed design

| File | Tables | Row class intent |
|---|---|---|
| `audit.py` | `kyc_audit_logs` | Immutable ledger |
| | `consent_records` | Entity (per user) |
| | `data_retention_schedules` | Reference/global |
| | `data_principal_requests` | Entity (per user) |
| `background_verification.py` | `background_verifications` | Entity (per user) |
| | `bgv_check_results` | Entity (child of BGV) |
| | `police_verifications` | Entity (per user) |
| | `medical_fitness_certificates` | Entity (per user) |
| | `training_certifications` | Entity (per user) |
| `banking.py` | `bank_accounts` | Entity (per user) |
| `employment.py` | `employment_records` | Entity (per user, history) |
| | `gig_worker_registrations` | Entity (1:1 per user) |
| | `gig_worker_fy_stats` | Entity (per user per FY) |
| `kyc.py` | `kyc_profiles` | Entity (per user, history) |
| | `aadhaar_verifications` | Entity (1:1 per KYC cycle) |
| | `pan_verifications` | Entity (1:1 per KYC cycle) |
| | `liveness_verifications` | Entity (per user) |
| `enums.py` | ~25 enums | Vocabulary |

Plus the **Fat-User** additions: identity/employment linkage, KYC/compliance caches, consent quick-flags, statutory ID caches, org linkage.

---

## 4. The Good

These are genuine strengths. Each is a reason to keep the idea even if the implementation is rewritten.

### 4.1 KYC modelled as a *cycle*, not a flag — **excellent**

`KYCProfile` gets a new row per KYC run (`kyc_cycle_number`, `kyc_type`, `is_current`), with a partial unique index enforcing one current cycle per user. This is the correct model: initial onboarding, periodic re-KYC, triggered re-KYC and address updates are all distinct events with distinct evidence. A boolean `kyc_verified` cannot represent "verified, but re-KYC due" or "triggered after an adverse flag." The Current design has *nothing* here; this is a straight upgrade.

### 4.2 Aadhaar Data Vault isolation — **the single best part**

`AadhaarVerification` stores only `masked_aadhaar_number`, an opaque `aadhaar_vault_reference_key` into an external ADV, and demographics. It never stores the 12-digit number. This matches the UIDAI ADV circulars and the 2025 clarification, and it aligns with the `documents` module's existing rule (`allows_full_number_storage=false` for AADHAAR, `model.py:135`). The surrounding commentary is disciplined and correct.

### 4.3 Normalized BGV sub-checks — **excellent**

`BackgroundVerification` (the run) + `BGVCheckResult` (one row per sub-check) means criminal/address/employment/education/reference checks are *data*, not columns. New check types need no `ALTER TABLE`. The run-level `status` remains the dispatch gate. This is textbook normalization and directly follows the codebase's own philosophy (`document_links.linkable_type` is open for the same reason).

### 4.4 Employment as history, not 1:1

`EmploymentRecord` with `is_current` and a partial unique index correctly models exit + rejoin. `GigWorkerRegistration` (1:1 statutory facts) is cleanly separated from `GigWorkerFYStats` (running accrual, unique per `(user_id, financial_year)`), which lets an eligibility job flip status deterministically without rescanning history. Strong.

### 4.5 Bank account encryption pattern

`BankAccount` keeps `account_number_last4` plaintext for display/search and `account_number_encrypted` ciphertext for the payout service only — mirroring the Aadhaar isolation principle and the repo's own PAN/DL pattern. The partial unique index `uq_bank_accounts_one_primary` (`WHERE is_primary`) is a correct use of partial indexes. The `name_match_score` CHECK is good.

### 4.6 DPDP coverage that the platform currently lacks

`ConsentRecord`, `DataRetentionSchedule`, and `DataPrincipalRequest` address the DPDP Act 2023 duties — explicit consent logging, per-category retention with delete-vs-anonymize, and the access/correction/erasure/grievance/nomination rights lifecycle with SLA tracking. Even if the individual implementations need work, the *decision to model these* is correct and overdue.

### 4.7 Centralized enum vocabulary

One `enums.py` per domain, with a module docstring explaining the boundary against `Document/enums.py` and `Vehicle/enums.py`. Reviewable at a glance; one source of truth for migration authors. Matches the repo's own pattern (`documents/enums.py`).

### 4.8 Correct instinct on immutability and partitioning

`KYCAuditLog` is append-only and the docstring proposes monthly range partitioning on `performed_at`. `DocumentVerificationLog` in the repo makes the same recommendation. The instinct is right.

---

## 5. The Bad

> **Superseded in part by §11.1.** §5.4 (drop `kyc_audit_logs`), §5.5 (pick
> one owner for the PVC), §5.7 (reconcile with `zoho_retention_policies`) and
> §5.13 (drop `uid_token`) record the *original* recommendations. The author
> has since decided to **keep `kyc_audit_logs`**, make the **PVC a
> `BackgroundVerification`**, treat **retention as application-only**, and
> **keep `uid_token`**. Read those subsections with §11.1 alongside them.

### 5.1 **BLOCKER — No multi-tenancy on any table**

Every proposed table is keyed only by `user_id` (or nothing at all). None declares `tenant_id`/`organization_id`. Consequences:

1. **Isolation is gone.** The tenancy layer only auto-filters models that subclass `TenantBound`. These tables would be treated as GLOBAL and would return other tenants' rows.
2. **The tenancy test fails by construction.** `test_every_table_is_entity_ledger_or_an_explained_global` requires every table to be an ENTITY, a LEDGER, or an explicitly-reasoned GLOBAL. The proposal provides no such reasoning (`docs/tenancy/README.md:96–102`).
3. **`User` is tenant-scoped, so a cross-tenant read is one careless `WHERE user_id=` away.** A `user_id` alone is not unique across tenants in any meaningful security sense even though the PK is global; the *access path* must lead with the tenant.

**Required fix:** every table except `data_retention_schedules` (defensible as a GLOBAL reference catalog, like `document_types` and `countries`) becomes `TenantEntityMixin` or `LedgerMixin`, and every index is re-led with `tenant_id`. Child tables (`bgv_check_results`, `aadhaar_verifications`, `pan_verifications`) should use composite FKs `(tenant_id, parent_id)` exactly as `document_files`/`document_links` do (`documents/model.py:314`, `:424`).

### 5.2 **BLOCKER — Wrong base package and mixin names**

The proposal imports:

```python
from ..Common.base import AuditColumnsMixin, Base, PrimaryKeyMixin, TimestampMixin
from .enums import ...
```

None of that exists here. The repository uses:

```python
from app.database.db import Base
from app.database.mixins import IntPKMixin, TimestampMixin, AuditMixin, TenantEntityMixin, LedgerMixin, ...
```

`Common/base.py` does not exist. `PrimaryKeyMixin`/`AuditColumnsMixin` are foreign names, and `docs/tenancy/README.md:82–94` states the rule explicitly: *"Mixin sets copied in from other projects use different names. Do not add aliases — use ours."*

The mapping is mechanical:

| Proposed name | Repository equivalent |
|---|---|
| `PrimaryKeyMixin` | `IntPKMixin` (or `BigIntPKWithUUIDMixin` when the table is API-exposed) |
| `AuditColumnsMixin` | `AuditMixin` (also gives `*_name`, which the proposal lacks) |
| `TimestampMixin` | `TimestampMixin` (compatible — but the repo's is DB-authoritative `server_default=func.now()`) |
| `Base` | `app.database.db.Base` |
| *(implicit entity bundle)* | `TenantEntityMixin` + `SoftDeleteFilteredMixin` |

### 5.3 **BLOCKER — Built against a superseded `User` model**

The proposal assumes the Fat-User model. The repo's `User` has none of the columns the modules reference, and the FK targets do not exist:

| Referenced by proposal | Exists in repo? |
|---|---|
| `users.employee_code`, `personnel_type`, `is_active_for_dispatch`, `kyc_status`, `re_kyc_due_at`, `background_verification_status`, `overall_compliance_status`, `consent_*_at`, `eshram_uan`, `epfo_uan`, `hub_id`, `primary_vehicle_id`, `fleet_partner_id`, `pan_masked`, `pan_encrypted` | **No** |
| `hubs` table | **No** |
| `fleet_partners` table | **No** |
| `vehicles` table | **No** |
| `documents.consent_id` column | **No** (the `documents` table has no such column) |
| `Document/enums.py AuditEntityType` | **No** (dangling reference; not defined in the proposal either) |

This is the difference between "a schema" and "a schema that can run here." None of it applies cleanly today.

### 5.4 `KYCAuditLog` duplicates `activity_logs`

The repo already has a persisted, append-only, tenant-scoped, cross-entity audit trail with before/after `changes`, `request_id` correlation, an API, and a dual-write recorder (`activity/model.py:25`, `users/audit.py:84`). `KYCAuditLog` re-implements the same idea with different column names (`entity_type`/`entity_id` vs `subject_type`/`subject_id`; `old_value`/`new_value` vs `changes`). This violates the master prompt's Prime Directive #2 ("Extend, don't duplicate — and don't silently adopt a competing pattern").

The one thing `KYCAuditLog` adds is `performed_at` distinct from `created_at` (useful for backfilled events) and `user_agent`. Both are trivial to add to `activity_logs` (`context` JSONB already exists for user-agent/device). **Recommendation:** drop the table; use `record_activity(...)`.

### 5.5 `BackgroundVerification` and `PoliceVerification` overlap

The proposal models a PVC **twice**:

- `BackgroundVerification` has `bgv_type = police_verification_certificate` *and* PVC-specific columns: `police_station_jurisdiction`, `pvc_certificate_number`, `pvc_issued_date`, `pvc_valid_upto`.
- `PoliceVerification` is a standalone table for the same certificate.

The docstring justifies the separate table (distinct lifecycle, government-issued document, renewal chain). That justification is sound — but then the PVC columns on `BackgroundVerification` must be **removed**, or the two become competing sources of truth. As written, "where does the PVC live?" has two answers. Pick one owner: `PoliceVerification` owns certificates; `BackgroundVerification` may hold a `document_id`/reference to it, not a copy.

### 5.6 Consent is not actually the single source of truth

`ConsentRecord`'s docstring claims it is "the single source of truth for consent." It is not:

- `AadhaarVerification` has its own inline `consent_given`, `consent_given_at`, `consent_ip_address`.
- The Fat-User model has `consent_dpdp_at`, `consent_aadhaar_ekyc_at`, `consent_biometric_at`, `consent_bgv_at`.
- `PoliceVerification` links via `consent_id`, but nothing else does.

Three consent stores that can disagree. **Fix:** all consent-worthy operations reference `consent_records.id`; inline consent columns are removed (the Aadhaar inline trio becomes a FK + join).

### 5.7 Retention design is incomplete and self-contradictory

The `DataRetentionSchedule` docstring says a nightly job joins it against `documents`, `background_verifications`, etc. to compute `retention_expiry_date`. But:

- `background_verifications`, `bank_accounts`, `employment_records`, `kyc_profiles`, `police_verifications`, `training_certifications`, and `medical_fitness_certificates` have **no** `retention_expiry_date` column.
- Only `Document` (existing repo table) has one (`documents/model.py:275`).
- The repo already has a `zoho_retention_policies` table and sync-payload retention policies — there is an unaddressed relationship between the two retention mechanisms.

So the retention schedule cannot yet drive the job it describes.

### 5.8 Relationship / N+1 discipline absent

Every relationship in the proposal is declared without a loader strategy:

```python
user: Mapped["User"] = relationship(back_populates="background_verifications", foreign_keys=[user_id])
check_results: Mapped[list["BGVCheckResult"]] = relationship(back_populates="bgv", ...)
```

Under `AsyncSession`, an implicit lazy load raises `MissingGreenlet` — it does not just cost a query. The repo's doctrine requires stating the strategy (`lazy="selectin"`, `lazy="joined"`, `lazy="raise_on_sql"`) at declaration time (`master-prompt.md` `<n_plus_one_doctrine>`; `documents/model.py:279–285` is the worked example). This is a correctness defect, not a style nit.

### 5.9 Soft-delete-unaware partial unique indexes

`EmploymentRecord` and `KYCProfile` use:

```python
Index("uq_employment_records_one_current", "user_id", unique=True, postgresql_where=text("is_current"))
```

`EmploymentRecord` is soft-deletable (`SoftDeleteMixin`), but the partial index does not exclude `deleted_at IS NOT NULL`. A soft-deleted current stint therefore **blocks creation of a new current stint** — the exact failure mode the repo's partial-index doctrine exists to prevent (`master-prompt.md` `<table_building_doctrine>` step 5). The predicate must be `is_current AND deleted_at IS NULL`.

The same audit applies to any partial unique index added to a soft-deletable table.

### 5.10 `SoftDeleteMixin` instead of `SoftDeleteFilteredMixin`

`EmploymentRecord` uses `SoftDeleteMixin` (column only, no query filtering). The repo's default for business tables a user can delete is `SoftDeleteFilteredMixin` (automatic `WHERE deleted_at IS NULL`). Using the unfiltered variant means every query must remember the predicate manually — a silent correctness risk.

### 5.11 Missing CHECK constraints on numeric ranges

- `DataRetentionSchedule.retention_period_days` — NOT NULL, no `> 0`.
- `DataRetentionSchedule.grace_period_days` — no `>= 0`.
- `TrainingCertification.score_percentage` (`Numeric(5,2)`) — no `0–100` CHECK, though `BankAccount.name_match_score` and `KYCProfile` scores have one.

### 5.12 Python-side defaults without server defaults

`DataRetentionSchedule.action` uses `default=RetentionAction.DELETE.value` only; several booleans use `default=` without `server_default=`. The repo's convention is a `server_default` for anything NOT NULL (`mixins.py:228–233`), so raw SQL and migrations produce the same row as the ORM.

### 5.13 `AadhaarVerification.uid_token` contradicts its own rule

The docstring says the UID token "may be stored locally ONLY if not mapped to demographic data." But `uid_token` sits in the **same table row** as `verified_name`, `verified_dob`, `verified_gender`, `verified_address`. Storing the token alongside demographics is precisely the mapping UIDAI prohibits. Either drop `uid_token`, or move it to a separate table with no demographic columns.

### 5.14 `PoliceVerification.reapplication_count` is a drift-prone counter

It is a stored integer that must be incremented on every renewal, but the renewal chain is already reconstructible via `supersedes_certificate_id`. Derive it (`COUNT(*)` over the chain) or drop it; a stored counter with no trigger will disagree with the chain.

### 5.15 Enum/column-comment drift and dangling references

- `BackgroundVerification.status` comment omits `discrepancy_found`, which the `BGVStatus` enum includes.
- `BGVType` values and the column comment disagree on naming.
- `AuditEntityType` is referenced repeatedly ("see `Document/enums.py AuditEntityType`") but defined nowhere.
- `GigBenefitEligibilityStatus` is physically located in the Consent section of `enums.py`.

### 5.16 No search / CDC / observability plan

The proposal adds 17 tables. None declares whether it is CDC'd, searchable, or added to Debezium's `table.include.list`. The master prompt's registration checklist requires a decision per model (`<table_building_doctrine>` step 6, `<search_architecture>`). This is not a reason to reject the design, but the tables cannot ship without it.

### 5.17 No service/API/transport layer

The proposal is model-only. It does not specify the FBA layers (`schema → service → crud → api`), the Slim/Fat DTO split, RBAC (who may read a user's Aadhaar verification?), or the localized messages for each operation. Those are the bulk of the work and must be designed alongside the models.

---

## 6. Defect register

Severity: **P0** = cannot merge / data-leak or non-running; **P1** = must fix before first migration; **P2** = should fix soon; **P3** = polish.

| ID | Sev | Area | Defect | Required action |
|---|---|---|---|---|
| D-01 | P0 | Tenancy | No `tenant_id`/`organization_id` on any table | Reparent to `TenantEntityMixin`/`LedgerMixin`; tenant-leading indexes; composite FKs on children |
| D-02 | P0 | Base/mixins | `..Common.base` + `PrimaryKeyMixin`/`AuditColumnsMixin` do not exist | Use `app.database.db.Base` + `app.database.mixins`; no aliases |
| D-03 | P0 | Dependencies | FKs to `hubs`, `fleet_partners`, `vehicles`; columns absent from real `User` | Drop or stage behind the modules that own them; extend `User` explicitly |
| D-04 | — | Audit | ~~`kyc_audit_logs` duplicates `activity_logs`~~ **RESOLVED — keep the table** | Keep `kyc_audit_logs` as the compliance ledger (see §11.1); document the boundary against `activity_logs`; add tenant/org scope + monthly partitioning |
| D-05 | — | BGV | ~~PVC modelled in two tables~~ **RESOLVED — PVC is a BGV** | Drop `police_verifications`; `BackgroundVerification` owns the PVC fields (`bgv_type = police_verification_certificate`) and the renewal chain (see §11.1) |
| D-06 | P1 | Consent | Three consent stores disagree | All consent via `consent_records.id`; a `ConsentBoundMixin` (FK only) standardizes the link (see §11.2) |
| D-07 | — | Retention | ~~reconcile with `zoho_retention_policies`~~ **RESOLVED — independent** | `data_retention_schedules` is the application's data-retention rule table; it has nothing to do with Zoho payload retention. Only remaining work: add `retention_expiry_date` where the purge job reads it |
| D-08 | P1 | N+1 | Relationships with no loader strategy | Declare `selectin`/`joined`/`raise_on_sql` per relationship |
| D-09 | P1 | Indexes | Partial unique indexes ignore `deleted_at` | Add `AND deleted_at IS NULL` to soft-deletable predicates |
| D-10 | P1 | Documents | `documents.consent_id` does not exist | Add column/migration or link consent via the pivot; use `HasDocumentsMixin` |
| D-11 | — | Aadhaar | ~~`uid_token` co-located with demographics~~ **RESOLVED — required field** | Keep `uid_token`; isolate it from demographics (separate table or inside the ADV) rather than dropping it (see §11.1) |
| D-19 | P1 | Vehicle | `vehicles`/`vehicle_compliance_documents`/`driving_licenses` tenant-blind, wrong base, `is_active`+`status` double truth | Reparent on `OrgEntityMixin`/`TenantEntityMixin`; drop `is_active`; use `VerificationMixin` (see §11.4) |
| D-20 | P1 | Hub/Fleet | `hubs` and `fleet_partners` are FK targets that do not exist | Build both modules (§11.6/§11.7) before `vehicles`/`employment_records` can migrate |
| D-21 | P2 | Banking | `bank_accounts.user_id` cannot own a fleet-partner payout account | Make the payee polymorphic (`owner_type`/`owner_id`) (see §11.8) |
| D-12 | P2 | Soft delete | `SoftDeleteMixin` used where filtered is the default | Switch to `SoftDeleteFilteredMixin` |
| D-13 | P2 | Constraints | Missing range CHECKs / server defaults | Add `>0`, `>=0`, `0–100`, `server_default` |
| D-14 | P2 | Consistency | Enum/comment drift; `AuditEntityType` undefined | Define or remove `AuditEntityType`; align comments with enums |
| D-15 | P2 | Banking | Primary-slot unique index ignores `is_active` | Predicate `is_primary AND is_active` (or free slot on deactivate) |
| D-16 | P3 | Police | `reapplication_count` drift | Derive from the chain or drop |
| D-17 | P3 | CDC/Search | No include-list / registry decisions | Add to the registration checklist per table |
| D-18 | P3 | Layers | No schema/service/crud/api or messages | Build the FBA layers with localized messages |

---

## 7. Is the new design better than the old design?

The honest answer depends on the axis. This is not a dodge — it is the actual finding.

### 7.1 Domain model: **yes, clearly better**

Compared to the Current design, the proposal adds every compliance capability the platform needs and models each one correctly: KYC cycles, ADV-isolated Aadhaar, normalized BGV, employment history, statutory gig registration, encrypted bank accounts, DPDP consent/retention/rights. The Current design has none of this. On the *shape of the data*, the proposal wins outright.

Compared to the Fat-User design, the proposal is also better: moving KYC, BGV, banking, employment and gig data off a 200+ column master row into owned tables removes the hot-row churn, the null-density, and the "everything is a column" rigidity that the Fat-User model suffers from. The proposal's own docstrings make this argument correctly.

### 7.2 Architectural fit: **no, currently worse**

As written, the proposal cannot be merged:

- It has no tenancy, so it would be *less* safe than the Current design.
- It targets a `User` model that no longer exists.
- It duplicates `activity_logs` and the `documents` module's capabilities.
- It references four tables (`hubs`, `fleet_partners`, `vehicles`, `documents.consent_id`) and a `Common` package that are not present.
- Its relationships will raise at runtime under `AsyncSession`.

A schema that cannot run is not better than one that does.

### 7.3 Net position

The proposal is a **strong domain blueprint wrapped in an incompatible implementation**. The correct decision is neither "accept" nor "reject" but **harvest**:

1. Keep the domain decomposition and the compliance coverage.
2. Rewrite every model on the repository's tenancy, mixin, audit, documents, and N+1 conventions.
3. Extend the existing `User` with the compliance caches and linkage fields — do not replace it.
4. Resolve the BGV/PVC and consent-source-of-truth ambiguities first.
5. Ship with the FBA layers, localized messages, tests, and Debezium/search registration.

Executed that way, the result is strictly better than both baselines.

---

## 8. Recommended path — hybrid adoption plan

### 8.1 Table-class mapping (the tenancy decision, per table)

| Proposed table | Recommended class | Notes |
|---|---|---|
| `kyc_profiles` | ENTITY (`TenantEntityMixin` + `SoftDeleteFilteredMixin`) | History; partial unique `(tenant_id, user_id) WHERE is_current AND deleted_at IS NULL` |
| `aadhaar_verifications` | ENTITY, composite FK `(tenant_id, kyc_profile_id)` | 1:1 per cycle; drop `uid_token` or isolate |
| `pan_verifications` | ENTITY, composite FK `(tenant_id, kyc_profile_id)` | Keep encrypted+masked pattern |
| `liveness_verifications` | ENTITY | `raise_on_sql` on relationships |
| `consent_records` | ENTITY (`LedgerMixin` acceptable if immutable) | Single source of truth; add `recorded_at`, validity |
| `data_principal_requests` | ENTITY | Define SLA windows in config |
| `data_retention_schedules` | GLOBAL reference (like `document_types`) | Written reason required for the tenancy test |
| `background_verifications` | ENTITY | Drop PVC columns |
| `bgv_check_results` | ENTITY, composite FK `(tenant_id, bgv_id)` | `selectin` on `check_results` |
| `police_verifications` | ENTITY | Sole owner of PVC; tenant-aware self-FK for renewals |
| `medical_fitness_certificates` | ENTITY | Add retention column |
| `training_certifications` | ENTITY | Add score CHECK |
| `bank_accounts` | ENTITY | Primary-slot predicate includes `is_active` |
| `employment_records` | ENTITY + `SoftDeleteFilteredMixin` | Fix partial unique predicate |
| `gig_worker_registrations` | ENTITY | 1:1 per user |
| `gig_worker_fy_stats` | ENTITY | Unique `(tenant_id, user_id, financial_year)` |
| `kyc_audit_logs` | **drop** | Use `activity_logs` |

### 8.2 `User` model changes (extend, don't replace)

Add only the caches/links the modules need, in a dedicated section of the existing model, with a comment that each is a cache of its owning table:

- Identity/employment: `employee_code` (cache of `employment_records.employee_code`), `personnel_type`, `badge_id`, uniform fields, `device_binding_id`.
- KYC/compliance caches: `kyc_status`, `kyc_verified_at`, `re_kyc_due_at`, `background_verification_status`, `overall_compliance_status`, `compliance_last_evaluated_at`, `is_active_for_dispatch`.
- Consent quick-flags (caches only; `consent_records` remains truth).
- Statutory caches: `eshram_uan`, `epfo_uan`.
- Org linkage: `hub_id`, `primary_vehicle_id`, `fleet_partner_id`, `is_vendor_managed` — only once those modules exist.
- PAN: deprecate plaintext `pan`; add `pan_masked`/`pan_encrypted` (or rely solely on `pan_verifications`).

Each cache needs a documented maintenance path (a service function or a job) or it will drift.

### 8.3 Audit: reuse, don't fork

- Delete `KYCAuditLog`.
- Emit compliance events through `app/modules/users/audit.py` (extend `Event` with KYC/BGV/consent/PVC/retention/DSR verbs).
- If `performed_at` distinct from `created_at` is genuinely needed, add a nullable `occurred_at` to `activity_logs` — one column, not a second table.

### 8.4 Documents integration

- Use `HasDocumentsMixin` on KYC/BGV/PVC/medical/training models rather than raw `document_id` columns where the repo already provides the pivot — or keep the FK for the primary artifact and the pivot for supporting evidence. Be consistent.
- If consent must be linked from documents, add `documents.consent_id` (nullable, FK → `consent_records.id`, `ON DELETE SET NULL`) in its own migration, and index it.

### 8.5 Suggested phasing

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Decide BGV/PVC ownership; decide audit reuse; define retention columns | — |
| 1 | `kyc_profiles`, `aadhaar_verifications`, `pan_verifications`, `liveness_verifications` + FBA + tests | `User` caches |
| 2 | `consent_records` (+ `documents.consent_id`), `data_principal_requests`, `data_retention_schedules` | Phase 1 |
| 3 | `background_verifications`, `bgv_check_results`, `police_verifications`, medical, training | `documents` pivot |
| 4 | `bank_accounts`, `employment_records` | org/hub/fleet modules (or nullable staging) |
| 5 | `gig_worker_registrations`, `gig_worker_fy_stats` | Phase 4 |
| 6 | Compliance-gate job populating the `User` caches; search/CDC registration | Phases 1–5 |

Every phase must include: alembic migration (imported in `alembic/env.py`), tenancy test compliance, `_TEST_TABLES` entries in `tests/conftest.py`, hermetic + mocked-boundary tests, and localized messages in `users/lang/en.py`.

---

## 9. Open questions for the author

> Items 1–3 and 8 were answered by the author in Sept 2026; see §11.1 for the locked decisions.

1. ~~**PVC ownership**~~ — **resolved:** a police certificate is a `BackgroundVerification` of type `police_verification_certificate`; the standalone `police_verifications` table is dropped.
2. ~~**`uid_token`**~~ — **resolved:** it is required. Keep it; isolate it from demographics.
3. ~~**Retention reconciliation**~~ — **resolved:** `data_retention_schedules` is application data-retention only; `zoho_retention_policies` is unrelated.
4. **`hubs` / `fleet_partners` / `vehicles`** — resolved in §11.6/§11.7: build `hubs` and `fleet_partners` as first-class modules.
5. **Consent truth** — confirmed: `consent_records` is authoritative; inline consent columns are removed; a `ConsentBoundMixin` standardizes the FK (§11.2).
6. **Fat-User vs current `User`** — was the pasted `User` model an earlier draft that the tenant-scoped model replaced? If so, which columns of the Fat-User are still wanted as caches?
7. **SLA windows** — what are the DPDP response SLAs per `request_type`, and where are they configured?
8. ~~**RBAC**~~ — **resolved:** access to Aadhaar/PAN/bank records is managed explicitly outside this schema; no per-field permission model is required here.

---

## 10. Addendum (Sept 2026) — User location data, organization scoping, roles, and `zoho_id`

This addendum answers a second, sharper question than §1–§9: *the `users`
table carries ~90 location columns and is the hottest row in the system — how
should that be redesigned? And how do users and roles become properly
organization-scoped, with a first-class `zoho_id`?* The actionable steps live
in [`docs/implementation-plan/users-update-implementation-plan.md`](../implementation-plan/users-update-implementation-plan.md).

### 10.1 New ground truth: the `geo` location hub is live

Since the first pass, the location hub (`app/modules/geo/`, schema `geo`,
migration `4f2f2a8c7898`) is the platform's canonical location system
(`docs/geo/README.md`):

| Table | Role |
|---|---|
| `geo.places` | **The only table storing coordinates.** `coordinates` (PostGIS POINT) is canonical; `latitude`, `longitude`, `geohash8` are Postgres GENERATED columns. Postal block, provenance, verification. `OrgEntityMixin` (organization NOT NULL). |
| `geo.place_links` | **Polymorphic address book.** `owner_type` + `owner_id` → `place_id`, with `link_type` (primary/billing/shipping/home/office/site/current/permanent/other), effective dating (`valid_from`/`valid_to`), single-valued EXCLUDE, snapshots, verification. `owner_type='user'` is **already** in `OWNER_TYPES`. |
| `geo.admin_boundaries` | **GLOBAL** administrative reference geometry (country → … → pincode, plus electoral levels), with LGD/Census/geoname codes. One copy platform-wide. |
| `geo.geofences` | Tenant/organization-drawn zones with a dwell policy. |
| `geo.geocode_api_calls` | Append-only provenance/cache/spend ledger for external geo APIs. |

This changes the answer to "where should user location live?" decisively:
**the canonical structures already exist; the `users` columns duplicate them.**

### 10.2 The problem: ~90 location columns on the master row

`app/modules/users/model.py` currently declares, on `users`:

| Group | Columns | What it really is |
|---|---|---|
| Postal block | `street_address`, `landmark`, `village_town`, `taluka`, `district`, `city`, `state`, `country`, `country_code`, `pincode`, `constituency`, `sub_constituency`, `assembly_constituency`, `parliamentary_constituency` | An **address** — belongs in `geo.places` + `geo.place_links` |
| Boundary polygons | `constituency_geometry`, `sub_constituency_geometry`, `assembly_constituency_geometry`, `parliamentary_constituency_geometry`, `pincode_geometry`, `taluka_geometry`, `district_geometry`, `city_geometry`, `state_geometry`, `country_geometry` | **GLOBAL reference geometry** — belongs in `geo.admin_boundaries`, copied per user today |
| Coordinates & codes | `latitude`, `longitude`, `coordinates`, `location`, plus `*_latitude`/`*_longitude` and `*_geonameId` for constituency/sub-constituency/assembly/parliamentary/pincode/taluka/district/city/state/country | Duplicate copies of a place's point and of `geo.admin_boundaries.geoname_id` |
| Telemetry | `current_location`, `altitude`, `altitude_accuracy`, `heading`, `speed`, `location_accuracy`, `location_source`, `location_timestamp`, `location_timezone`, `location_ip`, `geocode`, `recorded_at`, `last_tracked_at`, `device_id`, `device_type`, `network_type`, `is_tracking_active`, `background_tracking_enabled`, `current_pincode`, `current_location_latitude`, `current_location_longitude` | **High-frequency GPS state** — must not live on the master row |

Four independent defects:

1. **Hot-row contention / bloat.** `users` is read on every auth, every
   profile read, every list. High-frequency GPS writes (`last_tracked_at`,
   `current_location`, `heading`, `speed`, …) cause lock contention, table
   bloat, index churn and WAL amplification on the one row the whole platform
   depends on. This is the same lesson `documents/model.py` records for
   `document_verification_logs`.
2. **Reference data duplicated per user.** A district MULTIPOLYGON is measured
   in megabytes; storing it on every user is the single worst storage decision
   in the current model. `geo.admin_boundaries` exists precisely to hold it
   once, globally.
3. **Multiple sources of truth for one coordinate.** `location`,
   `coordinates`, `latitude`/`longitude`, `current_location`, and the per-level
   lat/lng copies can all disagree. `geo.places` solved this with GENERATED
   columns — the application literally cannot write `latitude` there.
4. **Two concepts conflated.** A *home/permanent address* (slow-changing,
   reusable, needs history) and a *last-known GPS fix* (fast-changing,
   ephemeral, needs a firehose) are different data with different lifecycles.
   One set of columns cannot serve both.

### 10.3 Target architecture: three layers

```
Layer 1  ADDRESS (slow, reusable, historical)
         users ──(geo.place_links: owner_type='user', link_type=home/permanent/current/office)──► geo.places
         Effective-dated, snapshottable, verifiable, reusable across owners.

Layer 2  REFERENCE (global, read-only)
         geo.places.admin_boundary_id ──► geo.admin_boundaries (country…pincode, geoname/lgd/census)
         A user's district/state/constituency is derived, never stored on the user.

Layer 3  TELEMETRY (fast, ephemeral, firehose)
         user_live_locations  1:1 per user — last known fix (hot but isolated from `users`)
         user_location_pings  append-only history — partitioned monthly (pg_partman), retention-managed
```

**Layer 1 — addresses.** Use the existing address book verbatim:
`POST /api/addresses` with `owner_type='user'`, `owner_id=<user id>`,
`link_type='home'` (or `permanent`/`current`/`office`). `current` and
`permanent` are already single-valued and effective-dated with a no-overlap
EXCLUDE constraint, so a moved user keeps a readable history
(`GET /api/addresses/history`). Per-link `landmark`,
`delivery_instructions` and `contact_phone` cover the courier notes that
currently live as `users.landmark`. `VerificationMixin` on the link says "this
person really lives here", distinct from verifying the place.

**Layer 2 — reference.** No user column at all. Resolve the containing
boundary once on the place (`places.admin_boundary_id`, via
`geo.service.boundary_for_point`) and read the hierarchy through
`admin_boundaries.path` (`/india/maharashtra/pune/`). All `*_geometry`,
`*_geonameId` and per-level `*_latitude`/`*_longitude` columns are deleted.

**Layer 3 — telemetry.** Two new tables, deliberately **not** carrying
`row_version`/`status`/audit (they are LEDGER-class, per
`test_every_table_is_entity_ledger_or_an_explained_global`):

- `user_live_locations` — one row per `(tenant_id, user_id)`, upserted with
  `ON CONFLICT` on every fix. `MultiTenantMixin + AppMetaMixin + TimestampMixin`
  (organization NOT NULL; LEDGER columns present; no `row_version`). Holds the
  last fix and the tracking flags. This is what dispatch/beat-planning reads.
- `user_location_pings` — append-only, `MultiTenantMixin + AppMetaMixin`,
  **partitioned monthly on `recorded_at`** with `pg_partman` (already baked
  into the custom Postgres image per the master prompt). Retention is a
  partition drop, and the retention window is exactly a
  `DataRetentionSchedule` row (`data_category = location_history`) — this ties
  the telemetry layer into the DPDP retention design from §4.7/§5.7.

### 10.4 Column disposition

| Current `users` column(s) | Disposition |
|---|---|
| `street_address`, `landmark`, `village_town`, `taluka`, `district`, `city`, `state`, `country`, `pincode`, `constituency`, `sub_constituency`, `assembly_constituency`, `parliamentary_constituency` | **Move** → `geo.places` postal block + `geo.place_links` (link overrides for `landmark`, courier notes). Backfill one `home`/`current` link per user. |
| `country_code` | **Keep as a cache** (ISO2) of `user_profiles.country_iso2`, maintained by `set_user_country` — OR drop and join `user_profiles`. Decision in §11 of the plan. |
| `location` (POINT) | **Move** → the primary `home`/`current` link's `geo.places.coordinates`. |
| `latitude`, `longitude`, `coordinates` | **Drop** — `geo.places` GENERATED columns own these. |
| `constituency_geometry` … `country_geometry` (10 polygons) | **Drop** — `geo.admin_boundaries.boundary` (GLOBAL, one copy). |
| `constituency_latitude`/`longitude` … `country_latitude`/`longitude`, `postal_code_latitude`/`longitude` | **Drop** — derive from `geo.admin_boundaries.centroid`. |
| `constituency_geonameId` … `country_geonameId` | **Drop** — `geo.admin_boundaries.geoname_id` / `lgd_code`. |
| `current_location` (POINT), `current_location_latitude`, `current_location_longitude`, `current_pincode` | **Move** → `user_live_locations.coordinates` (+ resolved `place_id`). |
| `altitude`, `altitude_accuracy`, `heading`, `speed`, `location_accuracy`, `location_source`, `location_timestamp`, `location_timezone`, `location_ip`, `geocode`, `recorded_at`, `last_tracked_at`, `device_id`, `device_type`, `network_type`, `is_tracking_active`, `background_tracking_enabled` | **Move** → `user_live_locations` (last fix + flags) and `user_location_pings` (history). |
| `timezone` | **Drop from `users`** — `user_profiles.timezone_name` is already the source of truth (localization plan, implemented). |
| *(new)* `primary_place_id` | **Add** as an explicitly-documented read-optimization cache → `geo.places.id`, maintained by the address service; lets dispatch read a user's home place without a two-table join. |

After this, `users` keeps **only** `country_code` (optional cache),
`primary_place_id` (cache) and `timezone` removed — everything else is owned
by `geo` or the telemetry layer.

### 10.5 Organization scoping for users

Today `User` is `TenantScopedMixin` (`organization_id` **nullable**). The
requirement is that every user belongs to a tenant **and** an organization:

- Change the base to **`MultiTenantMixin`** (`organization_id` NOT NULL, plus
  the composite FK `(tenant_id, organization_id)` and
  `ix_users_tenant_org`). The existing manual audit/status/deactivation
  columns stay (they satisfy `ENTITY_COLUMNS`, so the tenancy conformance test
  passes).
- This is what makes `user_live_locations`, `user_location_pings` and every
  user address link inheritable from the user's organization, and it lets the
  `(tenant_id, organization_id, role_id)` composite FK guarantee a user can
  never hold a role from another organization.
- **Backfill is mandatory before the NOT NULL flip**: every user with a NULL
  `organization_id` is assigned its tenant's root organization (or the single
  organization), and the migration fails loudly if a tenant has several
  organizations and unassigned users. See plan M1.
- Trade-off to state: `MultiTenantMixin` uses `ondelete="CASCADE"` on
  `tenants`, where `TenantScopedMixin` uses `RESTRICT`. Deleting a tenant
  still cannot succeed while RESTRICT tables reference it; the cascade only
  fires for an already-empty tenant.

### 10.6 Organization scoping for roles

`Role` is currently `TenantEntityMixin` + `SoftDeleteFilteredMixin` with
uniqueness on `(tenant_id, code)`. The requirement is organization scope:

- Change to **`OrgEntityMixin`** (`organization_id` NOT NULL).
- Uniqueness becomes `(tenant_id, organization_id, code)` among live rows, and
  add `UniqueConstraint(tenant_id, organization_id, id)` so `users` can declare
  the three-column composite FK.
- `users` then declares
  `ForeignKeyConstraint(["tenant_id","organization_id","role_id"] →
  ["roles.tenant_id","roles.organization_id","roles.id"])`, so the database
  guarantees a user's role belongs to the user's own organization.
- **Behavioral consequence:** system roles (`owner`/`admin`/`member`) are
  currently seeded **per tenant** (`roles.service.seed_system_roles`). Under
  org scope they must be seeded **per organization** (on organization create,
  and backfilled). This is the main decision the plan flags.
- `roles.service.delete_role` counts holders via `User.role_id`; with the
  three-column FK it should count within the role's organization.

### 10.7 `zoho_id` on users

`users.zoho_id` already exists (`String(255)`, plain index) but is not a
first-class identity: no uniqueness, no link to the `zoho_users` mirror, no
sync provenance. The `zoho_users` module deliberately deferred linking
("an identity decision, not a mirror concern"). The requirement resolves that
deferral:

- Replace the plain index with a **partial unique index**
  `uq_users_zoho_id_live (tenant_id, zoho_id) WHERE deleted_at IS NULL AND
  zoho_id IS NOT NULL` — the same idiom every Zoho mirror uses.
- Align the type with the Zoho convention (`String(50)`) and document the
  crosswalk: `users.zoho_id` ↔ `zoho_users.zoho_id`, with email as the
  fallback match key.
- Optionally adopt `ZohoIdentityMixin` for `public_id` correlation if users is
  ever pushed to Zoho; if not, add only `zoho_synced_at`. The plan recommends
  the minimal option (index + crosswalk) until a push requirement exists.

### 10.8 Why this is better than the current design

| Axis | Current `users` location model | Target |
|---|---|---|
| Coordinate truth | 5+ disagreeing copies | one `geo.places.coordinates`, GENERATED decimals |
| Boundary storage | per-user polygons (MBs each) | one GLOBAL `geo.admin_boundaries` row |
| Address reuse | none — typed per user | address book, shared across owners |
| Address history | overwritten in place | effective-dated links + `GET /addresses/history` |
| Verification | boolean-ish | `VerificationMixin` on place *and* link |
| Live tracking | writes on the master row | isolated 1:1 + partitioned history |
| Retention | none | `DataRetentionSchedule` + partition drop |
| Tenant isolation | tenant only, org nullable | tenant **and** organization enforced by the DB |
| Role integrity | role of the tenant | role of the user's organization (3-column FK) |
| Zoho linkage | unindexed string | partial-unique crosswalk to `zoho_users` |

Net: the `users` row shrinks by roughly 80–90 columns, stops being a
write-hotspot, and the location data becomes reusable, historical,
verifiable, globally-referenced and retention-governed.

---

## 11. Addendum II (Sept 2026) — Vehicle, hubs, fleet partners, and locked design decisions

This addendum records the author's decisions on §1–§10 and analyses the newly
proposed **vehicle** schema, plus the two missing FK targets it and the
employment schema depend on: **`hubs`** and **`fleet_partners`**. The
actionable build steps are in
[`docs/implementation-plan/users-update-implementation-plan.md`](../implementation-plan/users-update-implementation-plan.md).

### 11.1 Locked decisions (these supersede earlier recommendations)

| # | Decision | Effect on this report |
|---|---|---|
| 1 | **Keep `kyc_audit_logs`.** | D-04 is withdrawn. `kyc_audit_logs` is the *compliance* ledger (cross-entity before/after snapshots); `activity_logs` remains the *operational/auth* trail. The boundary is now explicit; do not let them drift. |
| 2 | **`PoliceVerification` is a `BackgroundVerification` of type PVC.** | D-05 resolved. Drop the standalone `police_verifications` table. `BackgroundVerification` keeps the PVC fields (`pvc_certificate_number`, `pvc_issued_date`, `pvc_valid_upto`, `police_station_jurisdiction`) and the renewal chain (`supersedes`/`renewed_from_id`). |
| 3 | **`uid_token` is required.** | D-11 resolved. Keep `uid_token`. To satisfy UIDAI, isolate it from the demographic extract — store it in a sibling `aadhaar_uid_tokens` row (or fully inside the ADV) rather than in the same row as `verified_name`/`verified_dob`/`verified_gender`/`verified_address`. |
| 4 | **`data_retention_schedules` is application data-retention only.** | D-07 resolved. It has nothing to do with `zoho_retention_policies` or sync-payload retention. The only open work is adding `retention_expiry_date` to the tables the purge job scans. |
| 5 | **Backfill is not mandatory — the schema may be dropped and migrations re-run.** | The plan is now **greenfield**: no dual-write, no backfill scripts, no rollout window. Write the target models and generate fresh migrations (§11.9). |
| 6 | **RBAC is managed explicitly.** | All RBAC risks/open questions are removed. Roles remain org-scoped as a data model; who may read Aadhaar/PAN/bank rows is out of scope here. |

### 11.2 Consent: a table, **not** a mixin

**Recommendation: keep `ConsentRecord` as a table; do not make consent a mixin.**

Why a mixin is wrong here:

- Consent is a **history**: a user consents, withdraws, and consents again,
  per purpose and per policy version. A mixin that embeds `consent_given` /
  `consent_at` columns snapshots one instant onto every consent-worthy table —
  multiple sources of truth, no history, and no way to answer "what did this
  user actually consent to, and when did they withdraw?".
- The mixin doctrine in this codebase is explicit: mixins carry **columns and
  tiny pure helpers only — never relationships or I/O**. A consent mixin that
  tried to navigate to its `ConsentRecord` would need a relationship, which is
  forbidden; without one it is just a dangling FK.
- Consent-worthy tables are heterogeneous (Aadhaar eKYC, biometric capture,
  BGV/PVC, location tracking, third-party sharing, marketing). They share the
  *link*, not the shape.

The correct decomposition:

- **`consent_records`** stays the single source of truth (purpose, channel,
  policy version, language, timestamps, withdrawal, `is_active`).
- A tiny **`ConsentBoundMixin`** may be added that contributes **only** a
  nullable `consent_id` FK and nothing else:

  ```python
  class ConsentBoundMixin:
      """Pure schema: links a consent-worthy row to its authorizing ConsentRecord.
      No relationship, no I/O — the service loads the consent when it needs it."""
      consent_id: Mapped[int | None] = mapped_column(
          BigInteger, ForeignKey("consent_records.id", ondelete="SET NULL"), index=True,
          comment="The consent that authorized this record",
      )
  ```

  Apply it to `AadhaarVerification`, `PANVerification`, `BackgroundVerification`
  (PVC), and any location-tracking/biometric record. Remove the inline
  `consent_given` / `consent_given_at` / `consent_ip_address` columns from
  `AadhaarVerification`; the `consent_records` row now carries them.
- The `users.consent_*_at` quick-flags remain documented **caches** only.

### 11.3 Verification: mixin for state, domain columns for fields — **no polymorphic verifications table**

This is the right answer to "should we build a polymorphic verification
schema?", and it has three parts.

**(a) Record-level verification state is already a mixin — keep it.**
`app/database/mixins.py:VerificationMixin` gives `verification_status`,
`verification_method`, `verification_data`, `verified_by`, `verified_at` and
`mark_verified()` / `mark_unverified()`. It is already applied to
`documents`, `geo.places`, `geo.place_links` (and would apply to `Vehicle`,
`Hub`, `FleetPartner`, `BackgroundVerification`). **Do not build a polymorphic
`verifications` table**: it would fragment the fast `is_verified` filter,
force a join on every eligibility check, and duplicate an existing, working
mechanism. "Mark a document verified" is already solved by
`Document.verification_status` + `document_verification_logs`.

**(b) Field-level verification is domain data — keep it domain-specific.**
`verified_name`, `verified_dob`, `verified_gender`, `verified_address` are
**extracted identity facts** returned by an eKYC provider. They are
inherently specific to the identity document that produced them. Putting them
into one polymorphic `verified_fields` JSONB would lose:
- type safety (a DOB becomes an untyped string),
- queryability ("every driver under 18 with a verified DOB"),
- the per-field provenance that identity disputes rely on.
They belong on `AadhaarVerification`, `PANVerification` and `DrivingLicense`,
each with its own columns.

**(c) The trap: "verification" and "certificate validity" are different axes.**
For the vehicle set this matters:

| Axis | Question | Where it lives |
|---|---|---|
| **Document verification** | Is the uploaded scan authentic and legible? | `Document.verification_status` (`VerificationMixin`) + `document_verification_logs` |
| **Certificate validity** | Is the certificate currently in force? | `VehicleComplianceDocument.status` (`ComplianceDocStatus`) + `valid_upto` |

A PUC certificate can be a perfectly genuine scan (verified) that has since
expired (not valid). Keep the two axes separate; do not collapse
`ComplianceDocStatus` into `DocumentVerificationStatus`.

**Cross-entity verification history** is already served by three ledgers —
`kyc_audit_logs` (compliance, kept), `activity_logs` (operational), and
`document_verification_logs` (document lifecycle). No fourth mechanism is needed.

### 11.4 The proposed Vehicle schema — review

The proposal is a solid domain model (master + per-certificate renewal chain +
structured DL), with the same class of architectural issues as the KYC schema.

**Strengths**
- `Vehicle` (master) separated from `VehicleComplianceDocument` (one row per
  certificate) is correct: the MVA six + VLTD/speed-governor/HSRP are *data*,
  not columns.
- `renewed_from_id` gives a real renewal chain — good for claims and RTO audits.
- `DrivingLicense` stores the *regulated, structured* facts (DL classes,
  commercial endorsement, Parivahan reference) instead of only "a document
  exists" — correct, and it mirrors the `documents` module's philosophy.
- `VehicleComplianceType` / `InsuranceType` / `PermitType` cover the statute
  accurately.

**Defects (same categories as §5)**

| Sev | Issue | Fix |
|---|---|---|
| P0 | Foreign base (`..Common.base`: `PrimaryKeyMixin`, `AuditColumnsMixin`, `SoftDeleteMixin`) | Use `IntPKMixin`/`BigIntPKWithUUIDMixin`, `OrgEntityMixin`, `VerificationMixin`, `SoftDeleteFilteredMixin`, `AppMetaMixin` |
| P0 | No tenant/org on any of the three tables | `vehicles`, `vehicle_compliance_documents`, `driving_licenses` → `OrgEntityMixin` (org NOT NULL) |
| P0 | FKs to `users`, `hubs`, `fleet_partners`, `documents` — only `users`/`documents` exist | Build `hubs` (§11.6) and `fleet_partners` (§11.7) first |
| P1 | `status` **and** `is_active` on `Vehicle` — two sources of truth | Drop `is_active`; use `StatusMixin.status` (`VehicleStatus`) + `DeactivationMixin` (repo doctrine: `deactivation_date IS NULL`, no `is_active`) |
| P1 | `verified_at` / `verified_by_id` / `verification_method` duplicate `VerificationMixin` | Use `VerificationMixin`; keep only the method typed to `DocumentVerificationMethod` via a CHECK |
| P1 | `registration_number` globally unique | Partial unique per tenant: `(tenant_id, registration_number) WHERE deleted_at IS NULL` (a plate may be re-registered after soft delete; tenants are separate books) |
| P1 | Relationships `owner`, `documents`, `compliance_documents` with no loader strategy | `lazy="raise"` on `options`-loaded paths; `selectin` where a collection is always wanted; state it explicitly |
| P1 | `vehicle_type` mixes form factor with EV variants **and** has `is_ev` + `fuel_type` | One vocabulary: `vehicle_type` = form factor (`two_wheeler`/`three_wheeler`/`four_wheeler_light`/`four_wheeler_heavy`/`van`/`bicycle`/`other`); `fuel_type='electric'` says EV; drop `is_ev` (derive) |
| P2 | `metadata_json` | Use `AppMetaMixin.app_metadata` for app data and `custom_attributes` JSONB (geo idiom) for business extras |
| P2 | `VehicleComplianceDocument` has no soft delete | Add `SoftDeleteFilteredMixin`; renewal-chain FK `(tenant_id, renewed_from_id)` |
| P2 | `rc_status_cache` / `overall_compliance_status_cache` | Keep as documented caches maintained by the compliance-evaluation job; `overall` is the dispatch gate |
| P2 | `documents` relationship re-implements `HasDocumentsMixin` | Use `HasDocumentsMixin` (derives `linkable_type='vehicle'`); `DocumentLinkableType.VEHICLE` already exists |
| P2 | `registration_number` normalization, `manufacture_year` bounds, `battery_capacity_kwh > 0` | Add CHECKs / a normalizer in the service |
| P3 | `registered_owner_name` free text beside `owner_user_id` | Keep as a snapshot (the RC owner may differ from the app user); pair with the existing `VEHICLE_OWNER_NOC` document type |

**Target shape (abbreviated):**

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
    registration_number: Mapped[str] = mapped_column(String(20), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(30), nullable=False)
    ownership_type: Mapped[str] = mapped_column(String(30), nullable=False)
    fuel_type: Mapped[str | None] = mapped_column(String(20))
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    fleet_partner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fleet_partners.id", ondelete="SET NULL"))
    hub_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("hubs.id", ondelete="SET NULL"))
    zoho_id: Mapped[str | None] = mapped_column(String(50))
    custom_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                    server_default=text("'{}'::jsonb"))
    # ... chassis/engine/make/model/color/capacity/vltd/gps/fastag unchanged ...
```

### 11.5 `DrivingLicense`

Mostly good; same fixes:

- `OrgEntityMixin`; `(tenant_id, user_id)` composite FK vs `users(tenant_id, id)`.
- The partial unique `is_current` must be
  `WHERE is_current AND deleted_at IS NULL` (the proposal omits `deleted_at`,
  the D-09 defect).
- `dl_number_encrypted` + `dl_number_masked` mirror the PAN/bank pattern — good.
- `verification_status` should reuse the shared `SubVerificationStatus` (or the
  documents `DocumentVerificationStatus`); `verification_method` typed to
  `DocumentVerificationMethod`.
- `valid_upto` NOT NULL is correct; add `CHECK (valid_upto >= valid_from)`.
- Link the scan through `HasDocumentsMixin`/`document_links` (owner
  `user`, role `owner`, purpose `identity_proof`) rather than a bare
  `document_id` on a second table — or keep `document_id` for the primary scan
  and the pivot for supporting evidence, consistently.

### 11.6 New module — **`hubs`**

A hub is an **operational** entity (warehouse / branch / dark store / spoke)
with capacity, a manager and operating hours. It is **not** a `geo.place`:
Design Rule Zero says a place has no owner, no telemetry — and a hub has a
manager, a zone and a cutoff time. So a hub **points at** a place and a
geofence; it does not absorb either.

```python
# app/modules/hubs/enums.py
class HubType(str, enum.Enum):
    WAREHOUSE = "warehouse"
    BRANCH = "branch"
    DARK_STORE = "dark_store"
    TRANSIT = "transit"
    SPOKE = "spoke"

# app/modules/hubs/model.py
class Hub(IntPKMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
          SoftDeleteFilteredMixin, HasDocumentsMixin, Base):
    __tablename__ = "hubs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_hubs_tenant_org_id"),
        Index("uq_hubs_tenant_org_code_live", "tenant_id", "organization_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
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
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str | None] = mapped_column(String(64))
    operating_hours: Mapped[dict | None] = mapped_column(JSONB, comment='{"mon": [["09:00","18:00"]], …}')
    daily_cutoff_time: Mapped[dt.time | None] = mapped_column(Time)
    storage_capacity_sqft: Mapped[float | None] = mapped_column(Numeric(10, 2))
    dock_count: Mapped[int | None] = mapped_column(Integer)
    vehicle_capacity: Mapped[int | None] = mapped_column(Integer)
    serviceable_pincodes: Mapped[list | None] = mapped_column(ARRAY(String))
    zoho_location_id: Mapped[str | None] = mapped_column(
        String(50), comment="Zoho location id whose geo.places row this hub operates at")
    custom_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                    server_default=text("'{}'::jsonb"))
```

Also add `"hub"` to `geo.place_links.OWNER_TYPES` (and its CHECK migration) so
a hub can have an address. `DocumentLinkableType.HUB` already exists, so
`HasDocumentsMixin` works unchanged. Delivery/beat modules will reference
`hubs` for HUB_BASED work.

### 11.7 New module — **`fleet_partners`**

A fleet partner is the legal entity (or individual) that supplies vehicles
and/or drivers. It is the `fleet_partner_id` target of `vehicles` and
`employment_records`, and the `ENTITY_PROOF` document subject (GST/CIN seeds
already exist in `documents/seed.py`).

```python
# app/modules/fleet_partners/enums.py
class FleetPartnerEntityType(str, enum.Enum):
    INDIVIDUAL = "individual"
    PROPRIETORSHIP = "proprietorship"
    PARTNERSHIP = "partnership"
    LLP = "llp"
    PRIVATE_LIMITED = "private_limited"

# app/modules/fleet_partners/model.py
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
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False,
                                             default=FleetPartnerEntityType.INDIVIDUAL.value)
    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
        comment="For individual/proprietorship partners, the person behind the entity")
    # statutory identity (same encrypt/mask pattern as PAN/bank)
    pan_masked: Mapped[str | None] = mapped_column(String(12))
    pan_encrypted: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(20))
    cin: Mapped[str | None] = mapped_column(String(25))
    tan: Mapped[str | None] = mapped_column(String(20))
    registered_address_place_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"))
    contact_person_name: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    # commercial
    contract_start_date: Mapped[dt.date | None] = mapped_column(Date)
    contract_end_date: Mapped[dt.date | None] = mapped_column(Date)
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    zoho_id: Mapped[str | None] = mapped_column(String(50))
    custom_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                                    server_default=text("'{}'::jsonb"))
```

The fleet-partner payout account is handled by making `bank_accounts`
payee-polymorphic (§11.8); the partner's proof documents are attached through
`HasDocumentsMixin` (GST/CIN, `ENTITY_PROOF`).

### 11.8 `bank_accounts` becomes payee-polymorphic

The proposed `bank_accounts.user_id` cannot own a fleet partner's payout
account. Replace it with the repository's polymorphic-owner pattern:

```python
owner_type: Mapped[str] = mapped_column(String(50), nullable=False)   # 'user' | 'fleet_partner'
owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
# CHECK owner_type IN ('user','fleet_partner'); composite index (tenant_id, owner_type, owner_id)
Index("uq_bank_accounts_one_primary", "tenant_id", "owner_type", "owner_id", unique=True,
      postgresql_where=text("is_primary AND is_active AND deleted_at IS NULL"))
```

`EmploymentRecord.bank_account_id` and the partner payout then both point at
the same table, and the "at most one primary account per payee" invariant is
database-enforced.

### 11.9 Greenfield migration policy

Per §11.1(5), the database may be dropped and migrations re-run, so:

- No backfill scripts, no dual-write, no `M1 data migration`, no rollout window.
- `users` and `roles` are altered in place (org scope, `zoho_id`, location
  columns dropped) and the new `geo`-backed location tables created — all as
  ordinary schema migrations on a fresh database.
- The `users-update-implementation-plan.md` migration sequence is rewritten for
  this reality.

### 11.10 New-module registration checklist

For `hubs`, `fleet_partners`, `vehicles`, `driving_licenses`,
`vehicle_compliance_documents`:

- [ ] Import models in `alembic/env.py`.
- [ ] `OrgEntityMixin` (org NOT NULL) on every table.
- [ ] Partial unique indexes carry `deleted_at IS NULL`.
- [ ] State a loader strategy on every relationship.
- [ ] Add `hub`, `vehicle`, `fleet_partner` to any closed morph CHECK
      (`geo.place_links.OWNER_TYPES` for hub; `DocumentLinkableType` already has
      `hub`/`vehicle`).
- [ ] Debezium include-list + search registry decisions per table.
- [ ] `tests/conftest.py` `_TEST_TABLES`.
- [ ] `docs/PROJECT_STRUCTURE.md`, `docs/MODULES.md`, and a module README per module.

---

## 12. Appendix — sources read

- `apps/core-platform/backend/app/modules/users/model.py`
- `apps/core-platform/backend/app/modules/users/schema.py`
- `apps/core-platform/backend/app/modules/users/audit.py`
- `apps/core-platform/backend/app/modules/users/lang/en.py`
- `apps/core-platform/backend/app/modules/users/api.py` (routes)
- `apps/core-platform/backend/app/modules/activity/model.py`
- `apps/core-platform/backend/app/modules/documents/model.py`, `mixins.py`
- `apps/core-platform/backend/app/database/mixins.py`
- `apps/core-platform/backend/app/common/time.py`
- `apps/core-platform/backend/app/common/response/schema.py`
- `apps/core-platform/backend/alembic/versions/` (localization migration present)
- `docs/architecture-prompts/master-prompt.md`
- `docs/implementation-plan/user-localization-timezone-and-messages.md`
- `docs/tenancy/README.md`
- `docs/AUDIT_AND_DATA_MODULES.md`
- `docs/dlp-prd/dlp-prd.md`
