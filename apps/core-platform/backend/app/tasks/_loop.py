"""One event loop per Celery worker process (ADR‑3).

Why: the stack is asyncpg/redis.asyncio only, and pooled async connections
belong to the loop that opened them. v1 tasks ran ``asyncio.run`` per task,
so each task needed a throwaway NullPool engine, a fresh HTTP client, a
``bind_session_factory`` dance for every singleton that touches Postgres, and
a final ``redis_client.aclose()`` — and still broke whenever a new singleton
forgot one of those steps (ERRORS E06, E23).

Now every task in a process runs on the SAME long-lived loop:

  * the module-level pooled engine (``app.database.db``), ``redis_client``,
    the token manager's credential store and the engine switches are used
    as-is — connections are reused across tasks instead of re-opened;
  * ``run_async(coro)`` is the only entry point for sync Celery tasks.

Rules:
  * **prefork pool only** (the default; ``-P threads/gevent`` would share
    one loop between concurrent tasks). ``worker_process_init`` gives each
    forked child a fresh loop and drops any connection state inherited from
    the parent.
  * A task interrupted mid-flight (e.g. ``SoftTimeLimitExceeded`` raised by a
    signal inside the loop) is **cancelled and awaited** before the exception
    propagates, so its ``finally`` blocks run (rollback, connection return)
    and nothing half-done resumes during the next task.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from contextlib import suppress
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger("app.tasks.loop")

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_pid: int | None = None


def get_loop() -> asyncio.AbstractEventLoop:
    """The process's loop (created lazily; replaced after a fork)."""
    global _loop, _loop_pid
    if _loop is None or _loop.is_closed() or _loop_pid != os.getpid():
        _loop = asyncio.new_event_loop()
        _loop_pid = os.getpid()
        asyncio.set_event_loop(_loop)
    return _loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion on the process loop (sync Celery task → async code)."""
    loop = get_loop()
    if loop.is_running():  # pragma: no cover — a programming error, never a runtime condition
        coro.close()
        raise RuntimeError("run_async() called from inside the running loop; await the coroutine instead")
    task = loop.create_task(coro)
    try:
        return loop.run_until_complete(task)
    except BaseException:
        if not task.done():
            # Interrupted from outside (soft time limit, KeyboardInterrupt):
            # unwind the task properly on its own loop before re-raising.
            task.cancel()
            with suppress(BaseException):
                loop.run_until_complete(task)
        raise
    finally:
        _cancel_strays(loop)


def _cancel_strays(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel fire-and-forget tasks a coroutine left behind (they would run
    during the NEXT task otherwise)."""
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if not pending:
        return
    for stray in pending:
        stray.cancel()
    with suppress(BaseException):
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    logger.warning("tasks.loop.stray_tasks_cancelled", count=len(pending))


def reset_after_fork() -> None:
    """``worker_process_init``: new loop + forget connections inherited from the parent.

    ``dispose(close=False)`` drops the pool's inherited connections without
    closing the parent's sockets (SQLAlchemy's documented fork recipe); the
    Redis pool is simply disconnected lazily by building a fresh pool.
    """
    global _loop, _loop_pid
    _loop, _loop_pid = None, None
    get_loop()

    from app.database.db import engine

    engine.sync_engine.dispose(close=False)

    from app.database.redis import redis_client

    pool = redis_client.connection_pool
    with suppress(Exception):
        pool.reset()      # redis.asyncio ConnectionPool: forget connections, keep settings


def shutdown() -> None:
    """``worker_process_shutdown``: close pooled resources on the loop that owns them."""
    global _loop
    if _loop is None or _loop.is_closed():
        return

    async def _close() -> None:
        from app.database.db import engine
        from app.database.redis import redis_client

        with suppress(Exception):
            await engine.dispose()
        with suppress(Exception):
            await redis_client.aclose()

    with suppress(BaseException):
        _loop.run_until_complete(_close())
    _loop.close()
    _loop = None


__all__ = ["get_loop", "reset_after_fork", "run_async", "shutdown"]
