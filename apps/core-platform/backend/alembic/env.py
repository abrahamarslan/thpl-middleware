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
from app.modules.zoho.organizations import model as _zoho_organizations_model  # noqa: F401
from app.modules.zoho.sync import models as _zoho_sync_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# Tables owned by Postgres EXTENSIONS — never managed by our migrations.
# geoalchemy2's include_object covers spatial_ref_sys but NOT the
# postgis_topology tables, which once leaked DROPs into the baseline.
_EXTENSION_TABLES = {"layer", "topology", "spatial_ref_sys"}


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in _EXTENSION_TABLES:
        return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


# geoalchemy2 alembic helpers: skip PostGIS-internal tables, render Geography
# types and spatial indexes correctly in autogenerate.
_GEO_KW = {
    "include_object": _include_object,
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
