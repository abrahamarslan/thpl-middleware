# Worker event loop (ADR‑3)

**Status:** ✅ live · **Code:** `app/tasks/_loop.py`, signals in
`app/tasks/celery_app.py`; used by `app/tasks/{zoho_sync,authentik,emails,media}.py` ·
**Tests:** `tests/test_task_loop.py`

---

## 1. Before → after

| | Before (`asyncio.run` per task) | After (one loop per worker process) |
|---|---|---|
| Event loop | new loop for every task | one long-lived loop per forked child |
| Postgres | a throwaway `NullPool` engine per task (a new connection every time) | the module-level **pooled** engine, reused across tasks |
| Redis | `redis_client.aclose()` at the end of every task | pool reused |
| Singletons that read Postgres (token store, switches) | `bind_session_factory(...)` in every task (forgetting one = "attached to a different loop", E06) | used as-is — same as the API process |
| Per-task objects | engine + client | only the task's own HTTP client (Zoho: per-lane priority) |

## 2. How it works

| Piece | What it does |
|---|---|
| `run_async(coro)` | the only way a sync Celery task runs async code: `run_until_complete` on the process loop |
| `worker_process_init` → `reset_after_fork()` | fresh loop in each forked child; `engine.sync_engine.dispose(close=False)` and `redis_client.connection_pool.reset()` drop anything inherited from the parent without closing the parent's sockets |
| `worker_process_shutdown` → `shutdown()` | disposes the engine and closes Redis **on the loop that owns them**, then closes the loop |
| interruption (`SoftTimeLimitExceeded`, `KeyboardInterrupt` raised inside the loop) | the task is **cancelled and awaited** before the exception propagates, so its `finally` blocks run (rollback, connection return), and nothing half-done resumes during the next task |
| stray tasks | fire-and-forget tasks a coroutine left behind are cancelled after each `run_async` (logged `tasks.loop.stray_tasks_cancelled`) |

## 3. Constraints

* **Prefork pool only** (Celery's default, which all compose files use).
  `-P threads` or `gevent` would run concurrent tasks on one loop and is not
  supported.
* Worker DB connections = `CELERY_CONCURRENCY × (DB_POOL_SIZE + DB_MAX_OVERFLOW)`
  at peak. Size Postgres `max_connections` accordingly.
* Code called from a task must `await`, never call `run_async` (a nested call
  raises `RuntimeError`).
* `bind_session_factory` still exists on the token store and switches, for
  tests that inject a session factory.

## 4. Tests

`tests/test_task_loop.py`:
* one loop is shared by every task in a process;
* a "forked" child (different pid) gets a new loop;
* exceptions propagate and the loop stays usable;
* an interrupted task's `finally` runs before the exception surfaces, and no task is left pending;
* stray tasks are cancelled.
