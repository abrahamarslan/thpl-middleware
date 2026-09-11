"""Users & authentication module.

Two routers (`users/api.py`):
  /api/auth/*   register, login, login-otp, refresh, me, change-password,
                password-policy, forgot-password, reset-password, dev-token
  /api/users/*  admin CRUD (list/get/create/update/soft-delete/restore)

Auth is split into focused feature modules: `password_policy` (complexity),
`security` (bcrypt + one-time-code HMAC), `identifiers` (email|username|phone),
`password_reset` and `login_otp` (one-time-code flows), `auth_emails` (typed
email contexts), `tokens` (token-pair issuance), and `authentik_sync` (outbound
IdP mirror). See docs/modules/auth-module-documentation.md.
"""
