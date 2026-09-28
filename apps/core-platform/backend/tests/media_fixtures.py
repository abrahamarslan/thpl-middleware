"""Fixtures for the media integration tests (registered from conftest.py).

``media_env`` gives a test everything the media stack touches, isolated:

* local disk under ``tmp_path`` (never the real media volume), provider caches reset;
* NullPool database sessions for the two code paths that open their OWN session —
  the public router and the Celery-side repository — because the module-level
  pooled engine holds connections bound to a previous test's event loop;
* a recorder in place of the Celery broker, and a fresh worker event loop.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.conf import settings
from app.modules.media import public_api, repository_worker, service, storage, storage_sync
from app.tasks import _loop
from app.tasks.media import finalize_conversions, gen_variant


@pytest.fixture
def media_env(tmp_path, monkeypatch, db):
    base = tmp_path / "library"
    monkeypatch.setattr(settings, "MEDIA_STORAGE_DRIVER", "local")
    monkeypatch.setattr(settings, "MEDIA_LOCAL_BASE_PATH", str(base))
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE_URL", "https://media.test")
    storage._provider_cache.clear()
    storage_sync._provider_cache.clear()

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(public_api, "async_session_factory", factory)
    monkeypatch.setattr(repository_worker, "_session_factory", lambda: factory)

    dispatched: list[tuple[str, dict]] = []
    monkeypatch.setattr(service, "_dispatch_conversions", lambda media_id, conv: dispatched.append((media_id, conv)))

    _loop._loop, _loop._loop_pid = None, None
    yield SimpleNamespace(base=base, dispatched=dispatched)

    loop = _loop._loop
    if loop is not None and not loop.is_closed():
        loop.close()
    _loop._loop, _loop._loop_pid = None, None
    asyncio.set_event_loop(None)
    storage._provider_cache.clear()
    storage_sync._provider_cache.clear()


async def run_pipeline(media_id: str, conversions: dict) -> list[dict]:
    """What Celery does after an upload: every variant, then the chord callback.

    Runs in a worker thread because the tasks are synchronous and drive the
    database through their own event loop (``run_async``).
    """
    def _run() -> list[dict]:
        results = [gen_variant.apply(args=(media_id, name, spec), throw=True).get() for name, spec in conversions.items()]
        finalize_conversions.apply(args=(results,), kwargs={"media_id": media_id}, throw=True).get()
        return results

    return await asyncio.to_thread(_run)
