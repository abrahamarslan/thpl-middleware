# Audit Activity, Files & Favorites

Three modules plus the shared model mixins, all on the standard FBA 5-layer
pattern (model → schema → crud → service → api).

---

## 0. Two kinds of "logging" — don't confuse them

| | Operational logging | **Activity / audit log** (this) |
|---|---|---|
| Question | "What is the process doing?" | "Who did what to which record?" |
| Where | structlog → stdout → Loki | Postgres `activity_logs` table |
| Lifetime | retention window (30 d) | long-term, compliance |
| Audience | engineers in Grafana | admins/auditors via the API |
| Code | `app/core/logging/` | `app/modules/activity/` |

They are linked: every audit row stores the `request_id`, so from an audit
entry you can pivot to the full operational logs/trace of that same request.

---

## 1. Mixins vs Utilities — the decision

The request was to add the activity model "and its Mixins / Utilities (decide
which is better)." The answer is **both, for different jobs**:

- **Mixins** are the right tool for cross-cutting **columns** — every table
  wants the same `created_at/updated_at`, `deleted_at`, `tenant_id`,
  `created_by/...`. These live in [`app/database/mixins.py`](../apps/core-platform/backend/app/database/mixins.py):
  `IntPKMixin`, `TimestampMixin`, `SoftDeleteMixin`, `TenantMixin`,
  `AuditUserMixin`.

  ```python
  class FileEntity(IntPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
      ...
  ```

- **A utility/service** is the right tool for the **behaviour** of recording an
  audit entry — *not* a mixin and *not* a SQLAlchemy event listener. Why:
  - **Explicit & testable** — you see exactly where each entry is produced.
  - **Transaction-aware** — it writes through the caller's `AsyncSession`, so
    the audit row commits atomically with the business change.
  - **No hidden side effects** — event listeners fire inside arbitrary flush
    cycles (including ones you never meant to audit), and writing to the
    session from within a flush is fragile under async SQLAlchemy.

  So recording lives in [`app/modules/activity/recorder.py`](../apps/core-platform/backend/app/modules/activity/recorder.py) as `record_activity(...)`.

> Rule of thumb: **mixins for shape, utilities for behaviour.**

---

## 2. Recording activity

```python
from app.modules.activity.recorder import record_activity, model_changes

# Simple event
await record_activity(
    db, action="file.created", actor_id=user.id, actor_label=user.email,
    subject_type="file", subject_id=file.file_id,
    description=f"Uploaded {file.file_name}",
)

# With a before/after diff (call model_changes BEFORE commit)
changes = model_changes(user, exclude={"updated_at"})   # secrets auto-masked
await record_activity(db, action="user.updated", actor_id=editor.id,
                      subject_type="user", subject_id=user.id, changes=changes)
```

- `request_id` and `ip_address` are pulled automatically from the request
  context (no plumbing).
- **Best-effort by default**: the insert is wrapped in a SAVEPOINT, so an audit
  failure never breaks the business operation (it's logged operationally
  instead). For compliance-critical actions that must not proceed without an
  audit row, pass `best_effort=False`.
- Already integrated in the files and favorites services
  (`file.created/status_updated/deleted`, `favorite.added/removed`).

**Querying** (admin/audit UI): `GET /api/activity` with filters
(`action`, `actor_id`, `subject_type`, `subject_id`, `status`, `since`,
`until`, pagination) and `GET /api/activity/{activity_id}`.

---

## 3. Files module (`/api/files`)

Metadata records for documents whose bytes live in S3; OCR-aware.

| Endpoint | Purpose |
|---|---|
| `POST /api/files` | Create a file record (after the upload to S3). |
| `GET /api/files` | Filtered, paginated list (`file_type`, `processing_status`, `fileable_*`, …). |
| `GET /api/files/slim` | Lightweight list for dropdowns. |
| `GET /api/files/{file_id}` | Full detail incl. computed `*_formatted` fields. |
| `PATCH /api/files/{file_id}/status` | Advance processing/scan lifecycle. |
| `DELETE /api/files/{file_id}` | Soft delete. |

`FileOut` exposes formatted helpers computed on the fly:
`file_size_formatted` ("1.5 MB"), `scanned_amount_formatted` ("$1,234.50"),
`created_at_formatted`, `scanned_receipt_date_formatted`.

Polymorphic attachment: set `fileable_type` + `fileable_id` to bind a file to
any record (e.g. an invoice, a user).

---

## 4. Favorites module (`/api/favorites`)

Per-user, polymorphic "pin any entity". One row per (user, target), enforced by
a unique constraint; unfavoriting hard-deletes.

| Endpoint | Purpose |
|---|---|
| `GET /api/favorites` | The current user's favorites (filter by `favoritable_type`). |
| `POST /api/favorites` | Add (409 if already favorited). |
| `POST /api/favorites/toggle` | Idempotent on/off — returns `{favorited, favorite}`. |
| `DELETE /api/favorites/{favorite_id}` | Remove. |

Favorite anything by `favoritable_type` + `favoritable_id`
(e.g. `"file"`, `"zoho_item"`, `"user"`) — no schema change per type.

---

## 5. Migration

The models are imported in `alembic/env.py`, so:

```bash
./manage.sh makemig "add activity_logs, files, favorites"
./manage.sh migrate
```

`activity_logs` is append-only and indexed on subject, actor, action,
created_at, tenant and request_id. At very high volume, consider time-based
partitioning or shipping older rows to ClickHouse (same Debezium path the Zoho
mirror tables use).
