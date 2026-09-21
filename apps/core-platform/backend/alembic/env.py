"""Alembic async migration environment.

The database URL always comes from app settings (env vars), never from
alembic.ini — one source of configuration truth.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.conf import settings
from app.database.db import Base

# Import every module's models so autogenerate sees all tables
from app.modules.system import model as _system_model  # noqa: F401
from app.modules.activity import model as _activity_model  # noqa: F401
from app.modules.documents import model as _documents_model  # noqa: F401
from app.modules.emails import model as _emails_model  # noqa: F401
from app.modules.favorites import model as _favorites_model  # noqa: F401
from app.modules.files import model as _files_model  # noqa: F401
from app.modules.media import model as _media_model  # noqa: F401
from app.modules.tags import model as _tags_model  # noqa: F401
from app.modules.users import model as _users_model  # noqa: F401
from app.modules.zoho import model as _zoho_model  # noqa: F401
from app.modules.zoho.control import models as _zoho_control_models  # noqa: F401
from app.modules.tenants import model as _tenants_model  # noqa: F401
from app.modules.organizations import model as _organizations_model  # noqa: F401
from app.modules.roles import model as _roles_model  # noqa: F401
from app.modules.currencies import model as _currencies_model  # noqa: F401
from app.modules.zoho_currencies import model as _zoho_currencies_model  # noqa: F401
from app.modules.taxes import model as _zoho_taxes_model  # noqa: F401
from app.modules.locations import model as _zoho_locations_model  # noqa: F401
from app.modules.zoho_users import model as _zoho_users_model  # noqa: F401
from app.modules.zoho.sync import models as _zoho_sync_models  # noqa: F401
from app.modules.sync import models as _sync_models  # noqa: F401
from app.modules.geo import model as _geo_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# Tables owned by Postgres EXTENSIONS — never managed by our migrations.
# geoalchemy2's include_object covers spatial_ref_sys but NOT the
# postgis_topology tables, which once leaked DROPs into the baseline.
_EXTENSION_TABLES = {"layer", "topology", "spatial_ref_sys"}


#: Partitioned parents whose child partitions are created at runtime (by the
#: Zoho retention task) — autogenerate must neither drop nor recreate them.
#: ``sync_records`` partitions are per-source and created by migration, but they
#: are still children and must never be compared as standalone tables.
_PARTITIONED_PARENTS = ("zoho_sync_events", "sync_records", "sync_payloads")


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in _EXTENSION_TABLES:
        return False
    if reflected and any(name.startswith(f"{parent}_") for parent in _PARTITIONED_PARENTS):
        return False                     # zoho_sync_events_default, zoho_sync_events_p20260918, …
    if (
        type_ == "index"
        and reflected
        and getattr(getattr(obj, "table", None), "name", "").startswith(_PARTITIONED_PARENTS)
        and getattr(obj.table, "name", "") not in _PARTITIONED_PARENTS
    ):
        return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


#: Schemas our migrations own. `include_schemas=True` is needed for the tenancy
#: tables in org_management; everything else (topology, tiger, …) belongs to
#: PostGIS extensions and is never compared.
_OWNED_SCHEMAS = {None, "public", "org_management", "geo", "currency", "sync"}


def _include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in _OWNED_SCHEMAS
    return True


# geoalchemy2 alembic helpers: skip PostGIS-internal tables, render Geography
# types and spatial indexes correctly in autogenerate.
_GEO_KW = {
    "include_object": _include_object,
    "include_name": _include_name,
    "include_schemas": True,
    "process_revision_directives": alembic_helpers.writer,
    "render_item": alembic_helpers.render_item,
}


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        **_GEO_KW,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, **_GEO_KW)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
