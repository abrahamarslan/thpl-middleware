# Documents — catalog, logical documents, files, links and verification

**Code:** `app/modules/documents/` · **Tables:** `document_types`, `documents`, `document_files`,
`document_links`, `document_verification_logs` · **Tenancy:** [docs/tenancy/README.md](../tenancy/README.md) ·
**Migration:** `509eb251e3b3` · **Tests:** `tests/test_documents.py`

## 1. Model

```
document_types (GLOBAL)                       the catalog: AADHAAR, DRIVING_LICENSE, GENERAL, …
      ▲ document_type_id
documents (ENTITY)  ◄── document_files (ENTITY)      the LOGICAL document ◄── its PHYSICAL files / pages
      ▲                                              (one row: type, verification, printed metadata,
      ├──── document_links (ENTITY)                   versioning, retention)
      │       what it belongs to (user / vehicle / email / …) and in what role
      └──── document_verification_logs (LEDGER)    immutable trail of every status transition
```

**A logical document, many files.** A two-sided document (Aadhaar, DL) is *one* document with *two*
files. Modelling the sides as separate types (`AADHAAR_FRONT`/`_BACK`) made two disconnected rows whose
sides could be mismatched with no shared verification. Here the type is `AADHAAR`
(`requires_front_and_back`), the sides are pages of one row, and the pair is verified and versioned as a
set.

**A pivot, not `owner_type` / `owner_id`.** One document can belong to several entities — a vehicle RC scan
to the vehicle *and* to its owner user — with exactly one of them in the `owner` role.
`PolymorphicOwnerMixin` says "this row belongs to ONE entity", which is the wrong claim, so
`document_links` declares `linkable_type` / `linkable_id` itself and adds a `link_role`.

**Generic files are documents too.** Email attachments, exports and scans with no compliance meaning are
documents of the `GENERAL` type (never a checklist item). One row shape for everything; no second file table.

| Table | Class | Notes |
|---|---|---|
| `document_types` | GLOBAL | platform-wide reference data, like countries. Per-tenant catalogs would need `tenant_id` and a new `code` uniqueness |
| `documents` | ENTITY | `BigIntPKWithUUIDMixin` (the public id is `uuid`), tenant + audit + status + row_version + app meta, `VerificationMixin`, `DeactivationMixin`, `SoftDeleteFilteredMixin`, `HasTagsMixin` |
| `document_files` | ENTITY | composite FK `(tenant_id, document_id)` → `documents (tenant_id, id)`: a file can never point at another tenant's document |
| `document_links` | ENTITY | same composite FK. Attaching is the INSERT, detaching is the soft delete — no separate attach/detach columns |
| `document_verification_logs` | LEDGER | append-only. FK to `documents` is **RESTRICT** (the reference design cascades): purging a document is a deliberate act that decides what happens to its trail |

### What our mixins replaced

The reference design declared these by hand on every table; here they come from
[`app/database/mixins.py`](../tenancy/README.md#2-mixins-appdatabasemixinspy):

| Reference | Here |
|---|---|
| `tenant_id`, `organization_id`, `created_by(_name)`, `updated_by(_name)`, `app_version`, `app_metadata`, `row_version` | `TenantEntityMixin` |
| `verified_by_id`, `verified_at`, `verification_method`, `ocr…` provider payload | `VerificationMixin` (`verified_by`, `verified_at`, `verification_method`, `verification_data` = the raw provider payload) |
| `is_active`, `deactivated_reason`, `deactivation_date`, `deactivated_by_id` | `DeactivationMixin` — `deactivation_date IS NULL` *is* "active"; no second flag |
| `deleted_reason` + soft delete | `SoftDeleteFilteredMixin` |
| link `attached_by/at`, `detached_by/at` | `created_by/at`, `deleted_by/at/reason` |

`documents.verification_status` overrides the mixin column with `String(30)`: the lifecycle here is longer
(`resubmission_required` is 21 characters) and begins before any file exists.

## 2. Lifecycle

```
pending_upload ─► uploaded ─► in_review ─► verified ─► expired
                      │            │           │
                      └────────────┴─► rejected ┴─► resubmission_required
```

`ALLOWED_TRANSITIONS` (`enums.py`) is the single source; a refused transition is a **409** that lists the
allowed targets and changes nothing. Every transition — through `verification.transition()` — keeps
`is_verified` in step with the status (the database also checks: `chk_document_is_verified_cache`) and appends
one row to `document_verification_logs` in the same transaction, with a snapshot of the document's owner link.

| Action | From | To | Who |
|---|---|---|---|
| register / add file (requirement met) | `pending_upload` | `uploaded` | any user |
| `submit` | `uploaded` | `in_review` | any user |
| `verify` | `uploaded`, `in_review` | `verified` | `TenantAdmin` |
| `reject` | `uploaded`, `in_review`, `verified` | `rejected` | `TenantAdmin` |
| `request-resubmission` | `in_review`, `rejected`, `expired` | `resubmission_required` | `TenantAdmin` |
| expiry sweep | `verified` (past `expiry_date`) | `expired` | system (`actor_type = system`) |

"The requirement is met" = one file, or a front **and** a back for a two-sided type.

**Resubmission is not a transition.** `POST /{id}/resubmit` creates a **new version**: a new row
(`version_number + 1`, `supersedes_document_id`, `resubmission_count + 1`) that starts at `uploaded`, inherits
the old row's owners, and leaves the old row as evidence of what was rejected and why. A document is
superseded at most once (`uq_documents_supersedes` — two concurrent resubmissions cannot both create v2).
Lists return only the latest version unless asked (`all_versions=true`).

**Authorisation is interim.** Reviewer actions require `TenantAdmin` (a platform admin, or a user whose role
code is `admin`/`owner`), exactly like tenant management. A finer `documents.verify` permission arrives with
RBAC.

## 3. Rules the service enforces

* **Aadhaar is never stored.** Only the front/back *images* are files; the number is masked to its last four
  characters (`XXXXXXXX9012`). `document_types.allows_full_number_storage = false` makes the service discard the
  full number — no caller can persist it by mistake. The masked number and the UIDAI Data-Vault reference belong
  to a KYC module.
* **Other numbers are encrypted or dropped, never stored readable.** With `DOCUMENT_NUMBER_ENCRYPTION_KEY` set the
  full number is stored as `armor(pgp_sym_encrypt(number, key))`; with the key empty it fails closed (masked form
  only, and a warning is logged). The request field is a `SecretStr`: it is never echoed or logged.
* **One owner.** At most one `owner` link per document (`uq_document_links_one_owner`); other roles
  (`attachment`, `evidence`, `reference`, `version_of`) are unlimited; a link is unique per
  `(document, entity, role)`.
* **One front, one back.** `uq_document_files_side`. Extra pages are unbounded; the first file is the primary.
* **No duplicate uploads.** The same sha256 twice in a request, or one already on the document → refused.
* **Expiry is pre-filled** from `default_validity_days` (`issued_date` or today) when the type has an expiry and
  the caller gave none. `is_mandatory` follows the type's requirement for the `personnel_type` sent, if any.
* **Deactivated types** (`deactivation_date` set) are hidden from the catalog and refuse new documents.
* **Deletion is a soft delete of the document, its files and its links together**, and is logged, so no query
  can reach a deleted document through a child row (an email never sends the attachment of a deleted document).

## 4. API — `/api/documents`

| Method + path | Purpose |
|---|---|
| `GET /types`, `GET /types/{code}` | the catalog (`?category=`, `?include_deactivated=`) |
| `POST /` | register a document with its files and owners (after the bytes reached object storage) |
| `GET /{id}` · `DELETE /{id}?reason=` | read · soft delete |
| `GET /for-entity?linkable_type=&linkable_id=&roles=&all_versions=` | a user's / vehicle's / … documents |
| `POST /{id}/files` | add a page to a document that is still collecting files |
| `POST /{id}/links` · `DELETE /{id}/links/{link_id}?reason=` | link · detach |
| `POST /attach` | link existing documents to an entity (default role `attachment`) |
| `POST /{id}/resubmit` | the next version |
| `POST /{id}/submit` · `/verify` · `/reject` · `/request-resubmission` | lifecycle (last three: `TenantAdmin`) |
| `GET /{id}/logs` | the verification trail |
| `POST /render`, `GET /render/{task_id}` | Typst PDF generation (unchanged) |

Documents are addressed by `uuid` (returned as `id`); the BigInteger primary key never leaves the database.
Errors: business-rule violations are **422** `document_rule_violation`, unknown ids/types **404**, refused
transitions and duplicates **409**. Formatted values (`file_size_formatted`, `is_expired`) are computed in the
schema, never stored.

## 5. Attaching documents to your own model

```python
class Invoice(IntPKMixin, TenantEntityMixin, HasDocumentsMixin, Base): ...
# read:  select(Invoice).options(selectinload(Invoice.documents))
# write: documents.service.link_document(...)  /  documents.crud.attach_documents_to_entity(...)
```

The entity is named by `linkable_type_of(cls)` — the snake_case of the class (`Invoice` → `invoice`,
`BrandOwner` → `brand_owner`). The owner's primary key must be an integer. `linkable_type` is deliberately
**open at the database level** (no CHECK) so a new owner class needs no migration; the API validates it against
`DocumentLinkableType`, so add the class there.

Emails use exactly this: an email's attachments are the documents linked to it in the `attachment` role.
Inline-image data (`is_inline`, `content_id`) lives on the **link** (`document_links.context`), because the same
file can be inline in one email and a plain attachment in another. The delivery task reads the files of those
links, skipping deleted documents. Composing an email with an attachment id that does not exist is now a 404
instead of silently sending the email without the file.

## 6. Operating it

* **Seeding.** The migration seeds the catalog. `python scripts/seed.py --only documents.types` re-seeds
  idempotently and **never overwrites an existing row**, so an operator's edit survives. Correcting an existing
  row is a data migration. The seed data lives in `app/modules/documents/seed.py`
  (`SEED_DOCUMENT_TYPES`); add a type there and re-seed.
* **Expiry.** Celery Beat runs `app.tasks.documents.expire_due_documents` daily at 21:30 UTC (03:00 IST). It runs
  in system scope, across tenants.
* **Configuration.** `DOCUMENT_NUMBER_ENCRYPTION_KEY` (see `.env.example`).
* **Storage.** `file_storage_provider` is `s3`, `gcs`, `azure_blob` or `local_disk`; `file_key` is the object key
  (for `local_disk`, the path). There is no S3 client yet, so the delivery task skips object-store files with a
  loud log — as before.

## 7. Migration `509eb251e3b3`

Replaces the old single-owner `documents` table. **Every legacy row is migrated, none dropped:** one legacy row
→ one `GENERAL` document + one file + (when its owner id was numeric) one `attachment` link. The legacy UUID id
is kept as `documents.uuid`, so API ids, activity-log subjects and email references still resolve; tag pointers
(`taggables.taggable_id`) are re-pointed at the new id; `Email` becomes `email`. Fields with no home in the new
design are kept under `documents.app_metadata.legacy`; OCR fields move to `ocr_extracted_data`. A row-count
check aborts the whole transaction if any row is missing.

`downgrade` restores the legacy shape, **one legacy row per file**. Lost on the way down: documents without a
file, KYC metadata, versions, the catalog and the verification trail.

## 8. Deliberately not here

* **`consent_id` → `consent_records`.** There is no consent module; add the column and FK with it.
* **`AuditEntityType` (`kyc_audit_logs`).** Belongs to the KYC module that owns that table.
* **Downloads / presigned URLs and the `downloaded` audit action.** The enum value exists; it needs the S3
  client first.
* **A `document_types.is_active` column.** `DeactivationMixin` (see above).
* **`PersonnelType` lives in `documents/enums.py`** because the users module does not model personnel yet — the
  catalog depends only on the string values, so move it when that module does.
* **Per-type validation of the printed number** (PAN/GSTIN formats, DL checksum). It belongs with the
  third-party verification providers.
