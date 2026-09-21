# Adapter — organizations

> **Since 2026‑09‑20** a Zoho organization is a **root node of the tenant's organization
> tree** (`org_management.organizations`, docs/tenancy/README.md). The v1 `zoho_organizations`
> table and its outbox push are retired. The sync is INBOUND. Zoho owns the profile fields,
> `legal_name` follows the Zoho name, and code/type/parent/status are ours. The HTTP API is
> `/api/organizations`. The rows below describe the Zoho side, still valid.

**Status:** ✅ live (pull + outbox push) · **Code:** `app/modules/organizations/`
(adapter in `zoho/spec.py`, `zoho/fields.py`) · **Tests:** `tests/zoho_sync/test_engine.py`,
`test_organizations_module.py`, `tests/zoho_core/test_masters_e2e.py` ·
**Source:** `docs/zoho-docs-md/organizations.md`

| Aspect | Value | Why |
|---|---|---|
| Endpoint | `GET /organizations` → `GET /organizations/{id}` | the list is a thin index |
| Pagination | **none** (`paginated=False`) | one response, no `page_context` (E29) **[verify]** |
| Detail call | inline, 0.2 s apart | N is tiny (orgs the token can see) |
| Strategy | `full`, every 360 min | no `last_modified_time` filter |
| Direction | bidirectional | local create/update/delete → v1 outbox (`sync_status`) |
| Mixins | `ZohoEntityMixin` (legacy alias = Identity + Mirror + `sync_status` family) | built before the mixin split |
| HTTP | `/api/zoho/organizations` — list, get, create/update/delete (outbox), `POST /sync` | unchanged by the Phase 5 move |

Field map: `zoho/fields.py` (29 mappings, including the `address.*` flattening;
server-managed attributes are `outbound=False`).

Open: move pushes to outbox v2 (Phase 8); `/organizations/address` and
`/organizations/user` are not mirrored.
