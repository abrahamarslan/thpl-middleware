# New Media Module — Implementation Guide

> Status: **Design / pre-implementation**
> Owner: Platform Core
> Scope: `apps/core-platform/backend/app/modules/media`
> Companion doc: [`new-media-migration-guide.md`](./new-media-migration-guide.md)
> Deployment: Garage (S3-compatible) + local-folder fallback; Garage Web UI in prod.

This document specifies an enterprise-grade, **configurable** media module: a
single canonical attachment/image system with pluggable storage (local folder,
Garage, S3, future GCS/Azure) and a Spatie-style, declarative image
transformation pipeline (`fit`, `crop`, `manualCrop`, `focalPoint`,
`watermark`, `optimize`, format conversion to WebP/AVIF), plus placeholders
(`blurhash`) and optional perceptual fingerprints (`imagehash`).

It deliberately supersedes the current `app/modules/media` (which is **wired to
nothing**) and reconciles it with the live `documents` module. The migration
plan and consumer-impact analysis live in the companion guide.

---

## 0. Decisions at a glance (TL;DR)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | `media` becomes the **single canonical image/attachment** module. | The present `media`, `files` and the user avatar columns overlap; only `documents` is actually used. |
| D2 | **`documents` stays** for business documents (PDFs, verification, OCR, email attachments). Media and documents **share the storage layer**, not the schema. | Avoid a big-bang rewrite; documents has real consumers. |
| D3 | Storage is a **strategy** (`StorageProvider` protocol) resolved by a registry from settings. Providers: `local`, `s3` (Garage/AWS/MinIO), future `gcs`/`azure`. | "GarageFS or Folder based" without touching call sites. |
| D4 | Bytes are **never** in PostgreSQL. DB stores metadata + storage keys. | Proven, keeps DB small, enables CDN/presign. |
| D5 | Schema lives in a dedicated PostgreSQL **`media` schema** (`media.media`, `media.media_variants`, `media.owner_types`, `media.media_external_identities`). | Matches the approved design; isolates the module; add `"media"` to Alembic `_OWNED_SCHEMAS`. |
| D6 | Tenancy is added to the approved DDL: `tenant_id` + composite FK `(tenant_id, organization_id) → org_management.organizations`. | The approved SQL referenced a hypothetical `public.organizations`; in this repo orgs are in `org_management` and every entity carries `tenant_id`. |
| D7 | Use the codebase's **`RowVersionMixin`** (SQLAlchemy `version_id_col`), **not** the `bump_row_version()` trigger. | Every other table uses `version_id_col`; a trigger would fight the ORM's optimistic-lock bookkeeping. |
| D8 | Keep the **deferred `check_owner_integrity()` constraint trigger**. | DB-enforced polymorphic integrity + tenant boundary, stronger than `PolymorphicOwnerMixin`'s CHECK. |
| D9 | Conversions run in **Celery** on a dedicated `media` queue (not the request path). | CPU-bound Pillow work. Isolate from Typst PDF rendering. |
| D10 | Adopt **`blurhash`** now; treat **`imagehash`** as optional Phase 3 (exact dedupe is already covered by `content_hash` sha256). | See §7. |
| D11 | Delivery: **app proxy** for private/tenant-scoped assets, **presigned/public URLs** for public ones. Signed URLs are never stored. | Storage-key-only persistence (AP18), tenancy checks. |
| D12 | Uploads default to **direct-to-storage presign** for large files; small images may go through the API. | Offload bandwidth from FastAPI. |

---

## 1. Current state (why this rewrite)

Findings from the code audit (details + line references in the migration guide):

- `app/modules/media` exists and compiles, but **no domain model inherits
  `HasMediaMixin`** and **no module imports `media.service`**. It is dead code.
- `app/modules/files` (`FileEntity`, Laravel port) is a **second** generic file
  table, imported by no other module. Dead duplicate.
- `app/modules/documents` is the **live** file system:
  `HasDocumentsMixin` is used by `brands`, `manufacturers`, `vehicles`, `hubs`,
  `fleet_partners`, `emails`; `kyc`/`hr`/`vehicles` FK `documents.id`.
- `users.image/avatar/thumbnail/preview_image` are dead `String(255)` filename
  columns with no upload path.
- `brands.logo_storage_key` and `kyc.selfie_storage_key` are bare storage keys
  wired to nothing.
- The frontend consumes **none** of it.

So the media module has a clean slate: there is effectively **no data to lose**
and **no live API contract to preserve**, which is why this design favours the
correct target schema over incremental patching.

---

## 2. Goals / non-goals

**Goals**
1. One canonical `media` module for images and generic attachments.
2. Configurable storage: `local` folder or S3-compatible object storage
   (Garage first-class), selectable per deployment via env.
3. Declarative, Spatie-like conversions: `fit`, `crop`, `manualCrop`,
   `focalPoint`, `watermark`, `optimize`, WebP/AVIF/JPEG/PNG conversion,
   responsive sets, placeholders.
4. Tenant- and organization-scoped, soft-deleted, optimistically locked.
5. DB-enforced polymorphic ownership through a registry.
6. Asynchronous, idempotent, resumable processing.
7. Enterprise security: magic-byte sniffing, image-bomb limits, EXIF stripping,
   optional malware scanning, SVG refusal, path-traversal defence.
8. Observable: Prometheus metrics + structured logs + OTEL spans.

**Non-goals (initially)**
- Replacing `documents` schema/verification/OCR semantics.
- On-the-fly (runtime) image resizing at first request. Pre-generated variants
  are the default; URL-based dynamic transforms are a later option.
- Video transcoding (schema has `duration_seconds` for future use).
- A full DAM UI (folders, versions, sharing) — only the module and API.

---

## 3. Architecture overview

### 3.1 Package-by-feature layout

```
app/modules/media/
  __init__.py
  enums.py             # MediaStatus, VirusScanStatus, ConversionStatus,
                       # FitMode, ImageFormat, WatermarkPosition, DiskName
  model.py             # OwnerType, Media, MediaVariant, MediaExternalIdentity
  schema.py            # Pydantic: MediaIn / MediaOut / MediaUpdate / Presign*
  api.py               # HTTP surface (mounted at /api/media)
  service.py           # orchestration: validate → store → row → enqueue → events
  repository.py        # query helpers (owner lookup, default resolution)
  mixins.py            # HasMediaMixin v2 (+ __media_conversions__ declaration)
  owner_types.py       # registry codes/helpers + seed
  urls.py              # URL + signed-URL + srcset builders
  storage/
    __init__.py
    base.py            # StorageProvider protocol, StoredObject, PresignedUpload
    local.py           # LocalStorageProvider (atomic write, traversal guard)
    s3.py              # S3StorageProvider (aioboto3; Garage/AWS/MinIO)
    registry.py        # build providers from settings; get_storage(disk?)
  imaging/
    __init__.py
    engine.py          # ImageEngine: fit/crop/manualCrop/focalPoint/watermark/optimize
    conversions.py     # Conversion spec dataclasses + parser + named registry
    placeholders.py    # blurhash + dominant colour (+ optional LQIP)
    fingerprints.py    # sha256 content hash (+ optional perceptual hash)
    io.py              # decode/verify/orient helpers, decompression-bomb guard

app/tasks/media.py     # Celery: generate_conversions / purge_media (queue=media)
```

### 3.2 Layering (strict, one direction)

```
api.py ──▶ service.py ──▶ repository.py ──▶ model.py
                │
                ├──▶ storage/registry.get_storage()   (bytes out)
                ├──▶ imaging/*                         (pure CPU, in worker)
                ├──▶ activity.recorder                 (audit)
                └──▶ tasks.media (Celery enqueue)
```

- **No I/O or listeners in models/mixins** (repo convention).
- `api.py` stays thin: parse, authorize, call service, serialize.
- `service.py` owns the transaction; enqueue happens *after* flush with a
  `countdown` so the worker sees the committed row.
- `imaging/*` is pure and synchronous — it runs in the worker via
  `asyncio.to_thread`, never in the API loop.

### 3.3 Request/processing sequence

```
Client ──POST /api/media───▶ API ──▶ service.attach()
                                   ├─ magic-byte + size/pixel validation
                                   ├─ StorageProvider.put(original)
                                   ├─ INSERT media.media (status=processing)
                                   ├─ record_activity()
                                   └─ Celery(generate_conversions, countdown=2)
                                              │
                          media queue worker ─┤
                                              ├─ GET original (local path | S3 get)
                                              ├─ ImageEngine.run(conversion set)
                                              ├─ StorageProvider.put(variants)
                                              ├─ INSERT media.media_variants
                                              └─ UPDATE media.media
                                                   status=ready, generated_conversions=...
```

---

## 4. Storage abstraction (configurable: Garage or folder)

### 4.1 Protocol

```python
# app/modules/media/storage/base.py
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, AsyncIterator, runtime_checkable

@dataclass(frozen=True, slots=True)
class StoredObject:
    disk: str
    key: str                 # == media.storage_path
    size: int
    content_type: str | None = None
    etag: str | None = None

@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    method: str              # "PUT"
    headers: dict[str, str]
    key: str
    expires_in: int

@runtime_checkable
class StorageProvider(Protocol):
    name: str

    async def put(self, key: str, data: bytes | BinaryIO, *,
                  content_type: str | None = None,
                  metadata: dict[str, str] | None = None,
                  cache_control: str | None = None) -> StoredObject: ...
    async def get(self, key: str) -> bytes: ...
    async def stream(self, key: str, *, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    async def copy(self, src: str, dst: str) -> StoredObject: ...
    async def url(self, key: str, *, expires_in: int | None = None,
                  public: bool = False, filename: str | None = None) -> str: ...
    async def presign_put(self, key: str, *, expires_in: int,
                          content_type: str | None = None) -> PresignedUpload | None: ...
    def local_path(self, key: str) -> Path | None: ...
```

`local_path()` returns a real filesystem path **only** for `LocalStorageProvider`;
the worker uses it as a fast path, otherwise falls back to `get()` → temp file.

### 4.2 Providers

- **`LocalStorageProvider`** — base `MEDIA_LOCAL_BASE_PATH` (`/app/media/library`).
  Atomic write (`.tmp` → `os.replace`), `mkdir(parents=True)`, normalize +
  reject `..`/absolute keys, `async` via `asyncio.to_thread`.
- **`S3StorageProvider`** — `aioboto3` async client. Works with Garage, AWS S3,
  MinIO, R2. Config: `endpoint_url`, `region`, `bucket`, path-style flag,
  access/secret keys, optional SSE. Multipart for large objects, presign GET/PUT,
  server-side streaming for the proxy.
- Future: `GCSStorageProvider`, `AzureBlobStorageProvider` (same protocol).

### 4.3 Registry

```python
# app/modules/media/storage/registry.py
_PROVIDERS: dict[str, StorageProvider] = {}

def get_storage(disk: str | None = None) -> StorageProvider:
    name = disk or settings.MEDIA_STORAGE_DRIVER      # "local" | "s3"
    if name not in _PROVIDERS:
        _PROVIDERS[name] = _build(name)
    return _PROVIDERS[name]
```

Disks are named by capability, not vendor: `local`, `s3`. `MEDIA_STORAGE_DRIVER`
selects the default; `media.disk` and `media.conversions_disk` record what was
actually used, so a deployment can migrate disks later without ambiguity.

### 4.4 Object key layout

```
org_{organization_id}/tenant_{tenant_id}/{yyyy}/{mm}/{uuid}.{ext}          # original
org_{organization_id}/tenant_{tenant_id}/{yyyy}/{mm}/{uuid}/{conv}.{ext}   # variant
```

- Deterministic, tenant-safe prefix ⇒ the proxy can authorize by prefix alone.
- `uuid` is the media's public UUIDv7 (time-ordered, non-enumerable enough).
- No user-controlled segment ever reaches the key (no traversal, no PII).

### 4.5 Garage (S3-compatible) specifics

Garage is deployed alongside the stack (see `deployment/docker-compose*.yml`).
Key points for the app:

- Endpoint `http://garage:3900`, region `garage`, **path-style addressing**.
- v2.3.0+ supports `garage server --single-node --default-bucket` with
  `GARAGE_DEFAULT_ACCESS_KEY` / `GARAGE_DEFAULT_SECRET_KEY` /
  `GARAGE_DEFAULT_BUCKET`, so no manual `layout assign` / `bucket create`.
- The app uses the same default key for read/write. For least privilege in
  production, create a second read-only key for the CDN/proxy and restrict the
  app key to the media bucket.
- Garage **does not implement ACLs/policies**; use separate keys/buckets.
- `s3_web` can serve buckets as static websites — useful for public media via
  Traefik; private media should go through the app proxy or presigned URLs.

---

## 5. Image manipulation engine (Spatie-like)

### 5.1 Conversion specification

Conversions are **declared**, not imperative. A named conversion set maps to a
Spatie-style API:

```python
# app/modules/media/imaging/conversions.py
from dataclasses import dataclass, field
from app.modules.media.enums import FitMode, ImageFormat, WatermarkPosition

@dataclass(frozen=True, slots=True)
class Watermark:
    path: str | None = None          # PNG/SVG-raster asset
    text: str | None = None          # mutually exclusive with path
    position: WatermarkPosition = WatermarkPosition.bottom_right
    opacity: float = 0.6             # 0..1
    scale: float = 0.2               # relative to base width
    margin_px: int = 16
    tile: bool = False
    font: str | None = None
    colour: str = "#FFFFFF"

@dataclass(frozen=True, slots=True)
class CropBox:                       # manual crop, absolute pixels
    x: int
    y: int
    width: int
    height: int
    rotate_deg: float = 0.0

@dataclass(frozen=True, slots=True)
class Conversion:
    name: str
    width: int | None = None
    height: int | None = None
    fit: FitMode = FitMode.cover
    format: ImageFormat | None = None     # None = keep source format
    quality: int | None = None            # per-format default if None
    optimize: bool = True
    strip_metadata: bool = True
    background: str | None = None         # for contain/pad; "#RRGGBB" | "transparent"
    focal: tuple[float, float] | None = None   # (x%, y%) overrides media focal point
    crop: CropBox | None = None
    watermark: Watermark | None = None
    responsive: bool = False
    responsive_widths: tuple[int, ...] = ()
    blur: float | None = None             # gaussian radius
    greyscale: bool = False
```

Declaring a set on a model:

```python
class User(..., HasMediaMixin, ...):
    __media_owner_type__ = "user"
    __media_conversions__ = {
        "avatar": Conversion("avatar", 512, 512, FitMode.cover,
                             format=ImageFormat.webp, quality=82,
                             focal=True),
        "avatar_thumb": Conversion("avatar_thumb", 96, 96, FitMode.cover,
                                   format=ImageFormat.webp, quality=78),
    }
    __media_collections__ = {"avatar": {"single": True}}   # replaces old avatar
```

### 5.2 Operations

All are pure `PIL.Image` functions in `imaging/engine.py`.

**Pipeline order is fixed:** decode → EXIF auto-orient → manual/focal crop →
fit/resize → watermark → colour mode fix → encode/optimize → strip metadata.

- **`fit(img, mode, w, h, background)`**
  - `contain` — preserve aspect, fit inside (like `thumbnail`), pad with
    `background` when both w and h given.
  - `cover` — scale to cover then crop; anchored on the focal point (default
    centre) so faces/subjects survive cropping.
  - `fill` — stretch to exactly w×h (ignores aspect; rarely used).
  - `max` — downscale only (never enlarge), preserve aspect.
  - `min` — scale up/down to at least w×h.
  - `crop` — crop to w×h without scaling.
- **`crop(img, box)`** — rectangular crop; supports rotation.
- **`manualCrop(img, box)`** — same primitive, but the box comes from a stored
  user manipulation (`media.manipulations` JSONB) produced by the UI cropper.
  `manualCrop` takes precedence over focal/fit.
- **`focalPoint(img, x_pct, y_pct, w, h)`** — crop a w×h window centred on the
  focal point, clamped to the image bounds; a focal point near an edge shifts
  the window rather than cropping outside.
- **`watermark(img, spec)`** — overlay image (scaled, alpha-blended) or text
  (TTF via bundled font); 9 positions + free x/y; optional tiling; margins.
- **`optimize(img, fmt, quality)`** — format-aware encode:
  - JPEG: `optimize=True, progressive=True, quality, subsampling="4:2:0"`.
  - PNG: `optimize=True`, optional palette quantization.
  - WebP: `method=6, quality, lossless=False`.
  - AVIF: `quality` (Pillow ≥ 11.3 native libavif, else `pillow-avif-plugin`).
  - Strip ICC/EXIF/XMP unless `strip_metadata=False`.
- **format conversion** — `ImageFormat`: `jpeg | png | webp | avif | gif`
  (gif only passthrough initially). Unknown/unsupported → logged + skipped.
- Bonus (cheap to expose): `blur`, `greyscale`, `sharpen`, `background`,
  `autoOrient`.

### 5.3 Format support matrix

| Format | Pillow native | Notes |
|--------|---------------|-------|
| JPEG | ✅ | Baseline/progressive; strip EXIF. |
| PNG | ✅ | Alpha; optimize. |
| WebP | ✅ | Needs libwebp in the wheel (standard). |
| AVIF | ✅ Pillow ≥ 11.3 (libavif) | Fallback `pillow-avif-plugin` for older wheels. |
| GIF | ✅ read/animate | No re-encode initially. |
| SVG | ❌ (rasterize only) | **Refuse by default** (XSS). |
| HEIC/HEIF | ❌ | `pillow-heif` optional later. |

### 5.4 Decompression-bomb & resource guards

- Set `Image.MAX_IMAGE_PIXELS = settings.MEDIA_IMAGE_MAX_PIXELS` (e.g. 40 MP)
  and catch `Image.DecompressionBombError` → reject `422`.
- `ImageFile.LOAD_TRUNCATED_IMAGES = False`.
- Per-task memory ceiling in the worker; convert to RGB(A) early to cap RAM.
- Time/CPU limits on the Celery task.

---

## 6. Conversion pipeline, variants & responsive images

### 6.1 Named conversion sets

`ConversionsRegistry` provides reusable sets (`thumb`, `preview`, `avatar`,
`logo`, `gallery`, `receipt`) so models don't repeat specs. A model may declare
its own set, reference a named set, or pass an explicit set per upload
(detached/staged uploads).

### 6.2 `media_variants` rows

Each generated file becomes one `media.media_variants` row:
`variant_name` (`thumb`, `avatar_256`, `thumb_640`), `file_name`, `storage_path`,
`disk`, `mime_type`, `size`, `width`, `height`, `content_hash`, `status`.
`uq_media_variants_media_variant (media_id, variant_name)` makes regeneration
idempotent (upsert on conflict).

`media.generated_conversions` (JSONB) keeps the Spatie-compatible map
`{"thumb": true, "avatar": true}` for cheap reads; `responsive_images` holds the
srcset structure.

### 6.3 Responsive images

A conversion marked `responsive` produces a width ladder (default
`MEDIA_RESPONSIVE_WIDTHS = [320,640,960,1280,1920]`, clipped to the source
width), each optionally in WebP + AVIF, plus a small LQIP/blurhash. Structure:

```json
{
  "gallery": {
    "widths": [320, 640, 960],
    "formats": ["webp", "avif"],
    "variants": {
      "320": {"webp": "…/gallery_320.webp", "avif": "…/gallery_320.avif"},
      "640": {"webp": "…/gallery_640.webp", "avif": "…/gallery_640.avif"}
    },
    "sizes": "(max-width: 640px) 100vw, 50vw"
  }
}
```

`urls.py` renders `<picture>`/`srcset` from this, so the frontend never
string-builds URLs.

### 6.4 Task design (`app/tasks/media.py`)

- Queue: **`media`** (new; add to `celery-worker -Q ...`).
- `generate_conversions(media_id, conversion_names | set_name)`:
  1. Load media (`execution_options={"include_deleted": True}` to avoid races).
  2. Acquire a short Redis lock `media:conv:{id}` (avoid duplicate workers).
  3. For each conversion: skip if a `ready` variant with the same source
     `content_hash` exists (idempotent).
  4. Fetch source: `storage.local_path()` if local, else `get()` to a temp file.
  5. Run engine in `asyncio.to_thread`; persist variants; upsert rows.
  6. Update `media.status`, `generated_conversions`, `responsive_images`,
     `blurhash`, `dominant_color`, `width/height`, `orientation`.
  7. On per-conversion failure: `failed` status + `status_reason`; retry with
     backoff (`max_retries=3, retry_backoff=30`), then dead-letter.
- `purge_media(media_id)`: deletes original + variants from storage, marks
  `purged_at`, after the soft-delete retention window.
- **Idempotent & resumable**: a re-run only fills missing/failed variants.

---

## 7. Placeholders & fingerprints — is `blurhash`/`imagehash` useful?

Short answer: **`blurhash` yes (adopt now); `imagehash` not by default (optional
Phase 3).** They solve different problems.

### 7.1 `blurhash` — placeholder for instant loading

- Encodes an image into a **~20–35 character string** from which the client
  renders a smooth colour-gradient placeholder before the real bytes arrive.
- Excellent UX for galleries/avatars; costs one small downscale + encode.
- Maps directly to the approved `media.blurhash text` column (classified **P0**
  because it is a mathematical approximation, not the pixels).
- Add **three** placeholder fields together — they complement each other:
  - `blurhash` — rich gradient placeholder,
  - `dominant_color char(7)` — single hex colour, for solid backgrounds/spinners,
  - optional **LQIP** (tiny base64 WebP) in `custom_properties` for maximum
    fidelity (more bytes than blurhash; only if the UI needs it).
- Alternative to consider later: **ThumbHash** (even smaller, better aspect
  fidelity). BlurHash has broader client support today; start there.
- Dependency: `blurhash` (pure Python, uses NumPy). Compute at ~32×32 with
  components `(4, 3)` by default; make components configurable.

**Recommendation: adopt in Phase 2.**

### 7.2 `imagehash` — perceptual near-duplicate detection

- Computes perceptual hashes (`phash`, `dhash`, `ahash`, `whash`) that are
  *close* for *visually similar* images (resized/recompressed/recoloured).
- Useful for: near-duplicate suppression, "find similar", moderation, detecting
  a re-uploaded avatar, reverse-image style checks.
- **Not** a placeholder and **not** an exact-dedupe tool.

Why not by default:
1. **Exact dedupe is already solved and cheaper** by `content_hash` (sha256,
   already in the approved schema). Same bytes ⇒ same hash ⇒ reuse the media row.
   Perceptual hashing only adds value for *near* duplicates, which the product
   does not require yet.
2. **Heavy dependency**: `ImageHash` pulls **NumPy + SciPy** (SciPy ~40 MB),
   inflating the backend image for a feature nobody consumes.
3. **Fuzzy**: requires a Hamming-distance threshold and produces false
   positives; needs its own tuning and a review workflow to be safe.
4. **Storage/indexing**: to make it searchable you need a dedicated table or an
   index supporting XOR-popcount (`bit_count(phash # :probe) <= k`). SQLAlchemy
   exposure is awkward; it is genuinely Phase-3 work.

If adopted later, do it cleanly:
- New table `media.media_fingerprints (media_id, algorithm, hash bigint, bits)`
  (one row per algorithm) or columns `phash bigint` on `media`.
- Index with a BK-tree or `bit_count` expression; never compare in Python.
- Use 64-bit hashes only; store as `bigint`, not text.
- Keep it behind `MEDIA_FINGERPRINTS_ENABLED`.

**Recommendation: skip initially; add only when "similar images" is a real
requirement. `content_hash` (sha256) gives exact dedupe now.**

### 7.3 Exact dedupe (`content_hash`)

- sha256 of the original bytes → `bytea` (32 bytes, `ck_media_content_hash_len`).
- On upload, look up
  `ix_media_content_hash (organization_id, content_hash)`; if a live row exists,
  optionally **link/reuse** instead of re-storing bytes (configurable:
  `MEDIA_DEDUPE_ENABLED`).
- Dedupe is **per organization** (tenant boundary), never global.

---

## 8. Data model (adapted, tenancy-correct)

The approved DDL is largely preserved. **Required deviations** for this repo:

1. **Tenancy columns + composite FKs.** Add `tenant_id` and the FK
   `(tenant_id, organization_id) → org_management.organizations(tenant_id, id)`
   on `media`, `media_variants`, `media_external_identities` (mirrors
   `TenantScopedMixin`/`MultiTenantMixin`). The approved SQL referenced
   `public.organizations`, which does not exist here.
2. **Drop the `bump_row_version()` trigger.** Use `RowVersionMixin`
   (`version_id_col`) as every other table does.
3. **Keep `check_owner_integrity()`** (deferred constraint trigger), re-targeted
   to `org_management.organizations` / `public.users` / `core.brands`.
4. **`owner_types` is a GLOBAL registry** (no `tenant_id`) — admin-managed,
   allow-listed in the GLOBAL table policy. Its `target_table` may point at any
   owned schema.
5. Add `"media"` to `alembic/env.py::_OWNED_SCHEMAS`.

ORM mapping:

```python
class Media(
    IntPKMixin,          # bigint PK (GENERATED ALWAYS AS IDENTITY)
    BigIntPKWithUUIDv7Mixin,
    MultiTenantMixin,    # tenant_id NOT NULL + organization_id NOT NULL + composite FK
    AuditMixin, RowVersionMixin, AppMetaMixin, TimestampMixin,
    SoftDeleteFilteredMixin,
    Base,
):
    __tablename__ = "media"
    __table_args__ = (..., {"schema": "media"})
```

> Note: do **not** add `StatusMixin` — media owns its `status` state machine
> (`pending|processing|ready|failed|quarantined`), which is different from the
> entity `active` status. Compose the mixins explicitly as above.

The full DDL (tables, triggers, indexes, comments, seed, self-test) is in
**Appendix A**. Key behavioural constraints retained from the approved design:

- `ck_media_owner_pair` — `owner_type`/`owner_id` are both NULL or both set.
- `ck_media_unowned_expires` — staged (unowned) uploads must have `expires_at`
  (swept by a maintenance task).
- `ck_media_purged_needs_deleted` — `purged_at` only after `deleted_at`.
- `aspect_ratio` is a PG18 `GENERATED ALWAYS … STORED` column.
- Partial unique index `uq_media_owner_collection_default` — at most one default
  per `(organization_id, owner_type, owner_id, collection_name)`.
- `media_variants` unique `(media_id, variant_name)` + `ON DELETE CASCADE`.

---

## 9. Owners, registry & model integration

### 9.1 `owner_types` registry

One row per allowed polymorphic owner. `code` (`user`, `organization`,
`brand`, …), `target_table` (`public.users`, `org_management.organizations`,
`core.brands`), and `org_column` (`organization_id`, or `id` for organizations).
The deferred trigger validates both **existence** and the **tenant boundary**:

- owner row exists, and
- `owner_org_column == media.organization_id`, and (for user-owned) the owner's
  `organization_id` matches.

Unknown or soft-deleted owner type ⇒ `23503`. This makes the polymorphic link
a *database* guarantee, not a convention.

### 9.2 `HasMediaMixin` v2

```python
class HasMediaMixin:
    __media_owner_type__: ClassVar[str] = ""
    __media_conversions__: ClassVar[dict[str, Conversion]] = {}
    __media_collections__: ClassVar[dict[str, MediaCollection]] = {}

    @declared_attr
    def media(cls):
        return relationship(
            Media,
            primaryjoin=lambda: and_(
                foreign(Media.owner_id) == cls.id,
                Media.owner_type == cls.__media_owner_type__,
                Media.tenant_id == cls.tenant_id,   # tenancy safe-join
            ),
            viewonly=True,
            lazy="raise",                            # firewall (as today)
            order_by=Media.order_column,
        )
```

`MediaCollection` declares `single` (one file, e.g. avatar/logo) and max count.
The service enforces `single` by clearing the previous default / soft-deleting
the old file, within the transaction and protected by the partial unique index.

### 9.3 Profile avatar flow (the worked example)

```python
# user declares
__media_owner_type__ = "user"
__media_collections__ = {"avatar": MediaCollection(single=True)}
__media_conversions__ = {
    "avatar_thumb": Conversion("avatar_thumb", 96, 96, FitMode.cover,
                               format=ImageFormat.webp, quality=78),
    "avatar":       Conversion("avatar", 512, 512, FitMode.cover,
                               format=ImageFormat.webp, quality=82),
    "avatar_2x":    Conversion("avatar_2x", 1024, 1024, FitMode.cover,
                               format=ImageFormat.webp, quality=82),
}
```

1. `POST /api/users/me/avatar` (or generic `POST /api/media` with
   `owner_type=user, owner_id=<id>, collection=avatar`).
2. Service validates (magic bytes = image, ≤ size limit, ≤ pixel limit),
   stores the original to the configured disk under the tenant prefix, inserts a
   `media` row (`status=processing`), computes `content_hash`.
3. Enqueues `generate_conversions(media_id, "avatar")` on the `media` queue.
4. Worker produces `avatar_thumb`, `avatar`, `avatar_2x` + `blurhash` +
   `dominant_color`, sets `status=ready`, writes `media_variants`.
5. Response carries `urls` (`{original, avatar, avatar_thumb, avatar_2x}`),
   `srcset`, `blurhash`, `dominant_color`.
6. `is_default=true` for the avatar collection (partial unique index guarantees
   exactly one), and `users.avatar` is kept as a **compat pointer**.

The avatar is therefore "stored as a thumbnail with a configurable size, like
Spatie/image": sizes/formats/quality are declared once on the model; the engine
does the rest asynchronously.

---

## 10. HTTP API surface

Mounted at `/api/media` (JWT via `CurrentUser`, tenant-bound session).

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/media` | Multipart upload; `owner_type`, `owner_id`, `collection`, `conversions`, `is_default`, `name`, `custom_properties`. |
| `POST` | `/media/presign` | Request a presigned PUT (direct-to-Garage) for large files; returns `key` + headers. |
| `POST` | `/media/complete` | Finalise a direct upload (HEAD the object, insert row, enqueue). |
| `GET` | `/media/{uuid}` | Metadata + `urls` + `srcset` + placeholders. |
| `GET` | `/media/{uuid}/file` | App-proxy download/stream (authorizes tenant + ACL; `Content-Disposition`, `X-Content-Type-Options: nosniff`). |
| `GET` | `/media/for-entity` | List by `owner_type`, `owner_id`, optional `collection`. |
| `PATCH` | `/media/{uuid}` | Name, `order_column`, `is_default`, `focal_point_x/y`, `manipulations` (manual crop), `custom_properties`. |
| `POST` | `/media/{uuid}/conversions` | (Re)generate named conversions/variants. |
| `POST` | `/media/{uuid}/replace` | Replace original bytes; invalidate + regenerate. |
| `DELETE` | `/media/{uuid}` | Soft delete; queue purge after retention. |

Transport schemas (`schema.py`) expose **no storage keys to unprivileged
clients** — only derived URLs (`urls.py`). `MediaOut` maps the model's `urls`
property (kept, extended to include srcset/blurhash/dominant colour).

---

## 11. Delivery, URLs & caching

- **Public** media (logos, marketing): serve via a public base URL
  (`MEDIA_S3_PUBLIC_BASE_URL`) backed by Garage `s3_web` behind Traefik, or a
  CDN; long `Cache-Control: public, max-age=31536000, immutable` (keys are
  content-addressed by UUID + variant, never mutated in place).
- **Private/tenant-scoped** media (KYC selfies, receipts): always through
  `GET /media/{uuid}/file` with a tenancy/ACL check, or a short-TTL presigned
  GET. The DB stores keys only; **signed URLs are never persisted**.
- On replace, a new object key is written (the UUID+variant key is versioned by
  a `?v=` query or by suffix); never overwrite in place, so caches stay valid.
- `srcset`/`<picture>` is generated server-side from `responsive_images`.

---

## 12. Security

| Threat | Control |
|--------|---------|
| Malicious/renamed file | Magic-byte sniffing (`filetype`), extension allowlist per collection, Pillow `verify()`. |
| Decompression bomb | `Image.MAX_IMAGE_PIXELS`, reject `DecompressionBombError`, `LOAD_TRUNCATED_IMAGES=False`. |
| SVG XSS | **Refuse SVG by default**; if ever needed, rasterize server-side (never serve user SVG). |
| Path traversal | Keys are server-generated; local provider rejects `..`/absolute; no user segment in keys. |
| SSRF | Remote fetch only from an allowlisted host list; never fetch user-supplied URLs. |
| EXIF/GPS leakage | `exif_transpose` then strip EXIF/XMP/ICC (unless explicitly disabled) on every variant. |
| Malware | `virus_scan_status` state machine; optional ClamAV scan hook in the worker; quarantine disk/prefix; `clean` required before public serving. |
| Tenant leakage | Composite tenancy FK + `tenant_id` filter + storage prefix per tenant + proxy authorization. |
| Enumeration | Public UUIDv7 IDs, never sequential IDs in URLs. |
| Abuse | Size/pixel caps, per-user rate limits, `expires_at` TTL for staged uploads. |
| P0 data (KYC) | `data_class='P0'`, private delivery only, short retention, encrypt-at-rest at the storage layer if warranted. |

---

## 13. Configuration & dependencies

### 13.1 `app/core/conf.py` (new/changed settings)

```python
# --- Media (storage, imaging, delivery; docs/new-media-implementation-guide.md) ---
MEDIA_STORAGE_DRIVER: str = "local"            # local | s3   (s3 = Garage/AWS/MinIO)
MEDIA_LOCAL_BASE_PATH: str = "/app/media/library"
MEDIA_PUBLIC_BASE_URL: str = "/media/library"  # local/public delivery base
MEDIA_S3_ENDPOINT_URL: str = ""                # e.g. http://garage:3900
MEDIA_S3_BUCKET: str = "media"
MEDIA_S3_REGION: str = "garage"
MEDIA_S3_ACCESS_KEY_ID: str = ""
MEDIA_S3_SECRET_ACCESS_KEY: str = ""
MEDIA_S3_USE_PATH_STYLE: bool = True           # Garage requires path-style
MEDIA_S3_PUBLIC_BASE_URL: str = ""             # CDN / s3_web base for public assets
MEDIA_S3_SIGNED_URL_TTL: int = 900
MEDIA_MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024
MEDIA_IMAGE_MAX_PIXELS: int = 40_000_000
MEDIA_ALLOWED_IMAGE_FORMATS: str = "jpeg,png,webp,avif,gif"
MEDIA_BLURHASH_ENABLED: bool = True
MEDIA_BLURHASH_COMPONENTS_X: int = 4
MEDIA_BLURHASH_COMPONENTS_Y: int = 3
MEDIA_DEDUPE_ENABLED: bool = True              # exact sha256 reuse within an org
MEDIA_FINGERPRINTS_ENABLED: bool = False       # imagehash (phase 3)
MEDIA_RESPONSIVE_WIDTHS: str = "320,640,960,1280,1920"
MEDIA_PROXY_ENABLED: bool = True               # app-proxied private delivery
MEDIA_VIRUS_SCAN_ENABLED: bool = False
MEDIA_QUEUE: str = "media"
MEDIA_CONVERSION_LOCK_TTL_SECONDS: int = 600
```

(For compatibility, the legacy `AWS_*` / `MEDIA_S3_BUCKET` / `MEDIA_PUBLIC_BASE_URL`
names are either kept as aliases or migrated via the env templates.)

### 13.2 `requirements.txt` diff

```diff
 # --- Imaging ---
-Pillow>=11.0
+Pillow>=11.3                 # WebP + native AVIF (libavif) support
+# Object storage (S3-compatible: Garage, MinIO, AWS S3, R2)
+aioboto3>=13.2
+# Image placeholders (blurhash → numpy)
+blurhash>=1.1
+# Magic-byte content sniffing (pure-python; no libmagic system dep)
+filetype>=1.2
+# AVIF fallback ONLY if the Pillow wheel lacks libavif:
+# pillow-avif-plugin>=1.4
+# OPTIONAL phase 3 — perceptual near-duplicate detection (numpy+scipy):
+# ImageHash>=4.3
```

### 13.3 Packaging check

Verify the pinned `Pillow` wheel actually encodes AVIF:
`python -c "from PIL import features; print(features.check('avif'))"`.
If `False`, add `pillow-avif-plugin` (which bundles libavif) — the engine's
format registry will then advertise `avif` automatically.

---

## 14. Async processing & operational limits

- Dedicated `media` Celery queue; worker `-Q default,integrations,documents,media`.
- Concurrency tuned for CPU: Pillow is mostly C and releases the GIL; prefork
  workers parallelise well. Consider a small `--pool=prefork` worker with
  `MEDIA_CONVERSION_CONCURRENCY` and memory limits.
- Per-task `soft_time_limit`/`time_limit` guard against pathological images.
- Redis lock per `media_id` avoids duplicate conversions on retries.
- Failed conversions never fail the whole upload: `status=ready` can still hold
  a partial set; per-variant `failed` + `status_reason`.
- Retention: staged uploads (`owner_id IS NULL`) expire via `expires_at`; a
  scheduled `purge_media` deletes bytes after the soft-delete window.

---

## 15. Observability

- **Metrics (Prometheus):** `media_uploads_total{collection,result}`,
  `media_conversion_seconds{conversion,format}`, `media_conversion_failures_total`,
  `media_bytes_stored{disk}`, `media_variants_generated_total`, `media_dedupe_hits_total`.
- **Logs (structlog):** `media_uploaded`, `media_converted`,
  `media_conversion_failed`, `media_purged`, always with `media_id`, `tenant_id`,
  `organization_id`, `owner_type`.
- **Traces (OTEL):** upload + conversion spans; storage provider spans.
- **Health:** `/health` reports storage driver reachability (S3 head-bucket /
  local base writable) without failing the whole health check when storage is
  intentionally local.

---

## 16. Testing strategy

- **Unit (imaging):** golden-image fixtures per operation × format; assert
  dimensions, mode, format, EXIF stripped, focal anchoring, watermark placement.
- **Unit (storage):** Local provider (tmp dir, traversal, atomicity); S3 provider
  against Garage/MinIO in CI (or `moto` for pure logic).
- **Integration:** upload → conversion → variant rows → URLs; single-collection
  enforcement; dedupe; TTL sweep; owner-integrity trigger (registered vs
  unregistered vs cross-tenant owner).
- **Security:** bomb image, renamed executable, SVG refusal, traversal key,
  EXIF GPS stripping, oversize rejection.
- **Contract:** `alembic upgrade head` on a fresh DB includes the `media` schema;
  `test_health.py` still sees `/api/media/upload`; `tests/conftest.py` truncates
  the new tables.
- **Load:** 1k concurrent avatar uploads; conversion throughput/latency;
  degradation behaviour when Garage is down.

---

## 17. Roadmap / phases

| Phase | Deliverable | Exit criteria |
|-------|-------------|---------------|
| **0 — Infra (this change)** | Garage service in compose (base/dev/prod) + `garage.toml` + Garage Web UI in prod + env wiring. | `garage` healthy; bucket/a key auto-created; Web UI reachable in prod. |
| **1 — Core** | `media` schema migration; models; storage abstraction (`local`+`s3`); upload/get/delete; `HasMediaMixin` v2; owner registry + trigger. | Upload round-trips on both disks; trigger rejects bad owners/cross-tenant. |
| **2 — Imaging** | `ImageEngine` (all ops), named conversion sets, variants, blurhash + dominant colour, Celery `media` queue. | Avatar example produces thumb/1x/2x WebP + blurhash, idempotent re-runs. |
| **3 — Delivery** | URL/srcset builders, app proxy, presign direct upload, responsive sets. | Private assets blocked cross-tenant; public served via immutable cache. |
| **4 — Adoption** | users avatar, brands logo, organizations logo, KYC selfie; deprecate legacy columns. | See migration guide. |
| **5 — Hardening** | Dedupe UI, malware scan, purge/TTL jobs, optional imagehash, metrics dashboards. | Security + retention acceptance tests pass. |
| **6 — Cleanup** | Remove `files` module, drop `public.media`, drop legacy user image columns. | No references remain; migrations reversible. |

---

## Appendix A — Adapted DDL (`media` schema)

> Deviations from the approved SQL are marked **[DEV]**. Full file should be
> authored as an Alembic revision (not a raw `.sql`) so autogenerate stays
> authoritative.

```sql
CREATE SCHEMA IF NOT EXISTS media;

-- §1 Trigger: polymorphic owner integrity (deferred). [DEV] re-targeted tables.
CREATE OR REPLACE FUNCTION media.check_owner_integrity()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_target text; v_org_col text; v_ok boolean;
BEGIN
    IF NEW.owner_type IS NULL OR NEW.owner_id IS NULL OR NEW.deleted_at IS NOT NULL THEN
        RETURN NULL;
    END IF;
    SELECT ot.target_table, ot.org_column INTO v_target, v_org_col
      FROM media.owner_types ot
     WHERE ot.code = NEW.owner_type AND ot.deleted_at IS NULL;
    IF v_target IS NULL THEN
        RAISE EXCEPTION 'media %: owner_type % is not registered', NEW.uuid, NEW.owner_type
            USING ERRCODE = '23503';
    END IF;
    IF v_org_col IS NULL THEN
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s WHERE id = $1)', v_target::regclass)
           INTO v_ok USING NEW.owner_id;
    ELSE
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s WHERE id = $1 AND %I = $2)',
                       v_target::regclass, v_org_col)
           INTO v_ok USING NEW.owner_id, NEW.organization_id;
    END IF;
    IF NOT v_ok THEN
        RAISE EXCEPTION 'media %: owner %:% not found or organization mismatch',
            NEW.uuid, NEW.owner_type, NEW.owner_id USING ERRCODE = '23503';
    END IF;
    RETURN NULL;
END; $$;

-- §2 Registry (GLOBAL; no tenant_id)
CREATE TABLE media.owner_types (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid uuid NOT NULL DEFAULT uuidv7(),
    code varchar(255) NOT NULL,
    target_table text NOT NULL,
    org_column text,
    description text,
    created_by_id bigint, created_by_name text,
    updated_by_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by_id bigint,
    CONSTRAINT uq_owner_types_uuid UNIQUE (uuid),
    CONSTRAINT uq_owner_types_code UNIQUE (code),
    CONSTRAINT ck_owner_types_target_table
        CHECK (target_table ~ '^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$'),
    CONSTRAINT ck_owner_types_org_column CHECK (org_column ~ '^[a-z_][a-z0-9_]*$')
);

-- §3 Canonical media
CREATE TABLE media.media (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL,                          -- [DEV]
    organization_id bigint NOT NULL,
    owner_type varchar(255),
    owner_id bigint,
    collection_name varchar(255) NOT NULL,
    name varchar(255) NOT NULL,
    file_name varchar(255) NOT NULL,
    mime_type varchar(255),
    disk varchar(255) NOT NULL,
    conversions_disk varchar(255),
    storage_path text,
    size bigint NOT NULL,
    manipulations jsonb NOT NULL DEFAULT '{}'::jsonb,
    custom_properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    generated_conversions jsonb NOT NULL DEFAULT '{}'::jsonb,
    responsive_images jsonb NOT NULL DEFAULT '{}'::jsonb,
    order_column integer DEFAULT 0,
    status text DEFAULT 'ready',
    status_reason text,
    is_default boolean DEFAULT false,
    expires_at timestamptz,
    purged_at timestamptz,
    content_hash bytea,
    width integer, height integer, orientation integer DEFAULT 1,
    focal_point_x numeric(5,2), focal_point_y numeric(5,2),
    blurhash text, dominant_color char(7),
    aspect_ratio numeric(8,4) GENERATED ALWAYS AS (
        CASE WHEN height > 0 AND width > 0
             THEN round(width::numeric / height::numeric, 4) ELSE NULL END) STORED,
    page_count integer, duration_seconds numeric(10,2),
    virus_scan_status text DEFAULT 'pending', virus_scanned_at timestamptz,
    app_version text, data_class text,
    row_version integer NOT NULL DEFAULT 1,
    app_metadata jsonb,
    created_by_id bigint, created_by_name text,
    updated_by_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by_id bigint,
    CONSTRAINT uq_media_uuid UNIQUE (uuid),
    CONSTRAINT fk_media_owner_type FOREIGN KEY (owner_type) REFERENCES media.owner_types(code),
    CONSTRAINT fk_media_organization_id FOREIGN KEY (organization_id)
        REFERENCES org_management.organizations(id),
    CONSTRAINT fk_media_tenant_org FOREIGN KEY (tenant_id, organization_id)   -- [DEV]
        REFERENCES org_management.organizations(tenant_id, id),
    CONSTRAINT ck_media_owner_pair CHECK (num_nonnulls(owner_type, owner_id) <> 1),
    CONSTRAINT ck_media_unowned_expires
        CHECK (num_nonnulls(owner_type, owner_id) = 2 OR expires_at IS NOT NULL),
    CONSTRAINT ck_media_size_nonneg CHECK (size >= 0),
    CONSTRAINT ck_media_file_name_no_path
        CHECK (position('/' in file_name) = 0 AND position(E'\\' in file_name) = 0),
    CONSTRAINT ck_media_mime_type_shape
        CHECK (mime_type ~ '^[^/[:space:]]+/[^/[:space:]]+$'),
    CONSTRAINT ck_media_status
        CHECK (status IN ('pending','processing','ready','failed','quarantined')),
    CONSTRAINT ck_media_virus_scan_status
        CHECK (virus_scan_status IN ('pending','clean','infected','skipped')),
    CONSTRAINT ck_media_data_class CHECK (data_class IN ('P0','P1','P2','P3')),
    CONSTRAINT ck_media_content_hash_len
        CHECK (content_hash IS NULL OR octet_length(content_hash) = 32),
    CONSTRAINT ck_media_row_version_pos CHECK (row_version > 0),
    CONSTRAINT ck_media_focal_point_x CHECK (focal_point_x BETWEEN 0 AND 100),
    CONSTRAINT ck_media_focal_point_y CHECK (focal_point_y BETWEEN 0 AND 100),
    CONSTRAINT ck_media_dominant_color CHECK (dominant_color ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT ck_media_page_count_pos CHECK (page_count > 0),
    CONSTRAINT ck_media_duration_nonneg CHECK (duration_seconds >= 0),
    CONSTRAINT ck_media_json_shapes CHECK (
        jsonb_typeof(manipulations) IN ('object','array')
        AND jsonb_typeof(custom_properties) IN ('object','array')
        AND jsonb_typeof(generated_conversions) IN ('object','array')
        AND jsonb_typeof(responsive_images) IN ('object','array')),
    CONSTRAINT ck_media_app_metadata CHECK (
        app_metadata IS NULL OR (jsonb_typeof(app_metadata) = 'object'
        AND octet_length(app_metadata::text) <= 32768)),
    CONSTRAINT ck_media_purged_needs_deleted
        CHECK (purged_at IS NULL OR deleted_at IS NOT NULL)
);
-- [DEV] no media.bump_row_version trigger — SQLAlchemy RowVersionMixin owns it.

CREATE CONSTRAINT TRIGGER trg_media_owner_integrity
    AFTER INSERT OR UPDATE OF owner_type, owner_id, organization_id, deleted_at ON media.media
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    WHEN (NEW.owner_id IS NOT NULL)
    EXECUTE FUNCTION media.check_owner_integrity();

-- §4 Variants
CREATE TABLE media.media_variants (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid uuid NOT NULL DEFAULT uuidv7(),
    media_id bigint NOT NULL REFERENCES media.media(id) ON DELETE CASCADE,
    tenant_id bigint NOT NULL,                          -- [DEV]
    organization_id bigint NOT NULL,
    variant_name varchar(100) NOT NULL,
    file_name varchar(255) NOT NULL,
    storage_path text, disk varchar(255) NOT NULL,
    mime_type varchar(255) NOT NULL, size bigint NOT NULL,
    width integer, height integer, content_hash bytea,
    status text DEFAULT 'ready', status_reason text,
    created_by_id bigint, created_by_name text, updated_by_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by_id bigint,
    CONSTRAINT uq_media_variants_uuid UNIQUE (uuid),
    CONSTRAINT uq_media_variants_media_variant UNIQUE (media_id, variant_name),
    CONSTRAINT fk_media_variants_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations(tenant_id, id),
    CONSTRAINT ck_media_variants_size_nonneg CHECK (size >= 0),
    CONSTRAINT ck_media_variants_status CHECK (status IN ('pending','processing','ready','failed')),
    CONSTRAINT ck_media_variants_content_hash_len
        CHECK (content_hash IS NULL OR octet_length(content_hash) = 32)
);

-- §5 Integration edges (L3) — tenant-scoped [DEV]
CREATE TABLE media.media_external_identities (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid uuid NOT NULL DEFAULT uuidv7(),
    media_id bigint NOT NULL REFERENCES media.media(id) ON DELETE CASCADE,
    tenant_id bigint NOT NULL,
    connection_id bigint NOT NULL REFERENCES integration.connections(id),
    external_object text NOT NULL, external_id text NOT NULL, external_key jsonb,
    external_created_at timestamptz, external_updated_at timestamptz, external_deleted_at timestamptz,
    sync_status text DEFAULT 'synced', sync_error text, snapshot jsonb,
    created_by_id bigint, created_by_name text, updated_by_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by_id bigint,
    CONSTRAINT uq_media_external_identities_uuid UNIQUE (uuid),
    CONSTRAINT uq_media_ext_id_connection UNIQUE (connection_id, external_object, external_id),
    CONSTRAINT uq_media_ext_id_media_connection UNIQUE (media_id, connection_id),
    CONSTRAINT ck_media_ext_id_sync_status
        CHECK (sync_status IN ('pending','synced','failed','quarantined'))
);

-- §6 Indexes
CREATE INDEX ix_media_owner_lookup ON media.media
    (organization_id, owner_type, owner_id, collection_name, order_column)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_media_owner_collection_default ON media.media
    (organization_id, owner_type, owner_id, collection_name)
    WHERE is_default IS TRUE AND deleted_at IS NULL;
CREATE INDEX ix_media_org_created ON media.media (organization_id, created_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_media_content_hash ON media.media (organization_id, content_hash)
    WHERE content_hash IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_media_expires_at ON media.media (expires_at)
    WHERE expires_at IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_media_status_active ON media.media (created_at)
    WHERE status IN ('pending','processing') AND deleted_at IS NULL;
CREATE INDEX ix_media_purge_pending ON media.media (deleted_at)
    WHERE deleted_at IS NOT NULL AND purged_at IS NULL;
CREATE INDEX ix_media_trgm_name ON media.media USING gin (name gin_trgm_ops)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_media_variants_media_id ON media.media_variants (media_id)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_media_variants_status ON media.media_variants (created_at)
    WHERE status IN ('pending','processing') AND deleted_at IS NULL;
CREATE INDEX ix_media_ext_id_media_id ON media.media_external_identities (media_id);

-- §8 Seed (target tables per this repo)
INSERT INTO media.owner_types (code, target_table, org_column, description) VALUES
    ('organization', 'org_management.organizations', 'id',              'Organization branding assets (logo, marks)'),
    ('user',         'public.users',                 'organization_id', 'User avatar / KYC documents'),
    ('brand',        'core.brands',                  'organization_id', 'Brand logo assets')
ON CONFLICT (code) DO NOTHING;
```

---

## Appendix B — Settings reference

| Setting | Default | Notes |
|---------|---------|-------|
| `MEDIA_STORAGE_DRIVER` | `local` | `local` \| `s3`. Set `s3` to use Garage. |
| `MEDIA_LOCAL_BASE_PATH` | `/app/media/library` | Bind/volume-backed. |
| `MEDIA_S3_ENDPOINT_URL` | `` | `http://garage:3900`. |
| `MEDIA_S3_BUCKET` | `media` | Created by `--default-bucket`. |
| `MEDIA_S3_REGION` | `garage` | Must match Garage `s3_region`. |
| `MEDIA_S3_USE_PATH_STYLE` | `true` | Garage requirement. |
| `MEDIA_S3_ACCESS_KEY_ID/SECRET` | `` | The Garage default key. |
| `MEDIA_S3_PUBLIC_BASE_URL` | `` | CDN/s3_web base for public assets. |
| `MEDIA_MAX_UPLOAD_BYTES` | 25 MiB | Per-file cap. |
| `MEDIA_IMAGE_MAX_PIXELS` | 40 MP | Bomb guard. |
| `MEDIA_BLURHASH_ENABLED` | `true` | Placeholders. |
| `MEDIA_DEDUPE_ENABLED` | `true` | Exact sha256 reuse per org. |
| `MEDIA_FINGERPRINTS_ENABLED` | `false` | `imagehash`, Phase 3. |
| `MEDIA_RESPONSIVE_WIDTHS` | `320,640,960,1280,1920` | Ladder. |
| `MEDIA_VIRUS_SCAN_ENABLED` | `false` | ClamAV hook. |
| `MEDIA_QUEUE` | `media` | Celery queue. |

---

## Appendix C — Open questions

1. **AVIF by default?** It costs CPU and some clients still lack support.
   Recommendation: generate WebP always; AVIF only for hero/gallery sets or
   behind a flag.
2. **Public bucket vs proxy for logos?** If public, a dedicated read-only Garage
   key + Traefik `s3_web` route is needed. Until then, proxy everything.
3. **Per-org storage quotas?** Not in the approved schema; add later if needed.
4. **Video/PDF thumbnails?** `page_count`/`duration_seconds` exist; rendering
   (ffmpeg/pdftoppm) is out of scope for v1.
5. **ImageHash adoption trigger?** Only if "find similar"/dedupe review becomes a
   product requirement.
```