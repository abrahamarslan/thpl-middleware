"""Shared test fixtures.

Environment: unit tests are hermetic; integration tests (marked by the
fixtures they request) need Postgres/Redis. Defaults point at the local
scratch containers (ports 55432/56379); override via env:

    docker run -d --rm --name thm-scratch-pg -p 55432:5432 \
        -e POSTGRES_USER=app -e POSTGRES_PASS=app_password \
        -e POSTGRES_DBNAME=app_db \
        -e POSTGRES_MULTIPLE_EXTENSIONS=postgis,hstore,postgis_topology,pgrouting,pg_trgm,pgcrypto \
        kartoza/postgis:18-3.6--v2025.11.24
    docker run -d --rm --name thm-scratch-redis -p 56379:6379 redis:7.4-alpine
    alembic upgrade head   # with DATABASE_URL pointing at the scratch DB

Tests requesting `db` / redis are SKIPPED automatically when the services
are unreachable, so `pytest` stays green on a bare checkout.
"""

import os

# Must run BEFORE any `app.` import — settings are cached at import time.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:app_password@localhost:55432/app_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:56379/2")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:56379/3")
os.environ.setdefault("ZOHO_ORGANIZATION_ID", "10234695")

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.conf import settings  # noqa: E402

#: Tables integration tests write to — truncated between tests for isolation.
_TEST_TABLES = (
    "zoho_queue_logs",
    "zoho_sync_stats",
    "zoho_organizations",
    "taggables",
    "tags",
    "email_events",
    "email_links",
    "emails",
    "documents",
    "media",
)


@pytest.fixture
async def db():
    """Loop-scoped session against the migrated integration database."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("integration database unavailable (see tests/conftest.py)")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
        # Hard isolation: truncate everything the tests touch.
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {', '.join(_TEST_TABLES)} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def redis_available():
    """Skip when Redis is unreachable; reset pooled connections afterwards
    (each test runs its own event loop — stale pooled connections from a
    previous loop would otherwise break the next test)."""
    from app.database.redis import redis_client

    try:
        await redis_client.ping()
    except Exception:
        pytest.skip("integration redis unavailable (see tests/conftest.py)")
    yield redis_client
    await redis_client.aclose()
