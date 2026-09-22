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
from app.database.tenancy import clear_default_cache  # noqa: E402
from tests.tenancy_fixtures import worlds  # noqa: E402,F401 — shared tenancy API fixture

#: Tables integration tests write to — truncated between tests for isolation.
_TEST_TABLES = (
    "zoho_oauth_credentials",
    "zoho_sync_runs",
    "zoho_sync_cursors",
    "zoho_quota_days",
    "zoho_sync_events",
    # zoho_retention_policies is NOT truncated: its defaults are seeded by the
    # migration; tests that change a policy restore it themselves.
    "setting_audit_logs",
    "setting_values",
    "setting_definitions",
    "setting_groups",
    "system_modules",
    "zoho_queue_logs",
    "zoho_sync_stats",
    # Sync crosswalk: waiters before history before the crosswalk itself.
    "sync.pending_references",
    "sync.sync_payloads",
    "sync.sync_records",
    # Location hub: links before places before boundaries (FK order).
    "geo.place_relationships",
    "geo.place_links",
    "geo.geofences",
    "geo.geocode_api_calls",
    "geo.places",
    "geo.admin_boundaries",
    # Currency: rates before the currency (FK order).
    "currency.exchange_rates",
    "currency.currencies",
    # Tax: children before the component (composite FK order).
    "tax.tax_group_members",
    "tax.org_default_tax_preferences",
    "tax.organization_tax_components",
    "tax.tax_components",
    "tax.tax_exemptions",
    "tax.gst_treatment_types",
    # Core master data: children before parents (FK order). core.entity_types is
    # reference data seeded by the migration — NOT truncated.
    "core.entity_aliases",
    "core.manufacturer_identifiers",
    "core.brand_manufacturers",
    "core.brands",
    "core.manufacturers",
    "org_management.organizations",   # CASCADE: every tenant table references it
    "roles",
    # Users & telemetry
    "user_location_pings",
    "user_live_locations",
    # Hubs / fleet partners / vehicles
    "driving_licenses",
    "vehicle_compliance_documents",
    "vehicles",
    "hubs",
    "fleet_partners",
    # Person compliance (DPDP / KYC / BGV) — data_retention_schedules is global reference data
    "kyc_audit_logs",
    "data_principal_requests",
    "consent_records",
    "bgv_check_results",
    "background_verifications",
    "aadhaar_verifications",
    "pan_verifications",
    "liveness_verifications",
    "medical_fitness_certificates",
    "training_certifications",
    "kyc_profiles",
    # HR / employment / payouts
    "gig_worker_fy_stats",
    "gig_worker_registrations",
    "employment_records",
    "bank_accounts",
    "zoho_locations",
    "zoho_users",
    "taggables",
    "tags",
    "email_events",
    "email_links",
    "emails",
    "password_reset_tokens",
    "login_otp_tokens",
    "activity_logs",
    # Documents: trail, links and files before the document (FK order). document_types
    # is reference data seeded by the migration — NOT truncated.
    "document_verification_logs",
    "document_links",
    "document_files",
    "documents",
    "media",
    "user_profiles",
    "country_timezones",
    "timezones",
    "countries",
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
            # Tenants created by tests go; the migration's DEFAULT tenant stays
            # (rows written without a tenant context land in it).
            await conn.execute(
                text("DELETE FROM org_management.tenants WHERE tenant_code <> :code"),
                {"code": settings.DEFAULT_TENANT_CODE},
            )
            await _restore_default_organization(conn)
        # The restored organization is a NEW row with a NEW id, and
        # `tenancy.default_organization_id_sync` caches (tenant, code) -> id for
        # the life of the process. Without this, the next test's flush stamps a
        # freshly-created row with the id of an organization the truncate
        # removed, and fails on fk_<table>_tenant_org.
        clear_default_cache()
    await engine.dispose()


async def _restore_default_organization(conn) -> None:
    """Give the default tenant its organization back after the truncate.

    A migrated database always has one — migration ``fdbf62102e86`` creates a
    ``DEFAULT-HQ`` for every tenant that lacks one, because ``users`` and
    ``roles`` became organization-scoped. ``org_management.organizations`` is in
    ``_TEST_TABLES`` (it must be: CASCADE from it is what clears every tenant
    table), so the truncate takes that row with it and leaves the database in a
    state no migration ever produces — one where nothing can be written at all.

    Restoring it here keeps the *production* rule strict: `app/database/scope.py`
    refuses a write it cannot place rather than inventing an organization, and
    that refusal stays testable (``test_a_tenant_without_an_organization_is_told_so``
    builds a bare tenant of its own).
    """
    await conn.execute(
        text("""
            INSERT INTO org_management.organizations
                (uuid, tenant_id, parent_id, org_code, legal_name, org_type, hierarchy_path,
                 depth, status, is_verified, row_version, app_version, app_metadata,
                 created_at, updated_at)
            SELECT gen_random_uuid(), t.id, NULL, :code, 'Default HQ', 'solo',
                   '/' || gen_random_uuid()::text || '/', 0, 'active', false, 1, '0.1.0',
                   '{}'::jsonb, now(), now()
            FROM org_management.tenants t
            WHERE t.tenant_code = :tenant_code
              AND NOT EXISTS (SELECT 1 FROM org_management.organizations o
                              WHERE o.tenant_id = t.id AND o.deleted_at IS NULL)
        """),
        {"code": settings.DEFAULT_ORGANIZATION_CODE or "DEFAULT-HQ",
         "tenant_code": settings.DEFAULT_TENANT_CODE},
    )


@pytest.fixture(autouse=True)
def _no_leaked_tenant_context():
    """Tenancy context variables must never leak between tests."""
    from app.database.tenancy import SYSTEM, _actor, _organization, _tenant

    tokens = (_tenant.set(None), _organization.set(None), _actor.set(SYSTEM))
    yield
    _actor.reset(tokens[2])
    _organization.reset(tokens[1])
    _tenant.reset(tokens[0])


@pytest.fixture(autouse=True)
def _reset_zoho_config_cache():
    """The config resolver caches overrides per process; tables are truncated
    between tests, so a cached override must never leak into the next test."""
    from app.modules.zoho.control.config import zoho_config

    zoho_config.invalidate()
    yield
    zoho_config.invalidate()


@pytest.fixture
async def redis_available():
    """Skip when Redis is unreachable; reset pooled connections afterwards
    (each test runs its own event loop — stale pooled connections from a
    previous loop would otherwise break the next test)."""
    from app.database.redis import redis_client

    # A test WITHOUT this fixture may have used the client too (the engine
    # reads the config version), leaving connections bound to its closed loop.
    try:
        await redis_client.aclose()
    except Exception:  # noqa: BLE001 — stale transports can fail to close; they are dropped anyway
        pass
    try:
        await redis_client.ping()
    except Exception:
        pytest.skip("integration redis unavailable (see tests/conftest.py)")
    yield redis_client
    await redis_client.aclose()
