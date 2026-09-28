# Media storage — local disk or GarageFS, public URLs for other apps

Configurable file/image storage with Spatie-style image conversions and
unauthenticated cross-application access to **public** media (user avatars
first). Code: `backend/app/modules/media/`, `backend/app/tasks/media.py`.

> This supersedes the storage/serving parts of
> [`new-media-implementation-guide.md`](./new-media-implementation-guide.md) and
> [`new-media-migration-guide.md`](./new-media-migration-guide.md) (owner-type
> registry, variants table, blurhash, …). Those describe a larger design that was
> not built; this is what runs.

## 1. Principles

1. **The disk is recorded per row.** `MEDIA_STORAGE_DRIVER` (`local` | `garage`)
   only chooses the disk for **new** uploads. Every `media.items` row carries its
   own `disk`, so flipping the driver never breaks a URL that was already issued.
2. **Public and private are physically separate.** Two buckets
   (`core-platform-media-public`, `core-platform-media-private`), and on local disk
   two directory trees (`<base>/public`, `<base>/private`).
3. **The only URL ever handed out is the proxy URL**
   `GET {MEDIA_PUBLIC_BASE_URL}/public/m/{media_id}/{variant}`. It never encodes
   the backend, so it survives a driver change.
4. **Async storage for the API, sync storage for Celery.** `storage.py`
   (aioboto3) vs `storage_sync.py` (boto3, one client per worker process).
5. **Replace, never overwrite.** A new avatar is a new `media_id` and new keys, so
   public URLs are cache-safe forever. The old row is soft-deleted; bytes are purged
   by a beat task after 24 h.
6. **Verify, don't provision.** The backend never creates buckets.

`local` is a dev / air-gapped fallback, not a production equivalent: one Garage
node (`replication_factor = 1`) has the same single point of failure as local
disk. It buys S3 semantics, not resilience.

## 2. Using it

### Other applications
```html
<img src="https://dlp.tarrinahealth.com/public/m/9e1c2f10-…/medium">
```
No key, session or CORS handling. `variant` is `original`, `thumb`, `medium` or
`large`; an extension is optional but must match (`medium.webp` ✓, `medium.png` 404).
Responses carry `Cache-Control: public, max-age=31536000, immutable`, an `ETag`
(`If-None-Match` → 304) and `Cross-Origin-Resource-Policy: cross-origin`. `HEAD` works.

**Everything that is not a public, ready image is a plain `404`** — never `403` —
so a caller cannot tell "doesn't exist" from "private". A variant that is not
generated yet is also `404` (with `Cache-Control: no-store`).

### The authenticated API
| | |
|---|---|
| `POST /api/me/avatar` | multipart `file` (PNG/JPEG/WebP, ≤10 MB, ≤40 MP). `202` + `{media_id, status, avatar_urls}`; `avatar_urls.original` is live at once, the others are `null` until generated. |
| `DELETE /api/me/avatar` | `204`, idempotent. |
| `GET /api/me/profile` | now includes `avatar_urls` (`null` = no avatar). Poll it until no value is `null`. |

Uploads are decoded, **re-encoded with all EXIF/GPS removed** (orientation baked
into the pixels first), and rejected before anything is stored or queued if they
are not an image, are truncated, or exceed 40 megapixels. The stored format comes
from the bytes, never from the client's `Content-Type`.

## 3. Configuration

| Setting | Meaning |
|---|---|
| `MEDIA_STORAGE_DRIVER` | `local` \| `garage` for **new** uploads (`s3` accepted as an alias; anything else stops the app at boot). |
| `MEDIA_LOCAL_BASE_PATH` | Local root (`/app/media/library`, on the `backend_media` volume shared by API and worker). |
| `MEDIA_PUBLIC_BASE_URL` | Absolute origin for public URLs. Compose defaults it to `https://$APP_DOMAIN`. Empty = relative URLs (own frontend only); production logs a warning. |
| `S3_ENDPOINT_URL`, `S3_BUCKET_PUBLIC`, `S3_BUCKET_PRIVATE`, `S3_REGION` | Garage. |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Default to `GARAGE_DEFAULT_ACCESS_KEY` / `_SECRET_KEY` in compose. |
| `MEDIA_PUBLIC_HOST` | Optional (compose only): serve `/public/m` from its own host (needs DNS). Default = `APP_DOMAIN`. |

### Turning Garage on
```bash
./manage.sh start            # (or dev / prod) — Garage assigns its own layout and creates the key
./manage.sh garage-init      # creates both buckets, grants the key, denies bucket creation. Idempotent.
# set MEDIA_STORAGE_DRIVER=garage in .env, then recreate the backend + worker
```
With `garage`, the backend does a `HeadBucket` on both buckets at startup and
**refuses to boot** if either is missing, naming the bucket and the fix.

Production (`docker-compose.prod.yml`) refuses to render without real
`GARAGE_RPC_SECRET`, `GARAGE_ADMIN_TOKEN`, `GARAGE_METRICS_TOKEN`,
`GARAGE_DEFAULT_ACCESS_KEY` (`GK` + `openssl rand -hex 12`) and
`GARAGE_DEFAULT_SECRET_KEY`. Garage reads its secrets from the environment itself,
so `garage.toml` needs no template rendering. The Web UI is at
`https://garage.$APP_DOMAIN` (needs a DNS record) behind the dashboard basic-auth.

### Switching drivers
Flip the variable and restart. Old rows keep resolving from their own disk; new
uploads go to the new one. There is no migration of existing bytes between disks.

## 4. Data model — `media.items`

One row per stored file. Tenant-scoped (`OrgEntityMixin`: `tenant_id` and
`organization_id`, composite FK), soft-deleted, optimistic-locked, like every
entity here.

* `uuid` — the public `media_id`, and the prefix of every key
  (`{uuid}/original.jpeg`, `{uuid}/thumb.webp`). `id` is internal.
* `model_type` / `model_id` / `collection` — owner (`user`, `users.id`) and group
  (`avatar`, `documents`). No FK, same shape as `geo.place_links`.
* `disk`, `visibility` — where the bytes are and who may see them (CHECK-constrained).
* `conversions` — `{variant: {status, file_name, w, h, size}}`, one JSONB key per
  variant, each written by its own subtask.
* `status` — the *conversion* lifecycle `pending → processing → done |
  partial_failure` (overrides `StatusMixin`'s `active`).

Collection policy and variants live in `conversions.py` (`COLLECTION_DEFAULTS`,
`USER_AVATAR_CONVERSIONS`: thumb 150, medium 400, large 800, WebP, cover-fit).

## 5. Pipeline (queue `documents`)

`upload → sanitise → save original → row + commit → chord( gen_variant × N ) → finalize_conversions`

* Each variant is its own idempotent subtask; one failing never blocks the others.
* Permanent failures (undecodable source, bad spec) are recorded at once and not
  retried. Transient ones (storage, DB) retry with backoff; **only the last attempt
  records the failure and returns `failed`** instead of raising — a chord callback
  fires only when every header task returns, so raising would leave the row stuck in
  `processing`.
* Workers merge one JSONB key each (`conversions || jsonb_build_object(k, v)`), so
  concurrent variants cannot overwrite each other.
* Worker DB access goes through the process's single event loop
  (`tasks/_loop.py`, ADR-3); there is no second, psycopg-based engine.
* `gc_deleted_media` (beat, every 15 min): purges media soft-deleted > 24 h ago
  (original + every variant, then the row). One unreachable disk is logged and does
  not stall the sweep.

A soft-deleted (replaced or removed) media is **404 at the origin immediately**; the
24 h window keeps the bytes so edge/CDN copies and an accidental delete are not
instantly unrecoverable.

## 6. Tests

`tests/test_media_imaging.py` (Pillow: GPS strip, orientation, 40 MP, truncation,
fit modes), `test_media_storage.py` (local ≡ Garage parity, sync and async; runs the
Garage half when `TEST_GARAGE_ENDPOINT/ACCESS_KEY/SECRET_KEY` are set),
`test_media_pipeline.py` (variants, chord semantics, retries, concurrent writes, GC),
`test_media_api.py` (upload, public router, driver-switch regression, replace,
rejections).

To run the Garage half, use the compose `garage` service (the dev override publishes
`:3900`), bootstrap it, and point the tests at it:
```bash
./manage.sh dev && ./manage.sh garage-init
TEST_GARAGE_ENDPOINT=http://localhost:3900 \
TEST_GARAGE_ACCESS_KEY=$GARAGE_DEFAULT_ACCESS_KEY TEST_GARAGE_SECRET_KEY=$GARAGE_DEFAULT_SECRET_KEY \
  pytest tests/test_media_storage.py
```
(The tests write under random `{uuid}/…` keys and delete what they create.)

## 7. Known limits

* A broker outage at upload time (or a worker killed mid-chord) leaves the row
  `pending`/`processing`; the upload still succeeds and the original is served.
  `requeue_stuck_media` (beat, every 10 min) re-dispatches the variants that are not
  `done` for rows idle > 15 min, and marks a row `partial_failure` after 24 h instead
  of retrying forever.
* Garage is one node: back it up (`./manage.sh garage-backup`, see
  [`media-production-rollout.md`](./media-production-rollout.md) §10).
* Replacing an avatar makes the previous URL 404 at the origin at once; a client
  holding the old URL must re-read the profile.
* Only the `avatar` collection has an endpoint. New collections: add a policy in
  `conversions.py` and call `media.service.replace_image` from the owner's own
  endpoint (which must validate the owner — there is deliberately no generic
  `/api/media/upload`).
* The previous `public.media` table was dropped by migration `768753121795`; it had
  no consumers and the migration refuses to run while it holds live rows.
