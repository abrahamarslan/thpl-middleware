# Implementation Plan — Enterprise Auth Audit Logging

**Status:** core implemented in this release (see §13 for phase status).
**Owners:** Platform / Backend
**Related:** [`modules/auth-module-documentation.md`](../../../docs/modules/auth-module-documentation.md),
[`AUTHENTIK_SYNC.md`](../../../docs/AUTHENTIK_SYNC.md).

---

## 1. Objective

Every authentication, credential and moderation event must be recorded in an
**enterprise-grade** way:

- **Durable & queryable** — persisted in Postgres (`activity_logs`), not just
  stdout, so it survives container restarts and answers "who did what, to whom,
  when, from where".
- **Correlated** — each entry carries `request_id` so it links to the exact
  Loki log lines / Tempo traces of the same request.
- **Complete** — register, login (success **and** failure), logout, token issue
  & refresh, password change, password reset request/complete, OTP request &
  login, throttle/unthrottle, ban/unban, and **field-level profile changes**.
- **Safe** — never store passwords, tokens or 2FA secrets; mask them even when
  they appear in a diff.
- **Independent of the business transaction's fate** — a *failed* login's audit
  record must persist even though the request transaction rolls back.

---

## 2. Design principles

1. **Dual write, one call.** Each event writes an `activity_logs` row *and* a
   structured `structlog` line from the same helper (`app/modules/users/audit.py`
   `audit()`), so the audit trail and operational log can never drift.
2. **The operational/business split is deliberate.** `activity_logs` = business
   & compliance audit (persisted, user-facing, queryable). Loki = what the
   process is doing (ephemeral, searchable, high volume). See
   `docs/AUDIT_AND_DATA_MODULES.md`.
3. **Append-only.** `activity_logs` rows are never updated or deleted. There is
   no soft delete and no `updated_at`.
4. **One catalog.** All action names are constants in `users/audit.py::Event`
   (dotted, stable). No ad-hoc action strings.
5. **Mask by default.** `model_changes()` masks `password`, `two_factor_secret`,
   `two_factor_recovery_codes`, `api_token`, `remember_token`.
6. **Best-effort audit, but never lose failures.** Audit writes use a SAVEPOINT
   so a broken audit never breaks the business op; failure paths additionally
   **commit** the security state + audit before raising (see §7).

---

## 3. Where it lives

| Path | Responsibility |
|---|---|
| `app/modules/users/audit.py` | `Event` catalog + `audit()` dual-write helper; `commit` semantics. |
| `app/modules/activity/model.py` | `ActivityLog` table (append-only). |
| `app/modules/activity/recorder.py` | `record_activity()` (persist) + `model_changes()` (masked diff). |
| `app/modules/users/service.py` | Register/login/logout/refresh/change-password/user CRUD instrumentation. |
| `app/modules/users/login_otp.py` | OTP request/verify instrumentation. |
| `app/modules/users/password_reset.py` | Reset request/complete instrumentation. |
| `app/modules/users/moderation.py` | Ban/unban/throttle/unthrottle instrumentation. |

---

## 4. Event catalog

All events are `activity_logs.action` values (indexed). `status ∈ {success,
failure}`; `actor` is the subject unless overridden (admin actions).

| Event | Trigger | Status | Notable `changes` / `context` |
|---|---|---|---|
| `auth.register` | self-registration | success | `{has_username, has_phone}` |
| `auth.provisioned` | first OIDC/SSO sight | success | `{method:"authentik", sub}` |
| `auth.login.success` | password login OK | success | `{method:"password", device_id}` |
| `auth.login.failure` | unknown identifier / bad password / guarded | failure | `{attempts, locked}` or `{reason}` |
| `auth.login.locked` | lockout threshold crossed | failure | `{attempts}` |
| `auth.logout` | `POST /api/auth/logout` | success | — |
| `auth.token.issued` | login / OTP / refresh minted tokens | success | `{method, access, refresh}` |
| `auth.token.refresh` | refresh OK | success | — |
| `auth.token.refresh.failure` | invalid/expired/disabled | failure | description |
| `auth.otp.request` | OTP code sent | success | `{expires_at}` |
| `auth.otp.request.suppressed` | unknown / cooldown / cap / banned | failure | description |
| `auth.otp.login` | OTP verified → tokens | success | `{device_id}` |
| `auth.otp.failure` | wrong/expired/exhausted/no-challenge | failure | `{attempts, exhausted}` |
| `auth.password.changed` | change-password OK | success | `{method:"self"}` |
| `auth.password.change.failure` | wrong current password | failure | description |
| `auth.password.reset.request` | code/link requested (or suppressed) | success/failure | `{reset_type, expires_at}` |
| `auth.password.reset.completed` | reset applied | success | `{method}` |
| `auth.password.reset.failure` | bad/expired/exhausted/guarded | failure | `{attempts, exhausted}` |
| `user.created` | admin creates user | success | `{created_by}` |
| `user.profile.updated` | admin/self profile edit | success | **`{field: {old, new}}` diff** |
| `user.deleted` / `user.hard_deleted` / `user.restored` | lifecycle | success | — |
| `user.moderation.ban` / `.unban` | ban/unban | success | `{reason, until}` |
| `user.moderation.throttle` / `.unthrottle` | throttle/unthrottle | success | `{reason, until}` |
| `email.queued` | email module (existing) | success | `{to, subject}` |

**Not** logged here: every OIDC-bearer request (would be per-API-call noise),
email provider webhook events (those live in `email_events`).

---

## 5. Data model & storage

`activity_logs` (existing; **no migration needed**):

| Column | Type | Use |
|---|---|---|
| `activity_id` | UUID | public identifier |
| `action` | varchar(100), indexed | event name (catalog above) |
| `status` | varchar(20) | `success` \| `failure` |
| `description` | text | human reason (esp. failures) |
| `actor_id` / `actor_type` / `actor_label` | bigint / varchar / varchar | who; label snapshots email |
| `subject_type` / `subject_id` | varchar / varchar | target (typically `User`) |
| `changes` | JSONB | field-level diff / event attributes |
| `context` | JSONB | device, location, country, user_agent, method, reason |
| `request_id` | varchar(64), indexed | → Loki / Tempo correlation |
| `ip_address` | varchar(45) | client IP (`X-Forwarded-For` first hop) |
| `created_at` | timestamptz, indexed | when |

Indexes: `ix_activity_subject(subject_type, subject_id)`,
`ix_activity_action_created(action, created_at)`,
`ix_activity_tenant_created(tenant_id, created_at)` (multi-tenant ready).

---

## 6. Profile update — field-level diff (JSON)

`service.update_user` computes a `{field: {old, new}}` diff with
`activity.recorder.model_changes()` **before** flushing (SQLAlchemy resets the
unit-of-work history on flush):

```python
crud.apply_values(user, values)                  # setattr only, no flush
diff = model_changes(user, exclude=set(GEO_FIELDS) | {"updated_by"})
await db.flush(); await db.refresh(user)
if diff:
    await audit(db, Event.USER_UPDATED, user=user, actor_id=updated_by,
                actor_label=actor_label, client=client, changes=diff,
                context={"fields": sorted(diff)})
```

- Sensitive attributes are masked to `{"old": "***", "new": "***"}`.
- Geospatial WKT fields are excluded (large, non-JSON-safe); their change is
  still visible via the field list in `context.fields`.
- The JSON is stored in `activity_logs.changes` for compliance review.

---

## 7. Failure-path transaction rule (the critical fix)

**Rule:** when a domain error is raised, the request's `get_db` dependency rolls
the transaction back. Therefore any security counter or audit row written
before the raise **must be committed explicitly**, or it is lost.

`audit(..., commit=True)` performs `record_activity()` then `await db.commit()`
(see `audit.py`). It is used on every failure path:

- login: unknown user, bad password, lockout, moderation guard;
- OTP: unknown, expired, exhausted, wrong code;
- reset: unknown, expired, exhausted, wrong code, guard;
- password change: wrong current password;
- refresh: invalid/disabled.

**Bug this fixes (found while building this):** prior to this release the
failure increments (`failed_login_attempts`, `locked_at`, OTP/reset `attempts`)
and the failure audit rows were rolled back — so **account lockout and the
attempt caps never actually persisted in production**. Regression test:
`tests/test_auth_failure_persistence.py` drives the real HTTP stack + real
`get_db` and asserts the counter and the `auth.login.failure` row survive.
Success paths are *not* committed early — they commit with the request.

---

## 8. Read / query surface

- **API:** `GET /api/activity` (JWT) — append-only read with filters
  (`action`, `actor_id`, `subject_type`, `subject_id`, date range, pagination)
  via `app/modules/activity/api.py`. `GET /api/activity/{activity_id}`.
- **SQL (ops):**
  ```sql
  -- recent failures for a subject
  select created_at, action, status, description, ip_address, context
  from activity_logs
  where subject_id = $1 and status = 'failure'
  order by id desc limit 50;

  -- who changed what on a record
  select created_at, actor_label, changes
  from activity_logs
  where action = 'user.profile.updated' and subject_id = $1
  order by id desc;
  ```

---

## 9. Operational observability

- Every event also emits `structlog.get_logger("app.users.audit").info(event,
  status=…, actor_id=…, **context)`, so it appears in Loki with the bound
  `request_id`/`client_ip`.
- Per-module verbosity is controlled by
  `config/logging/modules/users.yaml` (namespace `app.users`) — no redeploy to
  raise/lower auth logging.
- `request_id` ties an `activity_logs` row to its Loki lines and Tempo trace.

---

## 10. Analytics & retention (phased)

| Phase | Item | Status |
|---|---|---|
| A | Dual-write + `activity_logs` + API read | **done** |
| B | Add `public.activity_logs` to Debezium `table.include.list` → Kafka → ClickHouse for SIEM dashboards (failed-login rate, lockouts, resets, geo anomalies) | proposed |
| C | Retention/partitioning: time-partition `activity_logs` with `pg_partman` (installed) once volume justifies it; Loki keeps 30 days | proposed |
| D | Grafana dashboards on ClickHouse: auth success/failure heatmap, lockouts/hour, resets/hour, top source countries | proposed |
| E | Alerting: spike in `auth.login.failure`, mass `auth.password.reset.request`, ban/throttle events | proposed |

**Do not** partition now — `activity_logs` is low-volume and `pg_partman` is a
deliberate change to flag when the growth curve justifies it.

---

## 11. Security & privacy

- **Never** log secrets: `password`, tokens, 2FA secrets/codes, API tokens.
  Codes are HMAC-hashed at rest and **not** placed in audit context.
- `actor_label` intentionally snapshots email for survivability after user
  edit/delete; it is PII — treat `activity_logs` as sensitive.
- `ip_address` + GeoIP (`context.location`) are personal data. Restrict API
  reads (currently any authenticated user — see §13 Phase F) and consider
  retention limits for PII fields.
- Failed logins for **unknown** identifiers record `actor_label` = the attempted
  identifier with no subject — useful for attack analysis; ensure this doesn't
  conflict with account-enumeration policy (the user-facing response stays
  uniform).
- Audit writes are best-effort so a DB hiccup never denies login; failures are
  themselves logged (`activity_record_failed`).

---

## 12. Testing

| Test | Layer | Covers |
|---|---|---|
| `tests/test_auth_audit.py` | integration | register/login/logout, token issue, profile diff JSON, moderation events, password change. |
| `tests/test_auth_failure_persistence.py` | integration (real HTTP + `get_db`) | failure counter + failure audit survive the 401 rollback. |
| `tests/test_moderation.py` | integration | ban/throttle guards + audit. |
| `tests/test_auth_reset_flow.py` / `test_login_otp.py` | integration | reset/OTP flows still emit the expected events. |

Patch emails at the `auth_emails` boundary; assert on `activity_logs` rows via
the test session. All integration tests skip cleanly without Postgres.

---

## 13. Rollout status

**Implemented (Phase A):** `Event` catalog, `audit()` dual-write, `commit=True`
failure rule, instrumentation across register/login/refresh/logout/change-password/
reset/OTP/moderation/user-CRUD, profile diff, `POST /api/auth/logout`, tests.

**Next (tracked):**
- **Phase B** — Debezium `activity_logs` → ClickHouse analytics.
- **Phase C** — `pg_partman` partitioning + retention/archival policy.
- **Phase D/E** — Grafana dashboards + alerts.
- **Phase F** — role guard on `GET /api/activity` and the moderation endpoints
  (today: authenticated, not role-checked).
- **Phase G** — server-side token revocation (JWT `jti` + Redis denylist) so
  logout can invalidate tokens before expiry; add `logout.revoked` context.

---

## 14. Acceptance criteria

- [x] Every event in §4 produces an `activity_logs` row **and** a structured log.
- [x] Failure counters/audits persist despite the request rollback.
- [x] Profile edits store a masked `{field:{old,new}}` JSON diff.
- [x] `request_id` present on every audit row for Loki/Tempo correlation.
- [x] No secret ever appears in `changes`/`context`.
- [ ] Debezium → ClickHouse pipeline for `activity_logs` (Phase B).
- [ ] Role-gated read access (Phase F).

---

## 15. Decisions & open questions

- **Commit-on-failure** mutates the request session; acceptable because auth
  failure paths own their transaction (no unrelated pending work). Alternative
  (autonomous session per failure) is more isolation but more machinery — kept
  in reserve if a failure path ever gains unrelated writes.
- **Unknown-identifier failed logins** are logged with the attempted identifier
  as `actor_label`. Confirm this is acceptable under your privacy policy.
- **Retention window** for `activity_logs` (and PII fields) is unspecified;
  propose 12–24 months with PII minimization, pending compliance input.
