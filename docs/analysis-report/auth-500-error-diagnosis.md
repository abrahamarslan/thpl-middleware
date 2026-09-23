# Auth 500 Error Diagnosis — `app/modules/users` (authentication surface)

**Document Reference:** `docs/analysis-report/auth-500-error-diagnosis.md`
**Date:** September 2026
**Scope:** `apps/core-platform/backend/app/modules/users/**`, `app/common/exception/handlers.py`
**Companion docs:** [`docs/modules/auth-module-documentation.md`](../modules/auth-module-documentation.md),
[`docs/implementation-plan/users-update-implementation-plan.md`](../implementation-plan/users-update-implementation-plan.md)

---

## 1. TL;DR

The 500s are **not** a database, migration, or tenancy failure. The database is
migrated to head (`3b7f0ae91c46`), registration with a valid email returns
`201`, and login returns `200`/`401` as designed.

**Root cause:** the response schemas `UserOut` and `UserMeOut` type the `email`
field as Pydantic `EmailStr`. Pydantic's `email-validator` rejects
*special-use / reserved* domains (`.test`, `.local`, `.invalid`, `.localhost`).
The platform stores exactly such an email for its own synthetic users — the
dev-token user `dev@local.test` (`service.get_or_create_dev_user`) and the
Authentik JIT fallback `{sub}@authentik.local`
(`service.provision_from_authentik`). When any endpoint serialises one of those
users, `UserOut.model_validate(...)` raises `pydantic_core.ValidationError`
**after** the request has succeeded, the global handler turns it into
`500 internal_error`.

In other words: input validation rejects reserved domains at the boundary
(`422`), but **output serialisation re-validates and cannot represent the same
row it just read** (`500`).

---

## 2. Reproduction & evidence

Environment: backend container `backend` on `http://localhost:8000`, Postgres
migrated, `alembic current = 3b7f0ae91c46 (head)`.

| # | Request | Result | Meaning |
|---|---|---|---|
| 1 | `POST /api/auth/register` valid email + strong password | **201** | register path is healthy |
| 2 | `POST /api/auth/register` weak/common password | 422 `password_policy` | expected |
| 3 | `POST /api/auth/register` email `foo@bar.test` | 422 `validation_error` | input `EmailStr` rejects reserved TLD |
| 4 | `POST /api/auth/login` valid identifier | 200 / 401 | login path is healthy |
| 5 | `POST /api/auth/dev-token` | 200 | creates `dev@local.test` user |
| 6 | `GET /api/auth/me` (dev token) | **500** | `UserOut` cannot serialise `dev@local.test` |
| 7 | `GET /api/auth/me/profile` (dev token) | **500** | `UserMeOut` inherits the same `email: EmailStr` |
| 8 | `GET /api/users` (dev token) | **500** | list contains the reserved-domain user |
| 9 | `GET /api/users/2` (dev token) | **500** | user `2` is `dev@local.test` |
| 10 | `GET /api/auth/me` (valid-email user) | 200 | confirms the bug is email-value specific |

### Traceback (request `84ab6d26906f44b5aa19b513c38f135a`, `GET /api/auth/me`)

```
File "/app/app/modules/users/api.py", line 123, in me
    return ResponseModel(data=UserOut.model_validate(user))
File "/opt/venv/lib/python3.12/site-packages/pydantic/main.py", line 732, in model_validate
    return cls.__pydantic_validator__.validate_python(...)
pydantic_core._pydantic_core.ValidationError: 1 validation error for UserOut
email
  value is not a valid email address: The part after the @-sign is a special-use
  or reserved name that cannot be used with email.
  [type=value_error, input_value='dev@local.test', input_type=str]
```

The same traceback repeats for `UserMeOut` and for the list endpoint.

---

## 3. Root cause in code

| Location | Code | Effect |
|---|---|---|
| `app/modules/users/schema.py:166-170` | `class UserOut(...): email: EmailStr` | Output model re-validates the stored email |
| `app/modules/users/schema.py:543-552` | `class UserMeOut(UserOut)` | Inherits `email: EmailStr` |
| `app/modules/users/schema.py:156-163` | `UserCreate.email`, `UserUpdate.email: EmailStr` | Input models — correct place for `EmailStr` |
| `app/modules/users/schema.py:218-220` | `RegisterRequest.email: EmailStr` | Input model — correct place for `EmailStr` |
| `app/modules/users/service.py:401` | `get_or_create_dev_user(db, email="dev@local.test")` | Persists a reserved-domain email |
| `app/modules/users/service.py:380` | `email = claims.get("email") or f"{sub}@authentik.local"` | Persists a reserved-domain email for JIT users |
| `app/modules/users/api.py:123, 189, 210, 220, 254, ...` | `UserOut.model_validate(user)` on responses | The throw site for every affected endpoint |
| `app/common/exception/handlers.py` | unhandled-exception → `500 internal_error` | A Pydantic serialisation error is indistinguishable from a server fault |

`EmailStr` validation happens at **both** boundaries. Request models are the
right place for it; response models are not, because the row already exists and
may legitimately have been written by a system component (dev-token, JIT,
Zoho import, seeders) with a domain that `email-validator` calls special-use.

Reserved/special-use names rejected by `email-validator` include (RFC 2606 /
RFC 6761): `.test`, `.example`, `.invalid`, `.localhost`, and the
`example.com`/`example.net`/`example.org` **domain names**. Note that
`example.com` is allowed by `email-validator` in practice (test #1 registered
`testuser123@example.com` successfully), whereas a bare reserved **TLD** such
as `.test` / `.local` is rejected — which is exactly why `dev@local.test`
fails.

---

## 4. Why it looks like "registration / login" 500s

Registration and login themselves do not return a `User`:

- `POST /api/auth/register` → `UserOut` **of the newly created user**. With a
  normal email this is `201`. With a reserved-domain email the request is
  rejected earlier with `422`, so it never reaches the 500.
- `POST /api/auth/login` → `TokenPair` (no email field), so it cannot 500 this
  way.

The 500 appears on the **follow-up calls a client makes immediately after**
register/login — `/api/auth/me`, `/api/auth/me/profile`, `/api/users`,
`/api/users/{id}` — whenever the current user (or any user in a list) has a
reserved-domain email. The most common trigger in this deployment is the
`dev@local.test` user created by `POST /api/auth/dev-token`, which then poisons:

- `GET /api/auth/me`
- `GET`/`PATCH /api/auth/me/profile` (`/api/me/profile`)
- `GET /api/users` (list serialises every row, including the dev user)
- `GET /api/users/{id}` for that user
- `GET /api/users/{id}/moderation`, `/ban`, `/unban`, `/throttle`, `/unthrottle`
- `PUT /api/users/{id}`

Any other reserved-domain user in the table (Authentik JIT `@authentik.local`,
seeders, Zoho/CRM imports, fixtures) causes the same 500.

---

## 5. What is explicitly **not** the cause (ruled out)

| Candidate | Verdict | Evidence |
|---|---|---|
| Migrations not applied / schema drift | No | `alembic current` = `3b7f0ae91c46 (head)`; `SELECT users...` with all new columns succeeds |
| Tenancy / organization resolution broken | No | registration resolves `(tenant_id=1, organization_id=1)`; `dev-token` and admin-create stamp both |
| `MultiTenantMixin` / composite role FK | No | inserts succeed; login reads succeed |
| Password policy | No | weak password → intentional `422 password_policy` |
| Authentik sync / email delivery | No | both are best-effort (`try/except` + `SyncResult`) and never surface a 500 |
| The `.env` / DB credentials | No | DB queries execute; endpoints that do not serialise `UserOut` return 200 |

---

## 6. Recommended fix

### 6.1 Primary (minimal, correct)

Response models must not re-validate stored data. Change **output** schemas to
plain `str`, keep `EmailStr` on **input** schemas:

```python
# app/modules/users/schema.py
class UserOut(UserProfileBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str            # was EmailStr — output, not input
    ...

class UserCreate(UserProfileBase):   # input — keep EmailStr
    email: EmailStr

class UserUpdate(UserProfileBase):   # input — keep EmailStr | None
    email: EmailStr | None = None
```

`RegisterRequest.email` stays `EmailStr` (input). This preserves strict
validation of what clients may submit while allowing the API to represent rows
written by system components.

### 6.2 Secondary (defence in depth)

1. Stop generating reserved-domain emails:
   - `get_or_create_dev_user`: use a domain that passes validation, e.g.
     `dev@example.com` (or a real local domain). `@local.test` is guaranteed to
     fail.
   - `provision_from_authentik`: replace the `{sub}@authentik.local` fallback
     with `f"{sub}@example.com"` or a configurable, non-reserved domain.
2. Add a normalisation/guard step on every user write path (seeders, Zoho/CRM
   import, fixtures, JIT) so reserved domains cannot enter `users.email` in the
   first place.
3. Add a regression test asserting `UserOut.model_validate(user)` succeeds for a
   stored reserved-domain email (and that the `/api/users` list does not 500
   when such a row exists).
4. Optionally audit existing rows:
   `SELECT id, email FROM users WHERE email ~* '@(.*\.)?(test|local|invalid|localhost)$';`

Do **not** simply broaden the global 500 handler: the real defect is that the
contract ("a UserOut can represent any users row") is broken at the schema
boundary.

---

## 7. Has the Users & DLP implementation plan been applied?

**Verdict: essentially yes — the plan is applied at both the model and migration
level, with four small gaps/deviations.** The database is migrated to head and
the new modules exist.

### 7.1 Applied

| Plan item (§) | Status | Evidence |
|---|---|---|
| `users` → `MultiTenantMixin` (org NOT NULL) | Applied | `users/model.py:63` |
| `users` location-free; keep `country_code` + `primary_place_id` | Applied | `users/model.py:209-221` |
| `uq_users_tenant_id` | Applied | `users/model.py:267` |
| `uq_users_zoho_id_live` partial unique | Applied | `users/model.py:280-281` |
| 3-column role FK `(tenant_id, organization_id, role_id)` | Applied | `users/model.py:293-297` |
| `roles` → `OrgEntityMixin`; per-org `(tenant_id, organization_id, code)` uniqueness | Applied | `roles/model.py:24-32` |
| Seed system roles per organization on create | Applied | `organizations/service.py:188-191` |
| `user_live_locations` (1:1 last fix) | Applied | `users/model.py:464-516` |
| `user_location_pings` (partitioned history) | Applied | `users/model.py:519-556`; migration `3b7f0ae91c46` |
| New `hubs` module (org-scoped + `VerificationMixin`) | Applied | `hubs/model.py:49-50` |
| New `fleet_partners` module | Applied | `fleet_partners/model.py:46-47` |
| New `vehicles` module (`Vehicle`, `VehicleComplianceDocument`, `DrivingLicense`) | Applied | `vehicles/model.py:61-62,148-149,212-213` |
| `bank_accounts` payee-polymorphic (`owner_type`/`owner_id`, one-primary) | Applied | `hr/model.py:215-247` |
| `ConsentBoundMixin` (FK-only) | Applied (in `compliance/mixins.py`) | `compliance/mixins.py:9-20` |
| No polymorphic verification table; `VerificationMixin` used | Applied | hubs/fleet_partners/vehicles models |
| `kyc_audit_logs` org-scoped, no row_version/soft-delete | Applied | `compliance/model.py:187` |
| Migrations G1–G8 applied | Applied | `alembic current` = `3b7f0ae91c46 (head)` |

### 7.2 Not applied / deviations

| Plan item (§) | Status | Detail |
|---|---|---|
| `geo.place_links.OWNER_TYPES += "hub"` (§4.4, §8) | **Not applied** | `geo/model/link.py:88-101` has no `hub` (nor `vehicle`). The `hubs` model points at `geo.places` directly, but the address-book owner set was never extended. |
| `users.zoho_id` narrowed to `String(50)` (§4.1, §5 G2) | **Deviation** | still `String(255)` (`users/model.py:236`). Permitted by plan risk #6 for kept data, but the schema is greenfield, so the intended narrowing was skipped. |
| `ConsentBoundMixin` on `PANVerification` (§4.9) | **Not applied** | applied to `AadhaarVerification` (`kyc/model.py:155`) and `BackgroundVerification` (`:281`) but not `PANVerification` (`:199`). |
| `kyc_audit_logs` monthly partitioning (§4.9) | **Planned only** | docstring says "At scale … pg_partman"; no partition clause in the model/migration. Consistent with the plan's "partition-planned" wording. |
| `hubs`/`vehicles` in `DocumentLinkableType` (§8) | Applied (pre-existing) | `documents/enums.py:119,123` |
| `ConsentBoundMixin` location | Deviation (benign) | lives in `compliance/mixins.py`, not `database/mixins.py` |
| `bank_accounts` module location | Deviation (benign) | lives in `hr`, not `kyc` |

### 7.3 Definition of Done scorecard (§9)

- [x] `users` org-scoped, location-free, `primary_place_id`, `uq_users_zoho_id_live`
- [x] `roles` org-scoped with per-org uniqueness; system roles seeded per org
- [x] `hubs` and `fleet_partners` exist and are org-scoped
- [x] `vehicles`, `vehicle_compliance_documents`, `driving_licenses` exist, org-scoped, `VerificationMixin`, no `is_active` double truth
- [x] `user_live_locations` + partitioned `user_location_pings`
- [x] `bank_accounts` payee-polymorphic
- [~] `consent_records` authoritative; `ConsentBoundMixin` used — **PANVerification missing**
- [x] `kyc_audit_logs` kept, org-scoped, partition-planned
- [x] No polymorphic verification table; `VerificationMixin` used
- [ ] `geo.place_links.OWNER_TYPES` += `hub` — **missing**
- [ ] All tests green on a bare checkout — **the `UserOut` 500 above will fail any test that serialises a reserved-domain user**

---

## 8. Appendix — reproduction commands

```bash
# Registration (valid) — 201
curl -i -X POST http://localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test User","email":"testuser123@example.com","password":"Xk9#mQ2vLp7w"}'

# Registration (reserved TLD) — 422, input validation
curl -i -X POST http://localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"name":"Bad Email","email":"foo@bar.test","password":"Xk9#mQ2vLp7w"}'

# Get a dev token (creates dev@local.test), then the 500s
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/dev-token | jq -r .data.access_token)
curl -i http://localhost:8000/api/auth/me           -H "Authorization: Bearer $TOKEN"   # 500
curl -i http://localhost:8000/api/auth/me/profile   -H "Authorization: Bearer $TOKEN"   # 500
curl -i http://localhost:8000/api/users             -H "Authorization: Bearer $TOKEN"   # 500

# Migration state
docker exec backend alembic current        # 3b7f0ae91c46 (head)

# Reserved-domain rows currently in the DB
SELECT id, email FROM users
WHERE email ~* '@(.*\.)?(test|local|invalid|localhost)$';
```
