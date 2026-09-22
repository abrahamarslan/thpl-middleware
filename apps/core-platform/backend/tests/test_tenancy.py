"""Tenancy core: stamping, the automatic tenant filter, cross-tenant guards,
composite FKs, optimistic locking, and the table-class conformance check."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.core.conf import settings
from app.database.db import Base
from app.database.tenancy import Actor, TenancyError, clear_default_cache, tenant_scope
from app.modules.organizations.model import Organization
from app.modules.tags.model import Tag
from app.modules.tenants.model import Tenant


async def make_tenant(db, code: str) -> Tenant:
    tenant = Tenant(tenant_code=code, name=f"Tenant {code}", primary_contact_email=f"ops@{code.lower()}.example")
    db.add(tenant)
    await db.flush()
    return tenant


async def default_tenant(db) -> Tenant:
    return await db.scalar(select(Tenant).where(Tenant.tenant_code == settings.DEFAULT_TENANT_CODE))


def tag(label: str, **kw) -> Tag:
    return Tag(name={"en": label}, slug={"en": label.lower()}, **kw)


# ── stamping ────────────────────────────────────────────────────────────────

async def test_rows_without_a_context_go_to_the_default_tenant_stamped_as_system(db):
    clear_default_cache()
    row = tag("Urgent")
    db.add(row)
    await db.flush()
    assert row.tenant_id == (await default_tenant(db)).id
    assert row.created_by is None and row.created_by_name == "system"
    assert row.app_version == settings.VERSION and row.row_version == 1 and row.status == "active"


async def test_actor_and_tenant_come_from_the_context(db):
    acme = await make_tenant(db, "ACME")
    with tenant_scope(acme.id, actor=Actor(42, "Asha Rao")):
        row = tag("Mine")
        db.add(row)
        await db.flush()
        assert (row.tenant_id, row.created_by, row.created_by_name) == (acme.id, 42, "Asha Rao")
        row.order_column = 3
        await db.flush()
        assert (row.updated_by, row.updated_by_name) == (42, "Asha Rao") and row.row_version == 2

    # A system write has no user: it must not overwrite the pair with half an attribution.
    with tenant_scope(acme.id, actor=Actor(None, "system:zoho-sync")):
        row.order_column = 4
        await db.flush()
    assert (row.updated_by, row.updated_by_name) == (42, "Asha Rao") and row.row_version == 3


# ── the read filter ─────────────────────────────────────────────────────────

async def test_queries_see_only_the_current_tenant(db):
    acme, globex = await make_tenant(db, "ACME"), await make_tenant(db, "GLOBEX")
    db.add_all([tag("A1", tenant_id=acme.id), tag("A2", tenant_id=acme.id), tag("G1", tenant_id=globex.id)])
    await db.flush()

    with tenant_scope(acme.id):
        names = sorted(t.name["en"] for t in (await db.scalars(select(Tag))).all())
        assert names == ["A1", "A2"]
        globex_id = (await db.scalars(select(Tag.id).where(Tag.name["en"].astext == "G1")
                                      .execution_options(all_tenants=True))).one()
        assert await db.scalar(select(Tag).where(Tag.id == globex_id)) is None    # by id: still invisible
        everyone = (await db.scalars(select(Tag).execution_options(all_tenants=True))).all()
        assert len(everyone) == 3                                  # platform escape hatch

    with tenant_scope(globex.id):
        assert [t.name["en"] for t in (await db.scalars(select(Tag))).all()] == ["G1"]

    assert len((await db.scalars(select(Tag))).all()) == 3         # system scope: no filter


# ── guards ──────────────────────────────────────────────────────────────────

async def test_cannot_write_into_another_tenant(db):
    acme, globex = await make_tenant(db, "ACME"), await make_tenant(db, "GLOBEX")
    with tenant_scope(acme.id):
        db.add(tag("Sneaky", tenant_id=globex.id))
        with pytest.raises(TenancyError):
            await db.flush()
    await db.rollback()


async def test_the_database_refuses_another_tenants_organization(db):
    acme, globex = await make_tenant(db, "ACME"), await make_tenant(db, "GLOBEX")
    with tenant_scope(globex.id):
        globex_org = Organization(org_code="G-HQ", legal_name="Globex HQ", tenant_id=globex.id)
        db.add(globex_org)
        await db.flush()
    db.add(tag("Crossed", tenant_id=acme.id, organization_id=globex_org.id))
    with pytest.raises(IntegrityError, match="fk_tags_tenant_org"):
        await db.flush()
    await db.rollback()


async def test_optimistic_locking_rejects_a_stale_update(db):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    row = tag("Shared")
    db.add(row)
    await db.commit()

    other = async_sessionmaker(db.bind, expire_on_commit=False)()
    try:
        theirs = await other.get(Tag, row.id)
        theirs.order_column = 7
        await other.commit()                                        # row_version 1 → 2
    finally:
        await other.close()

    row.order_column = 9                                            # we still hold version 1
    with pytest.raises(StaleDataError):
        await db.flush()
    await db.rollback()


async def test_soft_delete_records_who_and_why(db):
    acme = await make_tenant(db, "ACME")
    with tenant_scope(acme.id, actor=Actor(7, "Ops")):
        org = Organization(org_code="A-HQ", legal_name="Acme HQ")
        db.add(org)
        await db.flush()
        org.soft_delete(reason="duplicate")
        await db.flush()
    assert (org.deleted_by, org.deleted_reason) == (7, "duplicate") and org.deleted_at is not None


# ── conformance: every table is exactly one class ───────────────────────────

ENTITY_COLUMNS = {"tenant_id", "organization_id", "status", "is_verified", "created_by", "created_by_name",
                  "updated_by", "updated_by_name", "row_version", "app_version", "app_metadata",
                  "deleted_at", "deleted_reason"}
LEDGER_COLUMNS = {"tenant_id", "organization_id", "app_version", "app_metadata"}
#: Tables that cannot belong to a tenant — each with its reason.
GLOBAL_TABLES = {
    "org_management.tenants": "the tenancy root itself",
    "countries": "ISO reference data shared by every tenant",
    "timezones": "IANA reference data",
    "country_timezones": "reference join table",
    "system_modules": "settings catalog (tenant values live in setting_values' TENANT context)",
    "setting_groups": "settings catalog",
    "setting_definitions": "settings catalog",
    "setting_values": "context-scoped (GLOBAL / TENANT / USER) by design",
    "setting_audit_logs": "audit of the context-scoped settings",
    "zoho_retention_policies": "platform-wide retention policy",
    "data_retention_schedules": (
        "application data-retention rules (DPDP) — one authoritative rule per data category for "
        "every tenant; reference data like countries, unrelated to zoho_retention_policies"
    ),
    "document_types": "platform-wide catalog of document kinds (AADHAAR, DRIVING_LICENSE, …) — reference "
                      "data like countries; a per-tenant catalog would need tenant_id and a new code uniqueness",
    "core.entity_types": "platform-wide catalogue of polymorphic entity type codes (brand, manufacturer, …)",
    "tax.gst_treatment_types": (
        "CBIC-defined GST treatment vocabulary (business_gst, consumer, overseas, …), identical for "
        "every tenant — reference data like countries; provenance is the nullable owner_type/owner_id pair"
    ),
    "geo.admin_boundaries": (
        "administrative reference geometry (states, districts, PIN codes) — not one tenant's "
        "data, and a per-tenant copy would duplicate multi-megabyte polygons. Tenant-drawn "
        "areas are geo.geofences, which IS tenant-scoped"
    ),
}
DEACTIVATABLE = {
    "users", "org_management.organizations", "tax.tax_components",
    "geo.places", "geo.place_links", "geo.geofences", "documents",
}
#: The organization tree IS the organization: parent_id + fk_organizations_parent replace organization_id.
SELF_SCOPED = {"org_management.organizations": "parent_id"}


def test_every_table_is_entity_ledger_or_an_explained_global():
    import app.main  # noqa: F401 — import every module's models

    problems = []
    for table in Base.metadata.sorted_tables:
        name = table.fullname
        cols = set(table.c.keys())
        if name in SELF_SCOPED:
            cols |= {"organization_id"} if SELF_SCOPED[name] in cols else set()
        if name in GLOBAL_TABLES:
            if "tenant_id" in cols and name != "org_management.tenants":
                problems.append(f"{name} is listed GLOBAL but has tenant_id")
            continue
        if not LEDGER_COLUMNS <= cols:
            problems.append(f"{name}: missing {sorted(LEDGER_COLUMNS - cols)} (not in GLOBAL_TABLES either)")
            continue
        if "row_version" in cols and not ENTITY_COLUMNS <= cols:
            problems.append(f"{name}: looks like an entity but misses {sorted(ENTITY_COLUMNS - cols)}")
        if name in DEACTIVATABLE and not {"deactivation_date", "deactivation_reason", "deactivated_by"} <= cols:
            problems.append(f"{name}: missing the deactivation columns")
    assert problems == []


async def test_the_default_tenant_exists_and_can_sign_in(db):
    tenant = await default_tenant(db)
    assert tenant is not None and tenant.status == "active"
    is_active = (await db.execute(text(
        "SELECT status IN ('trial','active') FROM org_management.tenants WHERE tenant_code = :c"),
        {"c": settings.DEFAULT_TENANT_CODE})).scalar()
    assert is_active is True
