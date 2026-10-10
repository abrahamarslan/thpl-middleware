"""The Celery worker must be able to map every model before its first ORM query.

The API imports every router (and so every model) through ``app.main``; a worker
imports only what its task modules reach. ``app.tasks.documents`` loads
``documents.model`` — whose tenant/organization foreign keys name tables no
worker import ever loaded — so the first ORM query in any task raised
``NoReferencedTableError`` and ``planner_tick`` (hence every scheduled Zoho sync)
failed on every tick.

This must run in a CLEAN interpreter: inside pytest the whole app is already
imported by ``conftest`` and the bug cannot show.
"""

import pathlib
import subprocess
import sys
import textwrap

BACKEND = pathlib.Path(__file__).resolve().parents[1]

_BOOT = textwrap.dedent("""
    import sys

    from celery.signals import worker_init
    from sqlalchemy.orm import configure_mappers

    from app.tasks.celery_app import celery_app

    celery_app.loader.import_default_modules()   # what `celery worker` imports at boot
    worker_init.send(sender=None)                # the signal the worker fires before forking
    configure_mappers()                          # what the first ORM query does
    print("MAPPERS_OK", sorted({m.split(".")[2] for m in sys.modules
                                if m.startswith("app.modules.") and m.endswith(".model")}))
""")


def test_a_worker_boots_with_every_model_mapped():
    result = subprocess.run([sys.executable, "-c", _BOOT], cwd=BACKEND, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0 and "MAPPERS_OK" in result.stdout, (
        result.stdout[-1500:] + result.stderr[-2500:]
    )
    # the models the failure was about are all there
    assert "tenants" in result.stdout and "organizations" in result.stdout and "categories" in result.stdout


_CLI_BOOT = textwrap.dedent("""
    from sqlalchemy.orm import configure_mappers

    from app.database.db import Base
    from app.modules.zoho import cli
    from app.modules.zoho.sync.registry import sync_registry

    sync_registry.all()            # what `cli sync` imports: the adapters
    cli._register_every_model()    # what `cli.main` does first
    configure_mappers()
    # a contact person's FK into users is what failed per record (2026-10-10)
    assert "users" in Base.metadata.tables and "party.contact_persons" in Base.metadata.tables
    print("CLI_MAPPERS_OK")
""")


def test_the_zoho_cli_maps_every_model_before_syncing():
    """The Zoho CLI twin of the worker test: `cli sync parties` used to fail on every contact person."""
    result = subprocess.run([sys.executable, "-c", _CLI_BOOT], cwd=BACKEND, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0 and "CLI_MAPPERS_OK" in result.stdout, (
        result.stdout[-1500:] + result.stderr[-2500:]
    )
