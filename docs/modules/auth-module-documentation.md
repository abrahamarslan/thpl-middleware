# Auth Module — `app/modules/users/` (authentication surface)

Authentication lives inside the **users** module (the codebase's FBA
`api → schema → service → crud → model` split); `users/api.py` exposes two
routers: `auth_router` at `/api/auth/*` and `users_router` at `/api/users/*`.
This document covers the whole auth surface: password + passwordless-OTP login,
registration, password policy, password reset (code and link), request-audit
context (IP/device/GeoIP), and the transactional emails they trigger.

> **One-line doctrine:** in, per endpoint, a thin API layer; every security
> decision (hashing, TTLs, attempt caps, throttles, uniform responses) lives in
> a dedicated feature module; delivery goes through the reusable email layer.

---

## 1. Module map

| File | Responsibility |
|---|---|
| `api.py` | `auth_router` (`/api/auth/*`) + `users_router` (`/api/users/*`). Thin handlers only. |
| `schema.py` | Transport schemas. Password fields use the policy `PasswordStr`; auth-failure responses use the standard envelope. |
| `service.py` | Register, password login (lockout), token refresh, change password, user CRUD, Authentik JIT provisioning. Delegates reset to `password_reset`. |
| `tokens.py` | `issue_token_pair(user)` — the single place access+refresh tokens are minted (shared by password and OTP login). |
| `identifiers.py` | Resolves an auth `identifier` (email \| username \| phone) to a user, shape-driven with a username fallback. |
| `password_policy.py` | Configurable complexity rules; `PasswordStr` Pydantic type + `validate_password()`; `get_password_policy()`. |
| `security.py` | bcrypt password hashing + keyed-HMAC one-time-code hashing/verification + numeric code generation. |
| `password_reset.py` | Password-reset feature: request (code/link) + reset. |
| `login_otp.py` | Passwordless email-OTP login: request + verify. |
| `auth_emails.py` | Auth transactional emails: typed contexts + senders; registers the auth templates. |
| `templates/` | Auth email HTML/text templates (`_base.en.html` + one file per email). |
| `deps.py` | `CurrentUser` dependency (Authentik RS256 **or** first-party HS256). |
| `model.py` | `User`, `PasswordResetToken`, `LoginOtpToken`. |
| `crud.py` | Data access (lookups incl. phone, reset/OTP challenge storage). |
| `authentik_sync.py` | Outbound app→Authentik mirror (see `docs/AUTHENTIK_SYNC.md`). |

Shared infrastructure used by auth: `app/common/client_info.py` (IP/device/geo
audit context), `app/common/geoip.py` (MaxMind lookups), and
`app/modules/emails/` (provider adapter, template registry, delivery).

---

## 2. Endpoint reference

All bodies use the success envelope `{code, msg, data, request_id}` and all
errors use the same envelope with an HTTP status. Errors map to the domain
hierarchy: `AuthError` → 401 `unauthorized`, `ForbiddenError` → 403
`forbidden`, `ConflictError` → 409 `conflict`, `NotFoundError` → 404
`not_found`, `PasswordPolicyError` → 422 `password_policy`, request-validation →
422 `validation_error`.

| Method | Path | Auth | Body | Success |
|---|---|---|---|---|
| POST | `/api/auth/register` | public | `name, email, password, username?, phone?` | `201 UserOut` (also sends **welcome** email) |
| POST | `/api/auth/login` | public | `email_or_username, password, device_id?, device_type?` | `TokenPair` |
| POST | `/api/auth/login-otp/request` | public | `identifier` | `{sent, expires_at, debug_code?}` |
| POST | `/api/auth/login-otp/verify` | public | `identifier, code, device_id?, device_type?` | `TokenPair` |
| POST | `/api/auth/refresh` | public | `refresh_token` | `TokenPair` |
| GET | `/api/auth/me` | JWT | — | `UserOut` |
| POST | `/api/auth/change-password` | JWT | `current_password, new_password` | `{changed: true}` (also sends **password changed** email) |
| GET | `/api/auth/password-policy` | public | — | `PasswordPolicyOut` |
| POST | `/api/auth/forgot-password` | public | `identifier, reset_type? ("code"\|"link")` | `{sent, expires_at, debug_code?, debug_token?}` |
| POST | `/api/auth/reset-password` | public | `identifier, token_or_code, new_password` | `{reset: true}` (also sends **password changed** email) |
| POST | `/api/auth/dev-token` | DEBUG only | — | `{access_token}` (hidden from schema) |

`TokenPair = {access_token, refresh_token, token_type:"bearer", expires_in}`.

User administration (JWT-protected) lives on the same module: `GET/POST
/api/users`, `GET/PUT/DELETE /api/users/{id}`, `POST /api/users/{id}/restore`.

**Identifier vs `email_or_username`.** Reset and OTP endpoints take a single
`identifier` (email, username **or** phone). Login keeps the historical
`email_or_username` field name, but it too resolves through the same identifier
logic — so phone login works without an API break.

---

## 3. Flows

### 3.1 Registration
`POST /api/auth/register` → `service.register`:
1. Reject duplicate email/username (`ConflictError`).
2. Validate the password against the configured policy.
3. Hash with bcrypt, create the `User` (`last_password_change_at = now`).
4. Best-effort mirror into Authentik (retry enqueued on failure).
5. Best-effort **welcome** email (never fails registration).

### 3.2 Password login
`service.login`: resolve identifier → lockout check → verify bcrypt →
on failure increment `failed_login_attempts` (lock after `AUTH_MAX_FAILED_LOGINS`
for `AUTH_LOCKOUT_MINUTES`) → on success clear counters, stamp `last_login`,
optionally record device, return `issue_token_pair(user)`.

### 3.3 Passwordless OTP login
1. `POST /login-otp/request` → `login_otp.request_login_otp`: resolve
   identifier (uniform `{sent:true}` if unknown/deactivated), enforce cooldown +
   hourly cap, generate a numeric code (`LOGIN_OTP_CODE_LENGTH`, default 6),
   store only its HMAC with TTL/attempt-cap, send the **login OTP** email.
2. `POST /login-otp/verify` → `login_otp.verify_login_otp`: validate code
   (attempt-capped, single-use), then clear any password lockout, stamp the
   session and return a `TokenPair`.

### 3.4 Password reset — code (default)
`POST /forgot-password {"identifier", "reset_type":"code"}` →
`password_reset.request_password_reset`:
1. Resolve identifier (uniform response if unknown/deactivated).
2. Cooldown + hourly-cap throttle.
3. Generate a configurable numeric code (**4 by default**), store only its
   HMAC with TTL (`PASSWORD_RESET_CODE_TTL_MINUTES`, default 10) and attempt cap
   (default 3), keep the high-entropy link `token` too.
4. Send the **password reset code** email with the request-audit block.

`POST /reset-password {"identifier", "token_or_code", "new_password"}`:
verify code (or link token) → apply policy to the new password → hash/store →
clear lockout → delete the challenge (single use) → mirror to Authentik →
best-effort **password changed** email.

### 3.5 Password reset — link
Same request path with `reset_type:"link"`; the email carries
`{FRONTEND_URL}/reset-password?identifier=<email>&token=<token>`. The web form
submits `identifier` + `token` to `/reset-password`. Mobile-first clients use
the code flow instead.

### 3.6 Change password
`POST /change-password` (`CurrentUser`): verify current password → apply policy
→ hash/store → mirror to Authentik → best-effort **password changed** email.

### 3.7 Refresh
`POST /refresh`: decode the refresh token (type-checked) → user must still be
active → new `TokenPair`.

---

## 4. Identifier resolution — `identifiers.py`

`resolve_user_by_identifier(db, identifier)`:
- contains `@` → try email;
- phone-shaped (`+?digits`, ≥7 digits after stripping) → try phone/contact
  (raw and normalized);
- always falls back to username.

It never reveals which column matched. Soft-deleted users are excluded
(`include_deleted=False`).

---

## 5. Password policy — `password_policy.py`

Configuration, not code. One rule engine drives **register, admin-create,
change-password and reset**:

| Setting | Default | Meaning |
|---|---|---|
| `PASSWORD_MIN_LENGTH` | 8 | Minimum length |
| `PASSWORD_MAX_LENGTH` | 128 | Maximum length |
| `PASSWORD_REQUIRE_UPPERCASE` | true | Needs A–Z |
| `PASSWORD_REQUIRE_LOWERCASE` | true | Needs a–z |
| `PASSWORD_REQUIRE_DIGIT` | true | Needs 0–9 |
| `PASSWORD_REQUIRE_SPECIAL` | false | Needs symbol |
| `PASSWORD_SPECIAL_CHARS` | `""` | Explicit symbol set (empty = any non-alphanumeric) |
| `PASSWORD_MIN_UNIQUE_CHARS` | 4 | Distinct characters floor |
| `PASSWORD_DISALLOW_COMMON` | true | Built-in common-password denylist |
| `PASSWORD_DISALLOW_USER_INFO` | true | Must not contain name/email |
| `PASSWORD_BCRYPT_ROUNDS` | 12 | bcrypt cost |

Two entry points: `PasswordStr` (Pydantic type) enforces length/complexity at
the request boundary and surfaces failures as the standard 422 envelope
(`code: password_policy`); `validate_password(..., email=, name=)` adds the
user-specific rules in the service layer. `GET /api/auth/password-policy`
returns the active rules for client-side hints.

---

## 6. One-time code security model

Shared by password reset and login OTP (`PasswordResetToken`,
`LoginOtpToken`; codes hashed by `security.py`):

- **Never plaintext at rest** — keyed HMAC-SHA256
  (`PASSWORD_RESET_HMAC_KEY` or `JWT_SECRET_KEY`), compared with
  `hmac.compare_digest`.
- **Short TTL** — reset 10 min (code) / 60 min (link); login OTP 15 min.
- **Attempt cap** — default 3 (reset) / 5 (OTP); the row is destroyed at the cap.
- **Single use** — deleted on success.
- **Resend throttle** — per-row cooldown (60 s) + hourly cap (5).
- **Uniform responses** — `{sent:true}` regardless of account existence/state;
  401 `"Invalid or expired reset code"` on verify failure.
- **Numeric codes** drawn from `secrets`.

A 4-digit code is only safe *because* of these caps — the TTL is deliberately
short and the attempt limit low. The email body necessarily contains the code;
its short TTL bounds exposure (a possible future enhancement is body redaction).

Login OTP is a **possession factor** and therefore deliberately **does not**
touch the account-wide password failure counter: a password lockout does not
block OTP (recovery), and OTP brute-force cannot lock the user out of OTP —
it is bounded by the per-challenge cap instead.

---

## 7. Request audit context — `app/common/client_info.py` + `geoip.py`

Every auth endpoint takes `ClientInfoDep`, which resolves:
- **IP** — `X-Forwarded-For` first hop → `X-Real-IP` → socket peer (shared with
  the request-logging middleware, so logs and emails agree);
- **device** — a bounded local User-Agent parser (`"Chrome on macOS"`,
  `"Tarrina App on Android"`, `"API client"`);
- **location** — MaxMind GeoLite2 city/country when `GEOIP_ENABLED=true` and a
  `.mmdb` is mounted (private/reserved IPs are never looked up; if the DB is
  missing the lookup is a silent no-op).

The auth emails render this as their audit block (IP, location, device,
timestamp), and the values are bound to structured logs. GeoIP setup:
`deployment/config/geoip/README.md`.

---

## 8. Auth emails — `auth_emails.py` + `templates/`

Built on the reusable email layer (`send_template_email`), with **typed Pydantic
contexts** so a missing/renamed variable fails at the call site.

| Template | Trigger | Key context |
|---|---|---|
| `welcome` | registration | `dashboard_url`, `account_id`, `email` |
| `login_otp` | `/login-otp/request` | `code`, `code_formatted`, `expires_minutes` |
| `password_reset_code` | `/forgot-password` (code) | `code`, `expires_minutes`, `expires_at`, `attempts_allowed`, `email` |
| `password_reset_link` | `/forgot-password` (link) | `reset_url`, `expires_minutes`, `email` |
| `password_changed` | reset + change-password | `email`, audit fields |

All extend `users/templates/_base.en.html` (brand header/footer + logo) and get
brand globals (`company_name`, `support_email`, `company_address`, `site_url`,
`frontend_url`, `year`) injected by the template engine. Adding one email =
one file pair + one `register_template` entry + one sender (see
`docs/modules/email-module-documentation.md` §4.4/§12).

---

## 9. Configuration reference (`app/core/conf.py`)

| Group | Vars |
|---|---|
| JWT | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRATION_HOURS`, `JWT_REFRESH_EXPIRATION_DAYS` |
| Lockout | `AUTH_MAX_FAILED_LOGINS`, `AUTH_LOCKOUT_MINUTES` |
| Policy | all `PASSWORD_*` (see §5) |
| Reset | `PASSWORD_RESET_CODE_LENGTH`, `PASSWORD_RESET_CODE_TTL_MINUTES`, `PASSWORD_RESET_LINK_TTL_MINUTES`, `PASSWORD_RESET_MAX_ATTEMPTS`, `PASSWORD_RESET_RESEND_COOLDOWN_SECONDS`, `PASSWORD_RESET_MAX_PER_HOUR`, `PASSWORD_RESET_HMAC_KEY` |
| OTP | `LOGIN_OTP_CODE_LENGTH`, `LOGIN_OTP_TTL_MINUTES`, `LOGIN_OTP_MAX_ATTEMPTS`, `LOGIN_OTP_RESEND_COOLDOWN_SECONDS`, `LOGIN_OTP_MAX_PER_HOUR` |
| GeoIP | `GEOIP_ENABLED`, `GEOIP_CITY_DB_PATH`, `GEOIP_COUNTRY_DB_PATH` |
| Email | `RESEND_API_KEY`, `RESEND_DEFAULT_FROM`, `RESEND_WEBHOOK_SECRET`, `EMAIL_COMPANY_NAME`, `EMAIL_SUPPORT_EMAIL`, `EMAIL_SITE_URL`, `EMAIL_COMPANY_ADDRESS`, `FRONTEND_URL`, `EMAIL_ENABLED`, `EMAIL_LOG_ONLY` |
| Authentik | `AUTHENTIK_ENABLED`, `AUTHENTIK_*`, `AUTHENTIK_SYNC_ENABLED`, `AUTHENTIK_BASE_URL`, `AUTHENTIK_SERVICE_TOKEN` |

---

## 10. Operations

```bash
./manage.sh migrate            # b7c1f2a9d4e0 (reset hardening) + d2e3f4a5b6c7 (login_otp_tokens)
```

1. Set `JWT_SECRET_KEY` (and optionally a dedicated `PASSWORD_RESET_HMAC_KEY`).
2. Configure Resend + brand values in `deployment/.env`.
3. Optional: mount a GeoLite2 `.mmdb` and set `GEOIP_ENABLED=true`.
4. Non-prod: `EMAIL_LOG_ONLY=true` exercises the flow without a provider key;
   `DEBUG=true` echoes `debug_code`/`debug_token` in reset/OTP responses so you
   need no mailbox.

Onboarding: register → welcome; the client may then use password login or
passwordless OTP. A locked-out user can always recover via `/forgot-password`
or `/login-otp/request`.

---

## 11. Testing

| Test | Layer | Covers |
|---|---|---|
| `tests/test_password_policy.py` | hermetic | policy rules + `PasswordStr`/API 422. |
| `tests/test_auth_emails.py` | hermetic | template rendering, UA parser, `format_utc`, client-info/IP, GeoIP no-op. |
| `tests/test_password_reset.py` | integration (Postgres) | identifier resolution, hashed codes, cooldown, attempt cap, expiry, single-use, confirmation email. |
| `tests/test_login_otp.py` | integration (Postgres) | request/verify, cooldown, attempt cap, expiry, token issuance, single-use. |
| `tests/test_health.py` | hermetic | every auth route is registered. |

Auth-email sends are patched at the `auth_emails` module boundary
(`mocker.patch.object(auth_emails, "send_...", new=mocker.AsyncMock())`).
Integration tests skip cleanly without Postgres.

---

## 12. Security decisions & caveats

- **Uniform responses** everywhere account existence could leak
  (`forgot-password`, `login-otp/request`, `login` invalid credentials).
- **Best-effort notifications** (welcome, password-changed) never roll back a
  completed state change; a mail outage is logged, not surfaced as a 500.
- **OTP vs password lockout are independent** (see §6).
- **Codes are persisted inside the sent email body** (`emails.body_html` /
  `template_data`) — inherent to keeping an outbound-mail log; the short TTL
  bounds exposure. Body redaction for security emails is a possible follow-up.
- **Phone matching is exact** (raw or punctuation-stripped); a stored number
  with unusual formatting may not match. Normalizing phone storage at write
  time is the robust long-term fix.
- **`LoginRequest` keeps `email_or_username`** for API compatibility even
  though it now resolves phone too; only reset/OTP use `identifier` by name.
