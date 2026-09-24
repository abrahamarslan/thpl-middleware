"""Users & authentication module.

Three routers (`users/api.py`):
  /api/auth/*   register, login, login-otp, refresh, me, change-password,
                password-policy, forgot-password, reset-password, dev-token
  /api/users/*  admin CRUD (list/get/create/update/soft-delete/restore) and
                a user's last known position
  /api/me/*     the authenticated user's own profile, organization and location

A user belongs to ONE organization (`organization_id` NOT NULL) and holds a role
OF THAT ORGANIZATION. Creation paths therefore resolve an organization before
the row is flushed — `service.resolve_user_organization`; a path that skips it
fails with a NOT NULL violation.

Location is deliberately NOT on the user row: addresses live in the platform-wide
address book (`geo.place_links`, reached via `/api/addresses`) and position lives
in `user_live_locations` / `user_location_pings`. `users.primary_place_id` and
`users.country_code` are caches of those.

Auth is split into focused feature modules: `password_policy` (complexity),
`security` (bcrypt + one-time-code HMAC), `identifiers` (email|username|phone),
`password_reset` and `login_otp` (one-time-code flows), `auth_emails` (typed
email contexts), `tokens` (token-pair issuance), and `authentik_sync` (outbound
IdP mirror). See docs/modules/auth-module-documentation.md.
"""
