"""Media queries for Celery tasks.

Synchronous signatures — task bodies stay plain sync code, like the storage
clients — but the database work runs on the worker process's single event loop
(``run_async``, app/tasks/_loop.py, ADR-3) through the same pooled asyncpg
engine as everything else. There is deliberately no second, psycopg-based
engine: this project ships asyncpg only, and a private sync pool per worker
process would just be another set of connections to size and recycle.

Raw SQL on purpose:

* ``set_conversion`` is ``conversions || jsonb_build_object(k, v)`` — a shallow
  merge of ONE top-level key — which is what makes N parallel ``gen_variant``
  subtasks safe on the same row: each only ever touches its own key, and no
  task reads-modifies-writes the whole map.
* Workers run in system scope (no tenant context), and every statement is
  keyed by the media uuid, so tenant filtering has nothing to add.
* ``row_version`` is NOT bumped: these are background bookkeeping writes, and
  bumping would make an in-flight API update of the same row (soft-deleting a
  replaced avatar while its variants are still generating) fail as stale.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from app.database.db import async_session_factory
from app.tasks._loop import run_async


#: A row still unfinished this long after upload is not re-queued again: it is
#: marked ``partial_failure`` instead, so a poison image cannot loop forever.
STUCK_GIVE_UP_AFTER = timedelta(hours=24)


def _session_factory():
    """Indirection so tests can point the worker at a NullPool session."""
    return async_session_factory


def _run(coro_fn):
    async def _inner():
        async with _session_factory()() as session:
            result = await coro_fn(session)
            await session.commit()
            return result

    return run_async(_inner())


async def merge_conversion(session, media_id: str, variant: str, value: dict) -> None:
    """``conversions[variant] = value`` and NOTHING else, atomically in SQL.

    Two workers finishing different variants of the same media at the same time
    each merge their own key; neither reads the map first, so neither can
    overwrite the other's result. (Also a module-level coroutine so tests can
    run it from several connections at once — Celery itself never runs two
    tasks on one process's loop, the concurrency is between PROCESSES.)
    """
    await session.execute(
        text("""UPDATE media.items
                SET conversions = conversions || jsonb_build_object(CAST(:k AS text), CAST(:v AS jsonb)),
                    updated_at = now()
                WHERE uuid = CAST(:id AS uuid)"""),
        {"id": media_id, "k": variant, "v": json.dumps(value)},
    )


class MediaRepoWorker:
    def get(self, media_id: str) -> dict[str, Any] | None:
        """A LIVE media row (soft-deleted → None), as a plain dict."""
        async def q(s):
            row = (await s.execute(
                text("""SELECT id, uuid::text AS uuid, disk, visibility, file_name, conversions
                        FROM media.items WHERE uuid = CAST(:id AS uuid) AND deleted_at IS NULL"""),
                {"id": media_id},
            )).mappings().first()
            return dict(row) if row else None

        return _run(q)

    def set_conversion(self, media_id: str, variant: str, value: dict) -> None:
        _run(lambda s: merge_conversion(s, media_id, variant, value))

    def mark_processing(self, media_id: str) -> None:
        """pending → processing (idempotent; never regresses a finished status)."""
        async def q(s):
            await s.execute(
                text("""UPDATE media.items SET status = 'processing', updated_at = now()
                        WHERE uuid = CAST(:id AS uuid) AND status = 'pending'"""),
                {"id": media_id},
            )

        _run(q)

    def set_status(self, media_id: str, status: str) -> None:
        async def q(s):
            await s.execute(
                text("UPDATE media.items SET status = :s, updated_at = now() WHERE uuid = CAST(:id AS uuid)"),
                {"s": status, "id": media_id},
            )

        _run(q)

    def list_stuck(self, idle_for: timedelta, *, limit: int = 100) -> list[dict[str, Any]]:
        """Live rows still ``pending``/``processing`` whose last write is older than
        ``idle_for``. Every variant step bumps ``updated_at``, so a row that is
        genuinely being worked on never shows up here."""
        async def q(s):
            rows = (await s.execute(
                text("""SELECT id, uuid::text AS uuid, collection, conversions,
                               (created_at < now() - make_interval(secs => :max_age)) AS too_old
                        FROM media.items
                        WHERE deleted_at IS NULL AND status IN ('pending', 'processing')
                          AND updated_at < now() - make_interval(secs => :idle)
                        ORDER BY updated_at LIMIT :n"""),
                {"idle": idle_for.total_seconds(), "max_age": STUCK_GIVE_UP_AFTER.total_seconds(), "n": limit},
            )).mappings().all()
            return [dict(r) for r in rows]

        return _run(q)

    def touch(self, media_id: str) -> None:
        """Bump ``updated_at`` so a re-queued row is not picked up again next tick."""
        async def q(s):
            await s.execute(
                text("UPDATE media.items SET updated_at = now() WHERE uuid = CAST(:id AS uuid)"), {"id": media_id},
            )

        _run(q)

    def list_stale_deleted(self, older_than: timedelta, *, limit: int = 200) -> list[dict[str, Any]]:
        """Soft-deleted rows past the grace window. The cutoff is computed by the
        database, so worker/DB clock skew cannot shorten the grace period."""
        async def q(s):
            rows = (await s.execute(
                text("""SELECT id, uuid::text AS uuid, disk, visibility, file_name, conversions
                        FROM media.items
                        WHERE deleted_at IS NOT NULL
                          AND deleted_at < now() - make_interval(secs => :secs)
                        ORDER BY deleted_at LIMIT :n"""),
                {"secs": older_than.total_seconds(), "n": limit},
            )).mappings().all()
            return [dict(r) for r in rows]

        return _run(q)

    def hard_delete(self, pk: int) -> None:
        async def q(s):
            await s.execute(text("DELETE FROM media.items WHERE id = :id"), {"id": pk})

        _run(q)


media_repo_worker = MediaRepoWorker()
