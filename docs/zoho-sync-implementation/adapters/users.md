# Adapter — Zoho users (O1 master)

**Status:** ✅ live (pull) · **Code:** `app/modules/zoho_users/` (sync module name `users`) ·
**Migration:** `e6e42c16c52e` (`zoho_users`) · **Tests:** `tests/zoho_core/test_masters_e2e.py`
· **Source:** `docs/zoho-docs-md/users.md`

These are the people with a login in the **Zoho organization** (salespersons,
approvers, location users), not our application accounts (`app.modules.users`).
Hence the package name `zoho_users`.

| Aspect | Value | Why |
|---|---|---|
| Endpoint | `GET /users?filter_by=Status.All` (Books) | old documents reference inactive/invited users too |
| Pagination | yes (documented `page_context`) | — |
| Detail call | none (`GET /users/{id}` exists but adds nothing we mirror) | saves N calls |
| Id attribute | `user_id` | — |
| Strategy | `full`, daily; no weekly lane | no `last_modified_time` |
| Direction | inbound only | user management stays in Zoho |
| Personal data | `email` is masked in sync-event diffs (last 4 chars) | [`sync-events.md`](../sync-events.md) §2.1 |

| Column | Zoho attribute |
|---|---|
| `name`, `email`, `user_role`, `role_id`, `status`, `user_type` | same |
| `is_current_user` | same — relative to the connected OAuth identity |
| `is_customer_segmented`, `is_vendor_segmented` | same |
| `photo_url`, `cost_rate` | same |
| `zoho_created_time` | `created_time` |

HTTP (read-only): `GET /api/zoho/users?status=active` ·
`GET /api/zoho/users/{ref}` — local id, Zoho id or email (case-insensitive).

Open: linking a Zoho user to a local account (by email) is an identity
decision for the users module, not a mirror concern; roles (`/roles`) are not
in the vendored docs.
