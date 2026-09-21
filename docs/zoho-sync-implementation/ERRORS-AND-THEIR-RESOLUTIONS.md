# Errors and their resolutions

Every error hit while building or operating the Zoho sync platform, with the
exact message, the root cause and the fix. **Append only** — an entry is never
deleted, because the next person greps this file with the error text in hand.

Entry format:

```
### E<nn> — <short title>
**When** …   **Symptom** (verbatim message)   **Root cause** …   **Fix** …   **Prevention** …
```

Legend: 🏗 build-time (development), 🚦 test, 🔥 runtime/production.

---

## Build phase 2 — platform core

### E01 — 🚦 429 without a Zoho code classified as `BUG`

**When** First run of `tests/zoho_core/test_policy.py` (2026‑09‑18).

**Symptom**
```
AssertionError: assert <ErrorCategory.BUG: 'bug'> is <ErrorCategory.RATE_LIMITED: 'rate_limited'>
 +  where <ErrorCategory.BUG: 'bug'> = classify(Outcome(method='POST', retry_safe=False,
      http_status=429, zoho_code=None, ...))
```

**Root cause** `ZOHO_CODE_CATEGORY` contained `0: ErrorCategory.BUG` ("success,
for completeness") and `classify()` looked up `code or 0`. A 429 with no
parseable Zoho code therefore resolved to the code‑0 entry instead of falling
back to the HTTP-status default.

**Fix** Removed the `0` entry (success is not an error category) and made both
429 and generic-4xx branches fall back explicitly when `code` is falsy:
`ZOHO_CODE_CATEGORY.get(code, default) if code else default`
(`app/modules/zoho/core/policy.py`, `errors.py`).

**Prevention** The classification table test now includes an unlabelled 429
(`out("POST", http_status=429)`); a sentinel value in a lookup table must never
share the "missing" slot.

---

### E02 — 🚦 Governor test suite hung for >5 minutes

**When** First run of `tests/zoho_core/test_governor.py` (2026‑09‑18).

**Symptom** `pytest tests/zoho_core` never returned; the shell had to be
killed. No output, no failure.

**Root cause** The tests simulated reaching the daily ceiling by making real
`acquire()` calls (`spend(gov, 1_000)`). Each call takes a token from the real
per-minute bucket (`rate_per_minute=60` → one token/second), so 1,000 calls
meant ~1,000 seconds of correct, intentional waiting.

**Fix** Added a `seed_used()` helper that writes the day counter straight into
the Redis hash, and used it for all threshold/ceiling tests. Real `acquire()`
calls are kept only where admission itself is under test, in small numbers.

**Prevention** Tests that exercise *policy* must not pay *physics*: when a
gate deliberately rate-limits, seed its state instead of driving it. Every new
governor test asserts in < 1 s (the suite runs in ~1 s).

---

### E03 — 🚦 Rate-reserve test hit the concurrency cap instead

**When** Same run as E02, test
`test_lower_priorities_leave_a_reserve_for_higher_ones`.

**Symptom**
```
ZohoRateLimitedError: Zoho concurrency budget unavailable for reconcile traffic
assert excinfo.value.data["reason"] == "rate"   # got "concurrency"
```

**Root cause** The test held five leases open to drain the token bucket, but
the fixture's `concurrency_limit` is 3 — the concurrency gate refused the
fourth acquire before the rate reserve could be reached. The gates are ordered
(quota → pacing → rate → concurrency), so a test targeting one of them must
keep the others out of the way.

**Fix** The test now uses `concurrency_limit=9` and releases each lease
immediately (`sent=True`), so only the token bucket is under test, and asserts
on `data["reason"] == "rate"`.

**Prevention** Every gate-specific test asserts the refusal `reason`, so a
refusal from the wrong gate fails loudly instead of passing by accident.

---

### E04 — 🚦 `'BreakerConfig' object has no attribute '__dict__'`

**When** First run of `tests/zoho_core/test_breaker.py` (2026‑09‑18).

**Symptom**
```
AttributeError: 'BreakerConfig' object has no attribute '__dict__'. Did you mean: '__dir__'?
  return ZohoCircuitBreaker(config=BreakerConfig(**{**config.__dict__, **overrides}), ...)
```

**Root cause** `BreakerConfig` is a `@dataclass(frozen=True, slots=True)`.
Slotted classes have no instance `__dict__`, so the common
"copy-with-overrides" idiom fails.

**Fix** Used `dataclasses.replace(config, **overrides)` in the test helper.

**Prevention** Remember that every config dataclass in `core/` is slotted for
memory and immutability; `replace()` is the supported way to derive one.

---

### E05 — 🚦 Recovery-backoff test tripped over its own probe

**When** First run of `test_recovery_backoff_is_capped` (2026‑09‑18).

**Symptom**
```
ZohoCircuitOpenError: Zoho 'books:test9fd35e98' circuit is open; retry in ~2s
```

**Root cause** The test deleted the state key to simulate the cool-down
lapsing, which puts the group in HALF_OPEN. The helper then called `allow()`
four times: the first call won the probe, its recorded failure reopened the
circuit, and the second call legitimately raised.

**Fix** The test now drives `_open()` directly and asserts the recovery ladder
`[1, 2, 4, 4, 4]` against `recovery_max_seconds`. Probe semantics are covered
by dedicated tests.

**Prevention** When a state machine has a gate, tests that target *one*
transition drive that transition directly instead of replaying traffic
through the gate.

---

### E06 — 🚦→🔥 `got Future … attached to a different loop` in the credential store

**When** Full test run after adding `tests/zoho_core/test_auth.py` (2026‑09‑18).
The test passed alone and failed in the full suite.

**Symptom**
```
RuntimeError: Task <Task pending name='Task-772' coro=<test_encrypted_round_trip_through_postgres() ...>>
got Future <Future pending cb=[BaseProtocol._on_waiter_completed()]> attached to a different loop
  app/modules/zoho/core/auth.py: in store → existing = await db.scalar(...)
```

**Root cause** `CredentialStore` used the module-level `async_session_factory`,
a **pooled** engine. Its connections are bound to the event loop that opened
them; an earlier test (own loop) had opened them, so this test's loop could
not use them. This is not only a test artefact: every Celery task runs in a
fresh loop via `asyncio.run`, so a token refresh inside a task with DB
persistence enabled would have failed the same way in production.

**Fix** `CredentialStore(session_factory=…)` is injectable, with
`bind_session_factory()`; `app/tasks/zoho_sync.py::_run` binds the task's
throwaway NullPool factory before any Zoho call; the test injects the `db`
fixture's engine.

**Prevention** Any async component that touches Postgres and may run inside a
Celery task takes a session factory instead of importing the global one. The
permanent fix is the per-process event loop for workers (ADR‑3), planned with
the task-layer rework.

---

### E07 — 🚦 Pre-existing: auth tests fail with `user_profiles_country_iso2_fkey`

**When** First full run with the scratch Postgres up (2026‑09‑18). These tests
were being **skipped** before because no database was running.

**Symptom**
```
asyncpg.exceptions.ForeignKeyViolationError: insert or update on table "user_profiles"
violates foreign key constraint "user_profiles_country_iso2_fkey"
FAILED tests/test_auth_audit.py::test_register_login_logout_are_audited
FAILED tests/test_auth_failure_persistence.py::test_failed_login_persists_counter_and_audit
FAILED tests/test_login_identifier.py::test_login_by_email_username_and_phone
```

**Root cause** Not related to the Zoho work — reproduced on an untouched
checkout of `HEAD` (`git worktree`, same result). User registration creates a
`user_profiles` row referencing `countries.iso2`, but a freshly migrated
scratch database has no reference data, and `tests/conftest.py` truncates
`countries` between tests anyway.

**Fix** None applied here (outside this workstream). Options for the users
module owner: seed `countries` in the `db` fixture (and drop it from
`_TEST_TABLES`), or make the profile's country nullable when unknown.

**Prevention** Integration tests that depend on reference data must seed it in
their fixture — a green run with skipped integration tests hides this class
of failure.

---

### E08 — 🏗 PowerShell mangles inline bash in `wsl -- bash -lc "…"`

**When** Restarting the scratch containers from Windows (2026‑09‑18).

**Symptom**
```
seq : The term 'seq' is not recognized as the name of a cmdlet …
bash: -c: line 1: syntax error near unexpected token `>'
```

**Root cause** PowerShell evaluates `$( … )` and escapes inside the
double-quoted argument before WSL ever sees it, so the bash loop arrived
broken.

**Fix** Added `apps/core-platform/backend/.dev_scratch.sh` (start scratch
Postgres + Redis idempotently, wait for readiness through kartoza's restart,
run migrations; `stop` removes them). Invoke it as
`wsl -d Ubuntu -- bash -lc "bash …/.dev_scratch.sh"`.

**Prevention** Anything longer than one command goes in a script file, never
inline through PowerShell (also recorded in the dev-environment notes).

---

### E09 — 🚦 Integration tests silently skipped after a session pause

**When** Resuming work after an interruption (2026‑09‑18).

**Symptom** `176 passed, 103 skipped` — the governor, breaker and auth
integration tests were not running, but the run looked green.

**Root cause** The scratch containers were started with `--rm` and had gone
away; `redis_available` / `db` fixtures skip cleanly by design.

**Fix** `bash .dev_scratch.sh` before running the suite; the expected skip
count with both services up is **0** for `tests/zoho_core`.

**Prevention** When verifying Zoho platform changes, check the skip count, not
just the pass count. CI must run with both services (Phase 3).

---

### E10 — 🏗 Celery `autoretry_for=(ZohoApiError, …)` would replay ambiguous creates

**When** Review of `app/tasks/zoho_sync.py` after wiring the transport
(2026‑09‑18). Found before it shipped; no runtime occurrence.

**Symptom** None yet — a latent duplicate-record bug. Chain of events it would
have caused: `POST /invoices` → 502 → transport raises `ZohoAmbiguousOutcome`
(correctly, no client retry) → Celery sees an instance of `ZohoApiError` →
`autoretry_for` retries the whole push 60 s later → Zoho, which had created the
invoice, creates a second one.

**Root cause** To keep v1 `except ZohoApiError` sites working, `ZohoApiError`
became an **alias of the base class** `ZohoError`. The v1 task retry tuple
listed `ZohoApiError`, which therefore silently widened to *every* Zoho
failure, including `AMBIGUOUS`, `QUOTA_EXHAUSTED`, `AUTH_REVOKED` and
validation errors.

**Fix** `_RETRY_KW` now lists only retryable classes
(`ZohoTransientError`, `ZohoRateLimitedError`, `ZohoCircuitOpenError`,
`ZohoAuthError`) and adds `dont_autoretry_for` for ambiguous, quota-exhausted,
auth-revoked, validation, not-found, contract and unclassified errors (the
explicit exclusion matters because `ZohoAuthRevokedError` subclasses
`ZohoAuthError`).

**Prevention** `tests/zoho_core/test_task_retry_policy.py` fails if
`ZohoApiError` ever reappears in a task's `autoretry_for`, or if any
non-retryable category stops being excluded. General rule: after aliasing a
class to a broader one, grep every `isinstance`/`except`/`autoretry_for` site.

---

## Build phase 4 — control plane

### E11 — 🏗 Autogenerate wanted to drop the events partition (and found other modules' drift)

**When** Drafting a migration with `.dev_migrate.sh revision` after adding the
control tables (2026‑09‑18).

**Symptom** The generated draft contained
`op.drop_table('zoho_sync_events_default')` plus operations for other modules:
`remove_column users.postal_code`, a changed `uq_country_timezone` constraint,
a `password_reset_tokens.token` comment.

**Root cause** (a) Partition children are real tables that exist only in the
database, not in the SQLAlchemy metadata, so autogenerate treats them as
orphans. (b) The users/countries items are **pre-existing drift** between those
modules' models and their migrations — not part of this work.

**Fix** Draft discarded; migrations written by hand. `alembic/env.py`
`_include_object` now ignores children of `_PARTITIONED_PARENTS`
(`zoho_sync_events_*`) and their indexes. `alembic check` after the change
reports **no** Zoho/settings drift; the users/countries drift remains for that
module's owner.

**Prevention** Review every autogenerated draft line by line; never commit
operations on tables outside the change's scope.

---

### E12 — 🏗→🔥 `relation "setting_definitions" does not exist`

**When** First run of the switch tests (2026‑09‑18).

**Symptom**
```
asyncpg.exceptions.UndefinedTableError: relation "setting_definitions" does not exist
[SQL: SELECT setting_definitions.group_id, … WHERE setting_definitions.key = $1]
```

**Root cause** The hierarchical settings module (`app/modules/system/model.py`:
`system_modules`, `setting_groups`, `setting_definitions`, `setting_values`,
`setting_audit_logs`, enums `setting_type_enum`, `setting_context_enum`) was
added **without a migration**. Every database built from Alembic lacked these
tables, so `system_settings_service` could not work anywhere — including the
v1 token persistence path (`ZOHO_TOKEN_PERSISTENCE_ENABLED`).

**Fix** Migration `e6f7a8b9c0d1_system_settings_tables`, defensive: each table,
index and enum type is created only if absent, so an environment that created
them by hand still upgrades. Enum labels are the Python member **names**, which
is what SQLAlchemy persists.

**Prevention** `alembic check` on a freshly migrated scratch DB is part of the
definition of done for any model change (it would have flagged these five
tables immediately).

---

### E13 — 🚦 `got multiple values for keyword argument 'module'` in `finish_run`

**When** First leased-run test (2026‑09‑18).

**Symptom**
```
TypeError: …make_method.<locals>.meth() got multiple values for keyword argument 'module'
  app/modules/zoho/control/runs.py: log("zoho.run.finished", …, module=run.module, …, **(counters or {}))
```
and, once fixed, a second assertion failure: the run summary returned
`status='success'` instead of `'succeeded'`.

**Root cause** Callers pass the engine's whole `SyncRunReport.model_dump()` as
"counters"; that dict also contains `module`, `mode` and `status`. Spread into
the log call it collided with explicit keywords, and spread into the task's
return value it overwrote the run status.

**Fix** `finish_run` extracts only the known counter columns (`_COUNTER_FIELDS`)
for both the UPDATE and the log; `execute_leased_run` builds its result as
`{**counters, "status": …, "run_id": …}` so the run's status wins.

**Prevention** Never `**`-spread a foreign dict into structured-log calls or
return values; select fields explicitly.

---

### E14 — 🚦 `function make_interval(days => text) does not exist`

**When** First retention purge test (2026‑09‑18).

**Symptom**
```
asyncpg.exceptions.UndefinedFunctionError: function make_interval(days => text) does not exist
```

**Root cause** The per-row keep-days is a SQL `CASE … THEN :k0 …` built from
policies. asyncpg infers an untyped bind parameter inside `CASE` as `text`, and
`make_interval(days => …)` has no text overload.

**Fix** `THEN CAST(:k{i} AS integer)` in `_keep_case_sql`
(`app/modules/zoho/control/retention.py`).

**Prevention** Cast bind parameters explicitly wherever Postgres cannot infer
the type from a column (CASE branches, function arguments, VALUES lists).

---

### E15 — 🚦 Design flaw: a long retention class pinned every partition

**When** Partition-drop test (2026‑09‑18).

**Symptom** `assert 'zoho_sync_events_p20200101' in []` — a 2020 partition was
not dropped.

**Root cause** The first rule dropped partitions older than the **longest**
policy. With approval events kept 7 years, no partition younger than 7 years
could ever be dropped, turning all retention into row-by-row DELETEs — the
exact cost partitioning exists to avoid.

**Fix** A partition is dropped when it is older than the longest policy, **or**
older than the shortest policy **and empty** after `purge_events` ran. The
nightly job now purges first, then drops. Tests cover both an empty old
partition (dropped) and one holding an approval event (kept).

**Prevention** When mixing retention periods in one partitioned table, test
the drop rule with the extreme policy combination, not only the defaults.

---

### E16 — 🚦 `TestClient` would share an asyncpg session across event loops

**When** Writing the operator API end-to-end tests (2026‑09‑18). Caught
before running.

**Symptom** (expected) `… attached to a different loop` — same family as E06.

**Root cause** `fastapi.testclient.TestClient` runs the app in its own thread
and event loop; overriding `get_db` with the test's `db` session would hand a
connection bound to the pytest loop to a different loop.

**Fix** End-to-end tests use `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`
inside async tests, so the app runs on the test's loop. `TestClient` is kept
only for tests that never touch the database (route presence, 403).

**Prevention** Any API test that overrides `get_db` with the `db` fixture must
use the ASGI transport.

---

### E17 — 🏗 `SwitchState` built from `None` when Postgres was unreachable

**When** First switch test run (2026‑09‑18), surfaced by E12.

**Symptom**
```
AttributeError: 'NoneType' object has no attribute 'get'
  app/modules/zoho/control/switches.py: modules = durable.get("paused_modules") or []
```

**Root cause** When the database read failed, `_load_from_database()` returned
`None` and `snapshot()` passed it straight to `_build()`.

**Fix** `self._build(durable or {}, …)` — an unreadable settings table yields
the safe defaults (engine running, pull/push enabled, webhooks off) with
`source="defaults"`, and the failure is logged (`zoho.switches.database_unavailable`).

**Prevention** Every "degraded" branch gets a test that forces the dependency
to fail.

---

### E18 — 🏗 Inline heredoc patch failed through Git Bash

**When** Patching `app/tasks/zoho_sync.py` from the Windows side (2026‑09‑18).

**Symptom**
```
/usr/bin/bash: -c: line 145: unexpected EOF while looking for matching `''
```

**Root cause** A long `python - <<'EOF' … EOF` block containing triple-quoted
Python strings and backslashes was mangled on its way through the Git Bash
tool wrapper.

**Fix** Large patches are written to a script file in the scratchpad and run as
`python patch.py <target>`.

**Prevention** Same rule as E08: anything non-trivial goes in a file, not inline.

---

## Build phase 4 (second half) — apply gate, slices, config resolver

### E19 — 🏗 Alembic "Cycle is detected in revisions"

**When** First `alembic upgrade` of the apply-gate migration (2026‑09‑19).

**Symptom**
```
UserWarning: Revision f7a8b9c0d1e2 is present more than once
ERROR [alembic.util.messaging] Cycle is detected in revisions (a1b2c3d4e5f6, c3d4e5f6a7b8, d4e5f6a7b8c9, e6f7a8b9c0d1, f7a8b9c0d1e2)
```

**Root cause** Revision ids in this chain had been hand-picked as "the next
hex-looking sequence" (`c3d4…`, `d4e5…`, `e6f7…`). `f7a8b9c0d1e2` was already
used by `20260917_1700_…_countries_timezones_user_profiles.py`, so the new
migration pointed back into the existing chain.

**Fix** Renamed the migration with a random id: `f79d022c961a`
(`20260919_0900_f79d022c961a_zoho_apply_gate.py`).

**Prevention** Generate ids (`uuid.uuid4().hex[:12]` or `alembic revision`),
and never pick them by hand. Before committing a migration, run
`grep -rl <id> alembic/versions`.

---

### E20 — 🏗 Config change published before it was committed (latent race)

**When** Design review of `ConfigResolver.set` (2026‑09‑19). Caught before any
test failed.

**Symptom** (would have been) A worker keeps using the old value of a knob
until the *next* override change, although the operator API reported success.

**Root cause** `set()` flushed the settings row and bumped `zoho:cfg:version`
while the transaction was still open. A worker that noticed the new version in
that window reloaded, still saw the old row (uncommitted), and cached the old
value **under the new version**. Nothing would make it reload again.

**Fix** `set()` / `clear()` **commit first, then** `INCR zoho:cfg:version`. An
override is its own transaction (`app/modules/zoho/control/config.py`).

**Prevention** Rule for every cache that is invalidated by a version counter:
bump the counter only after the data it describes is durable. Covered by
`test_other_processes_see_a_change_via_the_version_counter`.

---

### E21 — 🏗 Settings service cannot "remove" an override

**When** Implementing `DELETE /api/zoho/admin/config/{module}/{knob}` (2026‑09‑19).

**Symptom** After `delete_setting`, `get_setting` still returned the removed
value. No `setting_audit_logs` row recorded the removal.

**Root cause** `system_settings_service.set_setting` auto-creates the
definition with `default_value` = the **first value ever set**, and
`get_setting` falls back to that default. The definition's `value_type` is
likewise frozen by the first write. `delete_setting` also writes no audit row.

**Fix** The resolver does not use `get_setting`. It reads the GLOBAL
`setting_values` rows for `zoho.module.%` directly (one query) and casts with
its own knob types. `clear()` deletes the value row itself and writes a
`SettingAuditLog` (`new_value = "(override removed)"`).

**Prevention** Documented in [`config-resolver.md`](config-resolver.md) §3.
Longer term the settings module should create definitions with an explicit
default and type, and audit deletes. That is a separate change to that module.

---

### E22 — 🏗 Windows-side Python patch scripts rewrote files with CRLF

**When** Patching `transport.py` / `fake_client.py` with a script run by the
Windows `python` (2026‑09‑19). The same happened silently to 17 files patched
in earlier turns.

**Symptom**
```
app/modules/zoho/core/transport.py: Python script, Unicode text, UTF-8 text executable, with CRLF line terminators
```
(The files had been LF at HEAD.) While normalising, a first
"fix all changed files" loop also converted user-owned CRLF files
(`docs/zoho-docs-md/*.md`, `.dockerignore`), which then had to be restored.

**Root cause** `open(p).write(s)` in text mode on Windows translates `\n` to
`\r\n`. A second trap: Git Bash sees a WSL file named
`countries.json:Zone.Identifier` under a different name, so its `git status`
disagrees with WSL's.

**Fix**
* Converted the 17 affected source/doc files back to LF.
* Restored CRLF on the user files by comparing with the HEAD blobs. Verified
  with WSL `git diff`: zero content changes, only the pre-existing mode bits.
* All patch scripts now run as `wsl -d Ubuntu -- python3 script.py` and write
  with `newline="\n"`.

**Prevention** Never run file-writing scripts with the Windows interpreter on
`\\wsl.localhost` paths, and only use WSL `git` for status/diff. A normalising
loop may touch only files this work changed, checked against HEAD's line
endings.

---

### E23 — 🚦 `integration redis unavailable` skip after the engine started using Redis

**When** Full Zoho suite after wiring the config resolver into the engine
(2026‑09‑19).

**Symptom**
```
SKIPPED [1] tests/zoho_core/test_auth.py:69: integration redis unavailable (see tests/conftest.py)
```

**Root cause** `ZohoSyncEngine.run()` now reads `zoho:cfg:version`. Engine
tests that don't request the `redis_available` fixture left pooled connections
bound to their (closed) event loop. The next test's `ping()` raised, and the
fixture reported that as "unavailable".

**Fix**
* `redis_available` closes the pool before pinging (`tests/conftest.py`).
* The resolver treats `RuntimeError` / `OSError` like a Redis outage (falls
  back to Postgres), so a loop-bound pool can never break a sync.
* An autouse fixture resets the resolver cache between tests.

**Prevention** Any new Redis read on the engine path gets the same
degrade-to-Postgres handling. Test runs must report **0 skipped** with the
scratch services up.

---

### E24 — 🔥 v1 engine gaps found while building the gate (fixed)

**When** Reading the v1 engine and task code against the target architecture
(2026‑09‑19).

| Gap | Effect in production | Fix |
|---|---|---|
| "Revive soft-deleted rows" was documented but `deleted_at` was never cleared | a record deleted and re-created in Zoho stayed invisible locally | apply gate rule 3 (`resurrected`), tombstones marked with `remote_deleted_at` |
| One transaction per run, no heartbeat | a full scan longer than Celery's 540 s soft limit was killed and **rolled back entirely**; its 720 s lease could expire mid-run | bounded slices (240 s default), per-page commit, heartbeat per page ([`apply-gate.md`](apply-gate.md) §4) |
| A `weekly_full` run paused by the governor counted as that week's full | the reconcile silently skipped a week | planner continuations ([`control-plane.md`](control-plane.md) §4.3) |
| Inbound apply always set `sync_status='synced'` | a queued or failed push disappeared from the UI | `queued` / `syncing` / `error` are preserved |
| Detail fetch for every listed record | 200 detail calls per list page even when nothing changed | detail skip when the stored detail is at the listed version |

**Prevention** Covered by `tests/zoho_core/test_apply_gate.py`,
`test_slices.py` and `tests/zoho_sync/test_engine.py`.

---

### E25 — 🔥 Compose never passed the control-plane settings

**When** Deploy-step review (2026‑09‑19).

**Symptom** Setting `ZOHO_OPERATOR_EMAILS` in `deployment/.env` had no effect.
Every operator request returned 403 in production.

**Root cause** The control-plane settings added in the previous change
(`ZOHO_OPERATOR_EMAILS`, `ZOHO_PLANNER_*`,
`ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`) were in `conf.py` and the docs but not in
the `x-backend-env` block of `deployment/docker-compose.yml`. Containers only
see variables that compose passes through.

**Fix** Added them, plus this change's slice and write-pressure settings, to
`docker-compose.yml`, `.env.example` and `.env.prod.example`. Verified with
`docker compose config --quiet`.

**Prevention** Checklist item in the README "Deploy" section: every new
`ZOHO_*` setting goes to all three files in the same change.

---

## Build phase 5 — package-by-feature, batched apply, worker loop, O1 masters

### E26 — 🏗 `ruff check --fix` over the whole tree rewrote files outside the change

**When** Linting after the Phase 5 changes (2026‑09‑19).

**Symptom**
```
Found 33 errors (22 fixed, 11 remaining).
```
The 22 fixes went to 13 files, 11 of them unrelated to the Zoho work
(`app/common/time.py`, `app/modules/users/*`, `tests/test_profile_endpoints.py`, …).

**Root cause** `--fix` was pointed at `app tests` instead of the files this
change touched.

**Fix** Each affected file was classified by running ruff on its HEAD version
and comparing the result with the working copy (`ruff_audit.sh`):
* 9 files were HEAD-clean before ruff → restored with `git checkout HEAD -- …`
  (exact);
* 2 files carried earlier edits (`zoho/auth/api.py`, `test_profile_endpoints.py`)
  → only the imports ruff removed were put back.

`git diff HEAD` for both now shows only the intended earlier changes.

**Prevention** `--fix` only with an explicit list of this change's files;
whole-tree runs are check-only. (Same class as E22: a normalising action must
be scoped to what the change owns.)

---

### E27 — 🚦 Planner tick tests assumed a single registered module

**When** First run after registering currencies and taxes (2026‑09‑19).

**Symptom**
```
AssertionError: assert ('organizations', 'scheduled', None) in [('currencies', 'scheduled', None), ('taxes', 'scheduled', None)]
```

**Root cause** Three modules were due; `ZOHO_PLANNER_MAX_CONCURRENT_RUNS=2`
correctly enqueued two of them (equal priority, equal overdue). The tests had
encoded "organizations is the only module".

**Fix** The tests raise the cap and assert per module
(`tests/zoho_core/test_planner_tick.py`).

**Prevention** Planner tests assert on the module they are about, never on the
whole enqueue list.

---

### E28 — 🏗 List endpoints without `page_context` (design finding)

**When** Writing the currencies adapter from `docs/zoho-docs-md/currency.md`
(2026‑09‑19).

**Symptom** (would have been)
```
ZohoContractError: list response for /settings/currencies has no page_context
```

**Root cause** The transport treats a list without `page_context` as a contract
violation (a Phase 2 safety rule: v1 silently ended scans). Some settings lists
are documented as a single un-paginated response.

**Fix** `ModuleSyncConfig.paginated` (default `True`); `False` makes the engine
issue one `GET` and treat it as the only page. Also added `api` (`books` |
`inventory`) so Inventory modules route to the Inventory base URL.

**Prevention** Adapter checklist step 3 ([`package-by-feature.md`](package-by-feature.md)
§4). **[verify]** in Phase 0 against the live org.

---

### E29 — 🔥 Organizations sync would fail every run: `/organizations` has no `page_context`

**When** First end-to-end run of the masters through the real transport
(`tests/zoho_core/test_masters_e2e.py`, 2026‑09‑19).

**Symptom**
```
app.modules.zoho.core.errors.ZohoContractError: list response for /organizations has no page_context
```

**Root cause** Since Phase 2 the transport treats a list response without
`page_context` as a contract violation (E28). `GET /organizations` returns every
org the token can see in one response with no pagination (the vendored doc has
no response example at all). The organizations module was left as
`paginated=True`, so in production **every organizations run would have
failed**. The existing tests used `FakeZohoClient`, whose `make_response`
always adds a `page_context`, which masked the problem.

**Fix** `paginated=False` in `app/modules/organizations/zoho/spec.py`. The
slice/resume tests moved to taxes, a genuinely paginated module.

**Prevention** Every adapter's documented response now also goes through the
**real transport** in `test_masters_e2e.py::ZohoWire` (adapter checklist step
9). **[verify]** in Phase 0 against the live org.

---

### E30 — 🚦 `TypeError: unsupported operand type(s) for |: 'function' and 'NoneType'`

**When** Running the CLI e2e test on its own (2026‑09‑19); it passed in the full suite.

**Symptom**
```
stop_reason  TypeError: unsupported operand type(s) for |: 'function' and 'NoneType'
```

**Root cause** The test monkeypatched `transport.ZohoClient` with a factory
*function*. A module imported lazily **after** the patch (the engine, via the
CLI) evaluates the annotation `ZohoClient | None` at import time, and
`function | None` is a TypeError. In the full suite those modules were already
imported, so the order hid it.

**Fix** Patch with a **subclass** (`WiredClient(ZohoClient)`) that injects the
mock HTTP client and the stub token manager.

**Prevention** Replace classes with subclasses in tests, never with functions,
and run a new test file on its own at least once.

---

### E31 — 🔥 After connecting Zoho: `validation_error … loc: ["query","code"] … ["query","state"]`

**When** Connecting Zoho from Swagger on the dev stack (2026‑09‑19, reported by the user).

**Symptom**
```
{"code":"validation_error","msg":"Request validation failed","data":[{"type":"missing","loc":["query","code"],…},
 {"type":"missing","loc":["query","state"],…}], "request_id":"4af334eb95854843bc83e4…"}
```

**Root cause** A redirect loop in our code, not a Zoho failure. The backend log
for that session shows `zoho_oauth_callback_success` and `zoho_auth_connected`:
the code exchange had **succeeded**. Then `return_url` defaulted to
`ZOHO_REDIRECT_URL`, which is Zoho's `redirect_uri`, i.e. **the callback
itself**, and the user had also entered it in Swagger's `return_url` field. So
the callback redirected the browser to `/callback` without query parameters,
and FastAPI rejected that second request with a 422. Two different concepts
(Zoho's redirect URI and the browser's landing page) shared one setting. The
dev `.env.example` also pointed `ZOHO_REDIRECT_URL` at a route that does not
exist (`/zoho/callback`).

**Fix**
* New `ZOHO_AUTH_RETURN_URL` (landing page) and `ZOHO_AUTH_RETURN_HOSTS`
  (open-redirect allow-list) in `conf.py`, compose and both env examples.
* `resolve_return_url()` ignores the callback URL, accepts relative paths or
  allowed hosts only, and returns None → the callback answers JSON.
* `/callback` takes `code`/`state` as optional and handles Zoho's `?error=`: it
  answers 400 `zoho_consent_failed` with an explanation instead of a bare 422.
* `.env.example` callback fixed to `https://app.local/api/zoho/auth/callback`.

**Prevention** `tests/zoho_core/test_oauth_flow.py` runs the full consent
round-trip, including the "callback typed as return_url" case, against a mocked
Zoho token endpoint.

---

### E32 — 🔥 A successful connect was silently lost within minutes

**When** Same session as E31 (2026‑09‑19).

**Symptom** None visible at first. `GET /api/zoho/auth/status` would flip to
disconnected after ~5 minutes; workers and the CLI never saw a token
(`CredentialUnavailable`).

**Root cause** `deployment/.env` had no `ZOHO_TOKEN_PERSISTENCE_ENABLED` /
`ZOHO_TOKEN_ENCRYPTION_KEY`. `CredentialStore.store()` then only logs
`zoho.auth.credential_not_persisted` and keeps the refresh token in that API
process's 5-minute cache. The token existed nowhere else: not in Postgres, and
deliberately not in Redis.

**Fix** `/initiate` refuses with **409 `zoho_token_storage_not_configured`**
(listing what is missing) before sending anyone to Zoho, so a consent can no
longer be wasted. Also refused when `ZOHO_REDIRECT_URL` is empty.

**Prevention** `test_initiate_refuses_when_the_token_could_not_be_kept`; the
runbook step 0 in [`cli.md`](cli.md) sets both variables first.

---

## First live run (2026‑09‑19) — Tarrina Health org

### E33 — 🔥 `cli check` crashed: `cannot import name 'zoho_switches' … (most likely due to a circular import)`

**When** `dc exec backend python -m app.modules.zoho.cli check --live` (user report).

**Symptom**
```
File "/app/app/modules/zoho/control/switches.py", line 40 … from app.modules.zoho.core.errors import ZohoBudgetDeferred
File "/app/app/modules/zoho/core/__init__.py", line 42 … from app.modules.zoho.core.transport import …
File "/app/app/modules/zoho/core/transport.py", line 52 … from app.modules.zoho.control.switches import zoho_switches
ImportError: cannot import name 'zoho_switches' from partially initialized module 'app.modules.zoho.control.switches'
```

**Root cause** An import cycle, switches → `core.errors` → `core/__init__`
(eagerly imports the transport) → transport → switches. It only appears when
**switches is the first Zoho module a process imports**. `cli check` does
exactly that; the API, the workers and every test import the transport first.

**Fix** The transport resolves the switches lazily (the `_switches` property,
on the first call), so importing the transport no longer imports switches.

**Prevention** `tests/test_import_cycles.py` imports **every** module of
`app/modules/zoho`, the five feature packages and `app/tasks` as the first
import of a fresh interpreter.

---

### E34 — 🔥 `transform_failed field=fiscal_year_start_month raw="'april'" transform=int`

**When** First live organizations sync.

**Root cause** The vendored doc gives `fiscal_year_start_month` as an integer
(0–11). The live API sends the month **name** (`"april"`), so the value was
dropped (NULL). This is the first *documented ≠ live* finding; more will come,
which is why the live run comes before new modules.

**Fix** New mapper transform `month_index` (int 0–11, `"3"`, `"april"`,
`"apr"` → 0-based index) used by the organizations field map. The next
organizations sync fills the column.

**Prevention** `test_month_index`. Record every live difference here and in
the adapter doc.

---

### E35 — 🔥 Zoho code 6041 `This user is not associated with the CompanyID/CompanyName:60059694101`

**When** First live `cli sync`: organizations succeeded, and currencies, taxes,
locations and users failed.

**Root cause** `ZOHO_ORGANIZATION_ID=60059694101` in `deployment/.env` is not
an organization of the connected Zoho user. The only org it can see is
**60015628348, Tarrina Health Private Limited** (now mirrored in
`zoho_organizations`). `GET /organizations` does not take `organization_id`,
which is why only that module worked. Two follow-on problems:
* 6041 was classified `validation` (a data problem) instead of configuration;
* the encrypted refresh token is stored **keyed by org id**, so correcting the
  id would have looked like "not connected" and forced a second consent,
  although a refresh token belongs to the Zoho *user*, not to an org.

**Fix**
* A 400 now honours known Zoho codes; **6041 → FORBIDDEN** (never retried),
  and the message carries a hint: wrong `ZOHO_ORGANIZATION_ID`, run
  `cli check --live`.
* `cli check --live` lists every org the user can see and says OK/WRONG for
  the configured id.
* `CredentialStore` prefers the current org's credential and otherwise uses
  the most recently rotated active one (logged as
  `zoho.auth.credential_org_mismatch`). Correcting the org id needs **no**
  re-consent.
* `cli status` / `cli runs` show why a run failed (the `why` / `reason` column).

**Prevention** `test_wrong_org_id_is_forbidden_with_an_actionable_hint`,
`test_credential_stored_under_the_old_org_is_still_used`; `cli check --live`
is step 3 of the runbook.

---

## Tenancy build (2026‑09‑20) — tenants, organizations, roles

### E36 — 🚦 `type object 'TenantBound' has no attribute 'tenant_id'`

**Root cause** `with_loader_criteria(TenantBound, lambda cls: cls.tenant_id == t)` evaluates
the lambda against the marker class itself. The marker had no column.

**Fix** `TenantBound` declares `tenant_id` (as `SoftDeleteFilteredMixin` declares
`deleted_at`). Organizations redeclares it with its named FK.

---

### E37 — 🚦 `expression 'Tenant' failed to locate a name ('Tenant')`

**Root cause** Engine-only tests imported the organizations model without the tenants model,
so the `tenant` relationship target was not mapped when mappers configured.

**Fix** The two modules import each other at safe points (organizations imports `Tenant` at
the top; tenants imports organizations at the bottom, after `Tenant` exists).

---

### E38 — 🚦 `MissingGreenlet … Error extracting attribute: updated_at`

**Root cause** `updated_at` is computed by the server (`onupdate=now()`). After an UPDATE it
is expired, and serialising the response lazily reloads it outside the async context.

**Fix** `eager_defaults=True` on every versioned entity (RowVersionMixin): INSERT/UPDATE use
`RETURNING`, so no extra query.

---

### E39 — 🏗 `SAWarning: unresolvable cycles between tables "organizations, zoho_currencies"`

**Root cause** `zoho_currencies → organizations` (composite tenant/org FK) and
`organizations.currency_id → zoho_currencies`.

**Fix** `use_alter=True` on `fk_organizations_currency`.

---

### E40 — 🏗 Import contracts broke once organizations became the tenancy core

**Root cause** Every API reaches organizations through `users.deps` (authentication binds the
tenant), so "the Zoho platform never imports organizations" and "features are independent"
no longer described the architecture.

**Fix** The contracts are restated by layer:
* tenancy core: tenants / organizations / roles;
* Zoho platform;
* Zoho masters: currencies / taxes / locations / zoho_users.

A new contract says the tenancy core never imports a master. The organizations hook that
resolves the currency FK uses table-level SQL.

---

### E41 — 🏗 `alembic check` reported the `org_management` tables as missing

**Root cause** Autogenerate only compares the default schema.

**Fix** `include_schemas=True`, restricted by `include_name` to `public` and `org_management`,
so the PostGIS schemas are never compared.

---

### E42 — 🚦 Connection report: `degraded` in the full suite, `connected` alone

**Root cause** Breaker tests leave an open circuit in Redis. The report correctly warns about
it. A second bug: the report read the "last error" evidence before running its own probe.

**Fix** The test fixture clears `zoho:cb:*`; the report re-reads the evidence after probing.

---

## Location hub (2026‑09‑20) — schema `geo`

### E43 — 🏗 Autogenerate produced an empty migration for six new tables

**Root cause** Two independent gates, and both had to be open:

1. `alembic/env.py` imports each module's models explicitly so autogenerate sees them.
   `app.modules.geo` was not in that list, so the tables were not in `Base.metadata`.
2. Alembic derives the schemas to compare from the **database's** schema names. A metadata
   schema that does not exist yet is never scanned, so even after the import nothing was
   detected until `geo` existed.

**Fix** Added the `app.modules.geo.model` import to `env.py` and `"geo"` to `_OWNED_SCHEMAS`;
`CREATE SCHEMA IF NOT EXISTS geo` runs first inside the migration itself, so a fresh database
needs no manual step.

---

### E44 — 🚦 `constraint "fk_places_geocode_call" does not exist` / missing table comments

**Root cause** Two things `create_table` silently drops:

* **`use_alter` foreign keys.** `places → geocode_api_calls` and the reverse are a genuine
  cycle, so both are declared `use_alter=True`. `CREATE TABLE` never emits those, and
  autogenerate still rendered them inline — where they were ignored. `alembic check` then
  reported them as missing forever.
* **Table comments**, but only on the geospatial tables: geoalchemy2's
  `create_geospatial_table` renderer does not carry `comment` through.

**Fix** Three explicit `op.create_foreign_key` calls after every table exists, matching
`op.drop_constraint` calls at the head of `downgrade`, and `op.create_table_comment` for the
four geospatial tables. `alembic check` reports no `geo` drift, and downgrade → upgrade round
trips cleanly.

---

### E45 — 🚦 `text()` bind parameter swallowed by a `::` cast

**Root cause** `text("… WHERE (:tenant_id::bigint IS NULL OR tenant_id = :tenant_id)")`.
SQLAlchemy's bind-parameter scanner does not recognise `:tenant_id` when a `::` cast follows
it, so the first occurrence was left in the SQL literally and Postgres rejected the statement.

**Fix** Build the optional clause in Python instead of casting inside the SQL. `CAST(:x AS
bigint)` also works; a parameter immediately followed by `::` does not.

---

### E46 — 🚦 A 422 became a 500 whenever a validator raised `ValueError` (platform-wide)

**Root cause** Raising `ValueError` is the documented way for a Pydantic validator to reject a
value, and Pydantic puts the exception **object** into `ctx["error"]` of the error list. The
`RequestValidationError` handler passed that list straight to `ORJSONResponse`, which cannot
encode a `ValueError`: `TypeError: Type is not JSON serializable: ValueError`, handled by the
catch-all as an opaque 500. The caller lost the very message that explained the problem.

Not new with the location hub — `organizations.schema._month` has raised `ValueError` since the
fiscal-month fix (E34), so a bad `fiscal_year_start_month` produced a 500 too. The geo
validators (`owner_type`, "exactly one of place / new_place") are simply the first with a test
that asserted the status code.

**Fix** `_serializable_errors` in `app/common/exception/handlers.py` stringifies non-primitive
`ctx` values (and elides binary `input`) before the envelope is built. `msg` already carries
the text, so nothing is lost. Covered by `tests/test_geo_api.py`.

---

## Template for new entries

```
### E<nn> — <emoji> <short title>
**When** <phase / file / date>
**Symptom**
```
<verbatim error text>
```
**Root cause** <what was actually wrong, not what looked wrong>
**Fix** <the change, with file paths>
**Prevention** <the test, guard or doc that stops a recurrence>
```
