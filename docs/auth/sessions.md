# Sign-in sessions

**Status:** ✅ built (2026-10-06) · **Migration:** `d81f4b6e2c90` (schema `auth`) · **Code:**
`app/modules/users/sessions.py`, `session_model.py`, `deps.py` · **Tests:** `tests/test_sessions_consent_privacy.py`

## Why

Before this, first-party JWTs were stateless: signing in on device B left device A working, and even
`POST /api/auth/logout` left the token valid until it expired (24 h access, 30 d refresh).

## How it works

* Every password or OTP sign-in creates an `auth.user_sessions` row (client type `field_app` / `web` /
  `service`, installation id, device label, IP, `expires_at` = `SESSION_MAX_DAYS`). Tokens carry its uuid
  as `sid` (+ a `jti`).
* **Every request** checks the session (`deps._authenticate` → `sessions.check`). State is cached in Redis
  DB 0 under `auth:session:<sid>` for `SESSION_CACHE_TTL_SECONDS`; revocation writes the cache first.
  `last_seen_at` is touched at most once a minute.
* Revoked → `401 {code: "session_revoked", data: {reason, revoked_at, drain_until}}`. Reasons: `logout`,
  `logout_all`, `signed_in_elsewhere`, `refresh_reuse`, `admin`, `password_changed`.
* **Refresh rotates** the refresh jti; presenting the previous one again revokes the session — except
  within 30 s of the rotation (two refreshes racing from one app), when it rotates again.
* Password change revokes every other session; password reset revokes all.
* Tokens without a `sid` (issued before deploy, `dev-token`) keep working until `AUTH_REQUIRE_SESSION=true`.

## The single-session rule

Only `field_app` sessions are limited. The rule is the policy setting `session.field`
([fieldops/policy-layers.md](../fieldops/policy-layers.md)), settable per organization, role or user:

| Field | Meaning |
|---|---|
| `field_max_sessions` | live field sessions per user; `0` = unlimited |
| `field_on_new_login` | `revoke_previous` (the oldest are revoked) or `refuse` (`409 active_session_exists`) |
| `field_drain_grant_hours` | a displaced device may still call `POST /api/me/location-pings` and `/me/device-events` this long, for fixes recorded before it was signed out |

With no layer setting it, `FIELD_MAX_SESSIONS` applies (default `0`). THPL's seed sets 1 for `member`.
`users` never imports `fieldops`: field operations registers the rule provider
(`fieldops/service/session_rules.py`).

## API

| Route | |
|---|---|
| `POST /api/auth/login`, `/login-otp/verify` | `client_type`, `installation_id` (optional; android/ios `device_type` ⇒ `field_app`); response adds `session_uuid`, `displaced_sessions` |
| `POST /api/auth/refresh` | rotated pair |
| `POST /api/auth/logout` · `/logout-all` | |
| `GET /api/auth/sessions` · `DELETE /api/auth/sessions/{uuid}` | my devices (`current` marks this one) |
| `GET /api/users/{id}/sessions` · `DELETE /api/users/{id}/sessions[/{uuid}]` | admin (`users.session:read/delete`) |

## Settings

`SESSION_MAX_DAYS` (30), `FIELD_MAX_SESSIONS` (0), `MAX_WEB_SESSIONS` (0), `AUTH_REQUIRE_SESSION` (false — turn
on once pre-deploy tokens have expired, ≤ 24 h), `SESSION_CACHE_TTL_SECONDS` (60). All are passed through
`deployment/docker-compose.yml`. Authentik (RS256) tokens are unaffected — Authentik owns those sessions.
