# Package-by-feature — where a Zoho module lives

**Status:** ✅ live (Phase 5) · **Code:** `app/modules/zoho/sync/registry.py`
(`_ADAPTER_PACKAGES`, `SyncRegistry.validate`), `app/modules/<feature>/zoho/` ·
**Tests:** `tests/zoho_core/test_registry.py`

---

## 1. Layout

The platform (`app/modules/zoho/`) is entity-agnostic. Each business entity is
its own feature package, and its Zoho knowledge sits in a `zoho/` sub-package:

```
app/modules/organizations/            ← the feature (moved from app/modules/zoho/organizations)
├── model.py schema.py crud.py service.py api.py
└── zoho/
    ├── __init__.py   registers SPEC with the sync registry (import side effect)
    ├── spec.py       identity, endpoint, strategy, lane defaults → ZohoModuleDefinition
    └── fields.py     FieldMapping list — the field map is law
app/modules/currencies/  … same shape (O1 master, read-only)
app/modules/taxes/       … same shape (O1 master, read-only)
app/modules/locations/   … same shape (O1 master, read-only)
app/modules/zoho_users/  … same shape (O1 master, read-only; NOT app.modules.users)
```

Files added as modules need them (target architecture §6.1): `children.py`
(line items), `builders.py` (push write contracts), `identity.py`
(X-Unique-Identifier), `hooks.py` (pre/post apply).

| Module | Table | HTTP | Direction | Endpoint | Paginated | Detail call |
|---|---|---|---|---|---|---|
| `organizations` | `zoho_organizations` | `/api/zoho/organizations` (CRUD via outbox) | bidirectional | `/organizations` | **no** (E29) | yes (inline) |
| `currencies` | `zoho_currencies` | `/api/zoho/currencies` (read) | inbound | `/settings/currencies` | **no** — one response, no `page_context` | no |
| `taxes` | `zoho_taxes` | `/api/zoho/taxes` (read) | inbound | `/settings/taxes` | yes | no |
| `locations` | `zoho_locations` | `/api/zoho/locations` (read) | inbound | `/locations` | **no** | no (none exists) |
| `users` | `zoho_users` | `/api/zoho/users` (read) | inbound | `/users?filter_by=Status.All` | yes | no |

Per-module details: [`adapters/`](adapters/) — organizations, currencies,
taxes, locations, users.

HTTP paths stay under `/api/zoho/…` so existing clients are unaffected by the move.

---

## 2. Registration

`sync/registry.py` keeps an **explicit** list, which keeps imports
deterministic. Discovery happens by string, so the platform never imports a
feature module directly:

```python
_ADAPTER_PACKAGES = [
    "app.modules.organizations.zoho",
    "app.modules.currencies.zoho",
    "app.modules.taxes.zoho",
    "app.modules.locations.zoho",
    "app.modules.zoho_users.zoho",
]
```

`autodiscover()` imports each package and then runs **`validate()`**. A bad
spec fails the process at startup (API and workers), not at 03:00 in a worker:

| Check | Failure it prevents |
|---|---|
| every `field_map[].local` is a column of the model | a typo silently drops a field on every sync |
| the model has the apply-gate columns (Identity + Mirror mixins) | the gate cannot fence/hash/tombstone |
| a UNIQUE index on `zoho_id` exists (partial on live rows) | duplicate mirror rows under concurrent lanes |
| nested rules point at registered modules | embedded payloads silently skipped |
| one `(api, endpoint)` per module | two modules fighting over one mirror |

Errors are logged as `zoho.registry.invalid_spec` and raised as `RegistryError`
with every problem listed.

---

## 3. Dependency rules

| Rule | Enforced by |
|---|---|
| `app.modules.zoho.*` never imports a feature, directly or indirectly (only by string in `_ADAPTER_PACKAGES`) | import-linter contract `zoho-platform-entity-agnostic` + `test_platform_code_never_imports_a_feature` |
| features never import the Zoho transport/client: reads come from the mirror, writes go through the outbox | import-linter `features-never-call-zoho-directly` (direct imports; a sync trigger through `app.tasks` is allowed) |
| feature modules are independent of each other: they link by Zoho id, not by import | import-linter `features-independent` |
| only the engine's apply gate writes Zoho-owned mirror columns | review ([`apply-gate.md`](apply-gate.md)) |

The contracts live in `apps/core-platform/backend/.importlinter`. Run
`.venv/bin/lint-imports`, or let `tests/test_import_contracts.py` run them
(there is no CI pipeline yet, so the test suite is the gate). A new feature
module must be added to all three contracts.

---

## 4. Adding a module — checklist

1. `app/modules/<feature>/model.py`: compose
   `IntPKMixin, TimestampMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin, Base`
   (+ `ZohoPushableMixin` / `ZohoApprovalMixin` / `ZohoWarehouseScopedMixin` as
   the module needs), plus
   `Index("uq_<table>_zoho_id_live", "zoho_id", unique=True, postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL"))`.
2. `zoho/fields.py`: field map, from `docs/zoho-docs-md/<entity>.md` only.
3. `zoho/spec.py`: `resolve_module_config(...)`, setting `paginated=False`
   when the documented list response has no `page_context`, and
   `api="inventory"` for Inventory endpoints.
4. `zoho/__init__.py`: `sync_registry.register(SPEC)`.
5. Add the package to `_ADAPTER_PACKAGES`; import the model in `alembic/env.py`.
6. Migration: autogenerate, then **delete unrelated drift** from the file
   (E11) and give it a random revision id (E19).
7. Mount the router in `app/router.py`.
8. Add the table to `tests/conftest.py::_TEST_TABLES` and to Debezium's
   `table.include.list` if it should stream; add the package to the three
   `.importlinter` contracts.
9. Tests: add the documented response to `ZohoWire` in
   `tests/zoho_core/test_masters_e2e.py`, which drives the real transport, so
   envelope and pagination shape are checked too (the `FakeZohoClient` alone
   hid E29).
10. Docs: `docs/zoho-sync-implementation/adapters/<module>.md` + README index row.

---

## 5. What moved (for anyone with old imports)

| Before | After |
|---|---|
| `app.modules.zoho.organizations` (package) | `app.modules.organizations` |
| `from app.modules.zoho.organizations import ORGANIZATIONS_CONFIG` | `from app.modules.organizations.zoho import ORGANIZATIONS_CONFIG` |
| `app.modules.zoho.organizations.model.ZohoOrganization` | `app.modules.organizations.model.ZohoOrganization` |
| registry `_ENTITY_PACKAGES` | `_ADAPTER_PACKAGES` (old name kept as an alias) |
| search registry `model_path` / `schema_path` | updated to the new module paths |

There is no compatibility shim at the old path: a shim inside `app.modules.zoho`
would break the dependency rule it exists to enforce.
