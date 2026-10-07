# Privacy and notification settings

**Status:** ✅ built (2026-10-06) · **Migration:** `d81f4b6e2c90` (data normalization) · **Code:**
`app/modules/users/schema.py` (`UserSettings`), `visibility.py`, `service.py` · **Tests:**
`tests/test_sessions_consent_privacy.py`, `tests/test_profile_endpoints.py`

Stored in `users.application_settings`; `GET/PATCH /api/me/settings` (PATCH merges what you send).

## Values

| Setting | Values | Default |
|---|---|---|
| `privacy.profile_visibility` | `everyone` · `team` · `managers` · `private` | `everyone` |
| `privacy.contact_visibility` | `everyone` · `team` · `hidden` | `hidden` |
| `notifications.{email,push,sms,slack,in_app}` | bool | email, push, in_app on |
| `appearance.theme` | `light` · `dark` · `system` | `system` |
| `security.two_factor_enabled` | read-only (2FA enrolment not built) | — |

`GET /api/me/settings/options` returns every value with its label and each notification channel's
availability (push, SMS and Slack delivery are not built yet — the preference is stored).

**Legacy values** are accepted and converted, and were migrated: `public`/`organization` → `everyone`,
`contacts` → `team`; `show_email` + `show_phone` both true → `contact_visibility: everyone`, else `hidden`.
`show_email`/`show_phone` are still returned (derived, deprecated).

## Who sees what (`users/visibility.py`)

Audiences of a viewer for a person: **tenant** (every signed-in user of the same tenant), **team** (an
approved, active team in common), **manager** (in the person's reporting line at any depth, or leads one of
their teams), **self**, **admin** (holds `users.user:read`).

| Setting | Visible to |
|---|---|
| profile / contact `everyone` | tenant |
| `team` | team ∪ manager |
| `managers` | manager |
| `private` / `hidden` | nobody else |

Self and admin always see everything. In the directory (`GET /api/users`, `GET /api/users/{id}`), a hidden
profile shows only `id` + `name` with `restricted: true`; profile details are `username`, `avatar_urls`,
`designation`, `department`; contact is `email`, `phone`. Audiences are computed for a whole page in ≤ 2 queries.
