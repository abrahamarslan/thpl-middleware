# New Media Module — Migration Guide

> Status: **Design / pre-implementation**
> Companion doc: [`new-media-implementation-guide.md`](./new-media-implementation-guide.md)
> Read that guide first for the target architecture, schema and imaging engine.

This guide answers three questions:

1. **Which modules actually use our media?** (the honest inventory)
2. **What is the impact** of moving to the new module?
3. **How do we migrate** schema, code and data safely (expand → backfill →
   cutover → contract), with rollback?

The headline: **almost nothing uses `media` today.** The new module has a clean
slate, and the only live file system (`documents`) is deliberately left in place.
The migration is therefore mostly *schema + code*, not mass data movement.

---

## 1. Consumer inventory (ground truth)

### 1.1 Three overlapping file systems

| System | Table | Stores bytes? | Actually consumed? | Endpoint |
|--------|-------|---------------|--------------------|----------|
| `media` | `public.media` | Yes (local; S3 placeholder) | **No.** No model inherits `HasMediaMixin`; no module imports `media.service`. | `/api/media/*` |
| `files` | `public.files` (`FileEntity`) | No (S3 metadata only) | **No.** Imported only by its own router. | `/api/files/*` |
| `documents` | `documents`, `document_files`, `document_links`, … | No (provider-neutral metadata) | **Yes.** `HasDocumentsMixin` + direct FKs. | `/api/documents/*` |

### 1.2 `media` references (all of them)

| File | Lines | What |
|------|-------|------|
| `app/modules/media/{model,service,api,schema,storage,__init__}.py` | — | The module itself. |
| `app/tasks/media.py` | 30, 40–67 | Celery `generate_conversions` (Pillow resize). |
| `app/router.py` | 25, 76 | Imports + mounts `/api/media`. |
| `alembic/env.py` | 26 | Imports `media.model` for autogenerate. |
| `app/core/conf.py` | 445–461 | `MEDIA_STORAGE_DRIVER`, `MEDIA_LOCAL_BASE_PATH`, `MEDIA_PUBLIC_BASE_URL`, `AWS_*`, `MEDIA_S3_BUCKET`, `MEDIA_DIR`. |
| `tests/test_health.py` | 62 | Asserts `/api/media/upload` is registered. |
| `tests/conftest.py` | 129 | `"media"` in the truncate list. |
| `alembic/versions/20260705_1825_….py` | 145–169, 388–393 | Creates/drops `media`. |
| `alembic/versions/20260920_0900_….py` | 45, 50 | Lists `media` as entity/soft-delete table. |
| `alembic/versions/20260920_1500_….py` | 40 | Audit `updated_by_name` on `media`. |

**`HasMediaMixin`, `attach_media`, `MediaOut`, `__media_conversions__` appear in
NO other module.** The module is fully orphaned.

### 1.3 `files` references

`app/router.py` (+ import), `alembic/env.py`, and the module's own files.
**No other module imports `FileEntity`.** It duplicates both `media` and
`documents.document_files`.

### 1.4 Live `documents` consumers (do not break these)

`HasDocumentsMixin` (`app/modules/documents/mixins.py:33`) is inherited by:

| Module | File |
|--------|------|
| brands | `app/modules/brands/model.py:64,73` |
| manufacturers | `app/modules/manufacturers/model.py:47,73` |
| vehicles | `app/modules/vehicles/model.py:46,63` |
| hubs | `app/modules/hubs/model.py:43,51` |
| fleet_partners | `app/modules/fleet_partners/model.py:42,48` |
| emails | `app/modules/emails/model.py:31,35` |

Direct `documents.id` FKs: `vehicles/model.py:184,233`; `kyc/model.py:258,327,399,429`;
`hr/model.py:158,270`. Email attachments load `DocumentFile` via `DocumentLink`
(`app/tasks/emails.py:38–57`, `app/modules/emails/service.py:94–103`).

### 1.5 Image-like columns with no upload path

| Model | Column(s) | Status |
|-------|-----------|--------|
| `users` (`users/model.py:179–182`) | `image`, `avatar`, `thumbnail`, `preview_image` | Dead `String(255)` filenames; defaults `default.png`/`avatar.png`; **no endpoint writes them.** Exposed in `users/schema.py:104–107,522–524`. |
| `brands` (`brands/model.py:133`) | `logo_storage_key` | Bare key; unwired. In `brands/schema.py:53,72,87`. |
| `kyc` (`kyc/model.py:261`) | `selfie_storage_key` (on `liveness_verifications`) | Bare key; unwired. |
| `organizations` (`organizations/model.py:166–174`) | — | No logo/image field at all. |
| `zoho_users` (`zoho_users/model.py:37`) | `photo_url` | External Zoho URL; inbound mirror. |

### 1.6 Frontend

`apps/core-platform/frontend/src` is a 4-file stub (`main.tsx`, `App.tsx`,
`Search.tsx`, `vite-env.d.ts`). A grep for `media|avatar|logo|upload|files|documents`
returns **no matches**. There is no UI contract to preserve — the frontend work
is greenfield.

---

## 2. Impact analysis

### 2.1 Impact summary

| Module | Impact | Severity | Action |
|--------|--------|----------|--------|
| `media` | Total rewrite (schema → `media` PG schema, models, storage, imaging). | High (internal) | Replace module in place; no external contract. |
| `files` | Deprecate + remove. | Medium | Confirm zero rows, then drop table + module (Phase 6). |
| `documents` | **Share the storage layer** only; schema/semantics unchanged. | Low | Optional adapter so documents can use `StorageProvider`. No forced change. |
| `users` | Avatar moves to media collection `avatar`; legacy columns become compat pointers. | Medium | Add `HasMediaMixin`; backfill; then deprecate columns. |
| `brands` | `logo_storage_key` → media collection `logo`. | Medium | Backfill; keep column as compat pointer, then drop. |
| `organizations` | New logo capability via media. | Low | Add `HasMediaMixin` + collection. |
| `kyc` | `selfie_storage_key` → media collection `selfie` (P0; private). | High (data class) | Backfill; private delivery; retention rules. |
| `vehicles`/`hubs`/`fleet_partners`/`manufacturers` | No break; may add galleries later. | Low | None required now. |
| `emails` | Attachments stay on `documents`. | None | None. |
| Frontend | New upload components/hooks. | Low | Phase 3+. |
| Ops/Deployment | Garage service; env; backups. | Medium | This change (Phase 0). |
| Tests | Truncate list, health assertion, new suites. | Low | Update `tests/conftest.py:129`, `tests/test_health.py:62`. |

### 2.2 Boundary decision: media vs documents

- **`media`** = images and generic attachments needing transformations and
  placeholders (avatars, logos, product/gallery images, receipt images).
- **`documents`** = business documents with verification, link roles, OCR,
  versioning and email attachment semantics (PDFs, scans).
- They **share the `StorageProvider` abstraction** (one place that knows how to
  talk to Garage/local), but keep separate tables and services. This avoids a
  risky big-bang merge while eliminating duplicate *storage* code.
- `files` has no unique capability and is removed.

### 2.3 What must NOT change

- `documents` API, tables, verification flows, KYC/HR/vehicle FKs, email
  attachments — untouched in this migration.
- Tenant isolation, soft-delete and optimistic-locking conventions — the new
  `media` schema adopts them exactly (`tenant_id`, composite FK, `RowVersionMixin`,
  `SoftDeleteFilteredMixin`).

---

## 3. Target state & mapping

| Source | Target | Rule |
|--------|--------|------|
| `public.media` (rows) | `media.media` | Map columns; `model_type`→`owner_type`, `model_id`→`owner_id` (cast), `conversions`→`generated_conversions`, `disk`, `size`, identity. Move bytes to the new key layout. |
| `public.media` (DDL) | dropped | After code removal (Phase 6). |
| `files.FileEntity` | dropped | After confirming zero rows / no consumers (Phase 6). |
| `users.image/avatar/thumbnail/preview_image` | `media` collection `avatar` | Backfill one media row + variants from a resolvable file, else keep defaults; retain columns as pointers then drop. |
| `brands.logo_storage_key` | `media` collection `logo` | Backfill a media row pointing at the existing key; copy bytes into the media bucket. |
| `kyc.selfie_storage_key` | `media` collection `selfie` | Backfill; `data_class='P0'`; private-only delivery. |
| `organizations` logo | `media` collection `logo` | New (no legacy data). |

### 3.1 Column mapping (`public.media` → `media.media`)

| Old | New |
|-----|-----|
| `uuid` | `uuid` |
| `model_type` | `owner_type` (registered code; unknown types must be registered first) |
| `model_id` (String(64)) | `owner_id` (bigint; rows whose owner does not exist are staged with `expires_at`) |
| `collection_name` | `collection_name` |
| `file_name` | `file_name` |
| `original_name` | `name` (display) / `custom_properties.original_name` |
| `mime_type`, `disk`, `size` | same |
| `conversions` (JSONB status map) | `generated_conversions` |
| `custom_properties`, `order_column` | same |
| `created_at`, `updated_at`, `deleted_at` | same |
| (new) | `tenant_id`, `organization_id` — derived from the owner or defaults; `storage_path` from key layout; `status` from conversion map; `width/height/orientation` extracted from the original. |

> If `public.media` is empty (expected), treat the mapping as a specification for
> future imports and skip byte movement.

---

## 4. Migration phases (expand → backfill → cutover → contract)

### Phase 0 — Infrastructure (this change)
- Garage service in compose (base/dev/prod) + `garage.toml`; Garage Web UI in
  prod; env templates (`GARAGE_*`, `MEDIA_*`).
- Backend default remains `MEDIA_STORAGE_DRIVER=local` until Phase 1 lands the
  S3 provider, so nothing regresses.
- Exit: `garage` healthy; bucket + key auto-created; Web UI reachable in prod.

### Phase 1 — Expand (additive, no behaviour change)
- Alembic revision: `CREATE SCHEMA media`; create `owner_types`, `media`,
  `media_variants`, `media_external_identities`; `check_owner_integrity` trigger;
  seed owner types. Add `"media"` to `alembic/env.py::_OWNED_SCHEMAS`.
- Implement models, storage abstraction (`local` + `s3`), service, API under the
  **new** tables. The old `public.media` and `files` remain untouched but still
  unused.
- Exit: `alembic upgrade head` clean; upload/get/delete round-trip on both disks.

### Phase 2 — Imaging & async
- `ImageEngine`, conversion sets, variants, blurhash/dominant colour, `media`
  Celery queue (`celery-worker -Q ...,media`).
- Update `tests/conftest.py` truncate list; extend `tests/test_health.py`.
- Exit: avatar set produces thumb/1x/2x WebP + blurhash; idempotent re-runs.

### Phase 3 — Adopt consumers (dual-write/compat)
Order by risk/importance:

1. **users avatar** — add `HasMediaMixin`; `POST /api/users/me/avatar` writes a
   media row; keep `users.avatar/thumbnail/preview_image` updated as compat
   pointers (dual-write) for one release.
2. **brands logo** — write media collection `logo`; keep `logo_storage_key` as a
   compat pointer.
3. **organizations logo** — new media collection.
4. **kyc selfie** — media collection `selfie`, `data_class='P0'`, private
   delivery; keep `selfie_storage_key` as compat pointer.
- Exit: new writes go to media; legacy columns mirror; reads can come from either.

### Phase 4 — Backfill (if legacy data exists)
- Run an idempotent backfill job that:
  1. counts legacy rows per source,
  2. creates `media` rows + variants,
  3. copies bytes into the configured media bucket/key layout,
  4. records a crosswalk (`app_metadata.legacy` or `media_external_identities`),
  5. is resumable and logs mismatches.
- Verify counts: `legacy_live == media_created + known_skips`.

### Phase 5 — Cutover
- Reads switch to media (`FeaturedImage`/`urls` from media first, legacy column
  only as fallback). Feature flag `MEDIA_V2_READS=true` per deployment.
- Stop dual-write once reads are stable.
- Exit: one full release with no fallback reads.

### Phase 6 — Contract / cleanup
- Drop legacy columns (`users.image/avatar/thumbnail/preview_image`,
  `brands.logo_storage_key`, `kyc.selfie_storage_key`) in a dedicated revision.
- Drop `public.media`; remove `files` module + table + migration import + router.
- Remove legacy settings/aliases.
- Exit: no references remain; migrations reversible to Phase 5.

---

## 5. Backfill strategy (detail)

**Principle:** idempotent, resumable, batched, crosswalk-ledgered.

```
for each source row batch (keyset paginated):
    key = f"legacy:{source}:{id}"
    if crosswalk.exists(key): continue
    bytes = resolve_bytes(row)              # local path | S3 key | skip
    if bytes is None: record_skip(row); continue
    media = media_service.import_bytes(bytes, owner=..., collection=...,
                                       source_key=key, data_class=...)
    crosswalk.upsert(key, media.uuid)
    if batch done: log progress; checkpoint
```

- **Crosswalk** lives in `media.media_external_identities` (connection =
  `legacy-importer`) or `media.custom_properties.legacy`.
- **Byte resolution**:
  - local volume: legacy file names resolved under the old `MEDIA_LOCAL_BASE_PATH`;
  - S3: derive the old key; copy object to the new key (server-side copy if same
    endpoint, else stream).
- **Default-only columns** (`default.png`, `avatar.png`): skip as "no real file".
- **Owners that no longer exist**: import as staged (`expires_at`) so the TTL
  sweep can clean them up.
- **KYC selfies**: `data_class='P0'`, private delivery, short retention.

Because `public.media` and `files` are expected to be empty and the user avatar
columns are dead, the backfill is anticipated to be a **no-op or a handful of
brand logos**. Confirm with the count queries below before scheduling work.

```sql
SELECT count(*) AS media_rows FROM public.media;
SELECT count(*) AS file_rows  FROM public.files;
SELECT count(*) FROM public.users
 WHERE image NOT IN ('default.png') OR avatar NOT IN ('avatar.png')
    OR thumbnail NOT IN ('default.png') OR preview_image NOT IN ('default.png');
SELECT count(*) FROM core.brands WHERE logo_storage_key IS NOT NULL;
SELECT count(*) FROM public.liveness_verifications WHERE selfie_storage_key IS NOT NULL;
```

---

## 6. Backward compatibility

- **API:** the new `/api/media` surface is replaced; the old one was unused.
  Keep `MediaOut` field names where sensible and add fields (`blurhash`, `srcset`,
  `dominant_color`). Additive only.
- **Legacy columns:** retained as pointers during Phases 3–5 so existing
  serializers (`users/schema.py`, `brands/schema.py`) keep working unchanged.
- **Settings:** support the legacy `AWS_*` / `MEDIA_S3_BUCKET` names as aliases
  for one release, then remove.
- **`documents`:** unaffected; storage sharing is optional and additive.

---

## 7. Rollback plan

| Phase | Rollback |
|-------|----------|
| 0 (infra) | Stop/remove Garage service; set `MEDIA_STORAGE_DRIVER=local`. App unaffected. |
| 1 (expand) | `alembic downgrade` drops the `media` schema (data is new; take a dump first). Old `public.media`/`files` still intact. |
| 2 (imaging) | Remove `media` queue from worker; revert code. No schema change. |
| 3 (adopt) | Turn off media reads (`MEDIA_V2_READS=false`); legacy columns were still dual-written ⇒ instant fallback. |
| 4 (backfill) | Drop imported rows via the crosswalk; legacy bytes untouched (copy, not move, until Phase 6). |
| 5 (cutover) | Flag off ⇒ fallback reads. Legacy columns intact. |
| 6 (contract) | Restore from pre-migration dump; re-add drop-revision downgrade. |

**Golden rule:** during Phases 3–5 we **copy** bytes, never move, and dual-write
pointers, so any phase is reversible without data loss. Destructive drops happen
only in Phase 6, behind a fresh backup.

---

## 8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `model_id` string → bigint cast fails | Medium (if rows exist) | Medium | Pre-validate; stage non-castable rows with `expires_at`; report. |
| Owner tables not in `owner_types` | Medium | High (trigger 23503) | Seed all types up front; unknown types rejected at insert by design. |
| Trigger perf on bulk insert | Low | Medium | Deferred to commit; batch imports; monitor. |
| Garage single-node = no redundancy | High | High | Documented ops risk; off-node backups (see §10); plan 3-node cluster. |
| AVIF encode CPU cost | Medium | Medium | WebP default; AVIF opt-in per conversion; scale `media` workers. |
| EXIF/GPS leakage (P0 KYC) | Medium | High | Auto-orient + strip on every variant; private delivery; tests. |
| Legacy URL/key change breaks references | Low (few consumers) | Medium | Crosswalk + compat pointers; proxy resolves old keys during transition. |
| `documents` accidentally impacted | Low | High | No schema change; storage sharing is opt-in; keep tests green. |
| Frontend has no upload flow yet | High | Low | Greenfield components in Phase 3+. |

---

## 9. Validation & acceptance tests

- **Schema:** `alembic upgrade head` on a fresh DB creates the `media` schema,
  tables, trigger, seed. `alembic downgrade` reverses cleanly.
- **Integrity:** inserting media with an unregistered `owner_type`, a
  non-existent owner, or a cross-tenant owner raises `23503` at commit.
- **Tenancy:** tenant A cannot read/write tenant B's media (ORM filter +
  composite FK + storage prefix + proxy check).
- **Imaging:** declared set produces expected dimensions/formats; EXIF stripped;
  focal anchoring respected; blurhash non-empty; idempotent re-run.
- **Dedupe:** identical bytes in the same org reuse the row (flag on);
  identical bytes in another org do **not**.
- **Storage:** local and Garage round-trip; missing source degrades gracefully.
- **Consumers:** avatar/logo/selfie endpoints write media and keep compat
  pointers; `documents`/email-attachment tests unchanged.
- **Regression:** `tests/test_health.py` passes; `tests/conftest.py` truncates
  the new tables; full suite green.

---

## 10. Cutover runbook (condensed)

1. **Pre-flight:** confirm counts (§5); take a PostgreSQL dump + a Garage
   metadata/data snapshot; record `MEDIA_STORAGE_DRIVER`.
2. **Deploy Phase 1–2** (`alembic upgrade head`; worker gets the `media` queue).
3. **Smoke:** upload an avatar end-to-end; verify variants + blurhash + URLs.
4. **Backfill** (if needed): run the idempotent job; reconcile counts.
5. **Adopt** consumers (Phase 3); verify compat pointers on read.
6. **Flip reads** (`MEDIA_V2_READS=true`) for one release; monitor error rate.
7. **Stop dual-write**; verify no fallback reads in metrics/logs.
8. **Backup, then Phase 6 cleanup** (drop legacy columns/`public.media`/`files`).
9. **Post-cutover:** monitor `media_conversion_failures_total`,
   `media_uploads_total{result=failed}`, storage health; keep the rollback path
   for one cycle.

### Garage backup note
The generic `backup` volume job must **not** blindly copy live Garage metadata
(LMDB/`sqlite-wal` can be inconsistent). Use Garage-native snapshots
(`metadata_auto_snapshot_interval` / `garage meta snapshot`) plus off-node
replication (rclone/restic to object storage) for `data_dir`. Document the
restore procedure before go-live.

---

## 11. Ownership & timeline (suggested)

| Phase | Owner | Estimated effort |
|-------|-------|------------------|
| 0 Infra | Platform/Ops | 0.5 day |
| 1 Core | Backend | 3–4 days |
| 2 Imaging | Backend | 4–5 days |
| 3 Adoption | Backend + Frontend | 3–5 days |
| 4 Backfill | Backend/Data | 0.5–2 days (data-dependent) |
| 5 Cutover | Backend/Ops | 1 day |
| 6 Cleanup | Backend | 1 day |

---

## Appendix — Compatibility surface changed

| Surface | Change | Migration |
|---------|--------|-----------|
| `/api/media/upload` | Replaced by `POST /api/media` (+ presign/complete, variants). | N/A (unused). |
| `MediaOut` | Additive: `blurhash`, `dominant_color`, `srcset`, richer `urls`. | Update `media/schema.py`; keep `urls: dict`. |
| `app/core/conf.py` media settings | Renamed/expanded (`MEDIA_S3_*`, imaging, security). | Alias legacy `AWS_*` for one release. |
| `alembic/env.py` | Add `media.model` (exists) and `"media"` to `_OWNED_SCHEMAS`. | One-line change. |
| `tests/conftest.py` truncate list | Add `media.media_variants`, `media.media`, `media.owner_types`, `media.media_external_identities`. | Test update. |
| `app/modules/files` | Removed. | Phase 6; confirm zero consumers. |
| `public.media` | Dropped. | Phase 6; confirm zero rows. |

---

## Appendix — Tooling to add for the migration

- `scripts/media_backfill.py` — idempotent, keyset-paginated importer with
  crosswalk ledger, `--dry-run`, `--limit`, `--source`.
- `deployment/healthcheck/test-garage.sh` — assert Garage admin health + bucket
  presence.
- `alembic/versions/…_media_module.py` — Phase-1 expand revision (and a separate
  Phase-6 contract revision).
