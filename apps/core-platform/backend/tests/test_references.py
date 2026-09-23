"""Reference resolution — a source id in a payload becomes a local foreign key.

Two layers, tested at the seam the design puts between them:

* **policy** (`app/modules/sync/references.py`) is pure — which misses fetch,
  stub, defer or are ignored, and what the budget does when it runs out. Tested
  as a decision table, with no database, no broker and no Zoho.
* **mechanism** (the drain lane, `app/modules/sync/reconcile.py`) writes the FK
  a DEFER left NULL. Tested against the real crosswalk.
"""


from app.modules.sync.contract import OnMissing, ReferenceRule
from app.modules.sync.references import (
    Budget,
    external_ids_for,
    pairs_in_page,
    plan_references,
    read_path,
)

TAX = ReferenceRule(attr="tax_id", module="taxes", fk="tax_component_id",
                    external_fk="zoho_tax_id", on_missing=OnMissing.DEFER)
CURRENCY = ReferenceRule(attr="currency_id", module="currencies", fk="currency_id",
                         on_missing=OnMissing.FETCH)
ITEMS = ReferenceRule(attr="line_items.item_id", module="items", fk="item_ids",
                      on_missing=OnMissing.STUB, many=True)


# ── reading ids out of a payload ────────────────────────────────────────────

def test_a_dotted_path_reads_through_nesting_and_lists():
    payload = {"a": {"b": "1"}, "line_items": [{"item_id": "x"}, {"item_id": "y"}, {}]}
    assert read_path(payload, "a.b") == "1"
    assert read_path(payload, "line_items.item_id") == ["x", "y"]
    assert read_path(payload, "a.missing") is None
    assert read_path(payload, "nope.at.all") is None


def test_ids_are_normalised_to_strings_and_deduplicated():
    """Zoho sends ids as strings, integers and empty strings for 'not set'; the
    crosswalk stores text. Normalising here keeps every comparison downstream
    string-to-string."""
    rule = ReferenceRule(attr="ids", module="taxes", fk="fk", many=True)
    assert external_ids_for(rule, {"ids": ["7", 7, "", None, " 8 "]}) == ["7", "8"]
    assert external_ids_for(rule, {"ids": []}) == []
    assert external_ids_for(rule, {}) == []


def test_a_single_valued_rule_takes_the_first_of_an_unexpected_list():
    """A mapping bug, not data to drop: the record still applies, and the
    surprise is logged rather than silently truncating to nothing."""
    assert external_ids_for(TAX, {"tax_id": ["1", "2"]}) == ["1"]


def test_the_page_surface_is_computed_once_and_deduplicated():
    """This is what makes the lookup ONE query: every rule, every record, one
    ordered set of (module, external_id) pairs."""
    payloads = [
        {"tax_id": "9", "currency_id": "1"},
        {"tax_id": "9", "currency_id": "2"},          # the same tax again
        {"line_items": [{"item_id": "i1"}, {"item_id": "i2"}]},
    ]
    pairs = pairs_in_page([TAX, CURRENCY, ITEMS], payloads)
    assert pairs == [("taxes", "9"), ("currencies", "1"), ("currencies", "2"),
                     ("items", "i1"), ("items", "i2")]


# ── the policy table ────────────────────────────────────────────────────────

def test_a_hit_sets_the_fk_and_keeps_the_external_id():
    """The external id is written on a HIT too — it costs nothing and lets a
    reconciler repair a bad linkage later without re-reading the source."""
    plan = plan_references([TAX], {"tax_id": "9"}, {("taxes", "9"): 42}, budget=Budget(limit=5))
    assert plan.values == {"zoho_tax_id": "9", "tax_component_id": 42}
    assert not plan.fetch and not plan.stub and not plan.defer


def test_a_miss_follows_the_declared_policy():
    budget = Budget(limit=5)
    resolved = {("taxes", "9"): None, ("currencies", "1"): None, ("items", "i1"): None}

    deferred = plan_references([TAX], {"tax_id": "9"}, resolved, budget=budget)
    assert deferred.defer == [(TAX, "9")] and "tax_component_id" not in deferred.values
    assert deferred.values["zoho_tax_id"] == "9"      # ...but the id is kept

    fetched = plan_references([CURRENCY], {"currency_id": "1"}, resolved, budget=budget)
    assert fetched.fetch == [("currencies", "1")]

    stubbed = plan_references([ITEMS], {"line_items": [{"item_id": "i1"}]}, resolved, budget=budget)
    assert stubbed.stub == [("items", "i1")]


def test_null_keeps_only_the_external_id():
    rule = ReferenceRule(attr="tax_id", module="taxes", fk="fk",
                         external_fk="zoho_tax_id", on_missing=OnMissing.NULL)
    plan = plan_references([rule], {"tax_id": "9"}, {("taxes", "9"): None}, budget=Budget(limit=5))
    assert plan.values == {"zoho_tax_id": "9"} and plan.ignored == [("taxes", "9")]


def test_a_many_rule_collects_every_hit_into_a_list():
    resolved = {("items", "i1"): 1, ("items", "i2"): 2}
    plan = plan_references([ITEMS], {"line_items": [{"item_id": "i1"}, {"item_id": "i2"}]},
                           resolved, budget=Budget(limit=5))
    assert plan.values == {"item_ids": [1, 2]}


def test_an_absent_attribute_produces_no_plan_at_all():
    plan = plan_references([TAX, CURRENCY], {"unrelated": 1}, {}, budget=Budget(limit=5))
    assert plan.is_empty


# ── the budget: the difference between "correct" and "ruinous" ──────────────

def test_fetch_degrades_to_stub_once_the_budget_is_spent():
    """"Go fetch it and insert it first" is right per record and catastrophic
    per page. Over budget the record still links — to a provisional row the
    owning module's own sync fills in — instead of spending the run's quota."""
    budget = Budget(limit=2)
    fetched, degraded = [], []
    for n in range(5):
        plan = plan_references([CURRENCY], {"currency_id": str(n)},
                               {("currencies", str(n)): None}, budget=budget)
        fetched += plan.fetch
        degraded += plan.stub

    assert len(fetched) == 2 and len(degraded) == 3
    assert budget.spent == 2 and budget.remaining == 0


def test_a_zero_budget_never_fetches():
    plan = plan_references([CURRENCY], {"currency_id": "1"},
                           {("currencies", "1"): None}, budget=Budget(limit=0))
    assert plan.fetch == [] and plan.stub == [("currencies", "1")]


# ── the drain lane, against the real crosswalk ──────────────────────────────

async def test_the_drain_links_a_waiter_once_its_master_arrives(db, worlds):
    """The end-to-end DEFER loop: a waiter is queued, the master syncs, and the
    reconcile lane writes the foreign key that was left NULL."""
    from sqlalchemy import select

    from app.database.tenancy import tenant_scope
    from app.modules.currencies.model import Currency
    from app.modules.organizations.model import Organization
    from app.modules.sync.crosswalk import upsert_record
    from app.modules.sync.models import LinkState, PendingReference
    from app.modules.sync.reconcile import drain_pending_references

    _, acme, _ = worlds
    tenant_id, org_id = acme.tenant.id, acme.organization.id

    with tenant_scope(tenant_id, org_id):
        currency = Currency(currency_code="AUD", currency_name="Australian Dollar",
                            tenant_id=tenant_id, organization_id=org_id,
                            owner_type="organization", owner_id=org_id)
        db.add(currency)
        await db.flush()

        # The crosswalk row the master's own sync would have written.
        await upsert_record(
            db, tenant_id=tenant_id, source_system="zoho", module="currencies",
            external_id="982000000004012",
            values={"entity_table": "currency.currencies", "entity_id": currency.id,
                    "link_state": LinkState.LINKED, "organization_id": org_id},
        )
        # ...and the waiter a document left behind before that happened.
        db.add(PendingReference(
            tenant_id=tenant_id, organization_id=org_id, source_system="zoho",
            module="currencies", external_id="982000000004012",
            waiting_table="org_management.organizations", waiting_id=acme.organization.id,
            waiting_column="currency_id",
        ))
        await db.flush()

        report = await drain_pending_references(db, tenant_id=tenant_id)

    assert report.scanned == 1 and report.linked == 1 and report.still_missing == 0
    linked = await db.scalar(select(Organization.currency_id)
                             .where(Organization.id == acme.organization.id)
                             .execution_options(all_tenants=True))
    assert linked == currency.id
    assert (await db.scalars(select(PendingReference))).all() == []


async def test_an_unresolvable_waiter_is_kept_and_counted(db, worlds):
    """Not an error — the master may simply not have synced yet. It stays
    queued with attempts incremented, which is the number an operator watches
    instead of silent NULLs."""
    from sqlalchemy import select

    from app.database.tenancy import tenant_scope
    from app.modules.sync.models import PendingReference
    from app.modules.sync.reconcile import drain_pending_references

    _, acme, _ = worlds
    with tenant_scope(acme.tenant.id, acme.organization.id):
        db.add(PendingReference(
            tenant_id=acme.tenant.id, organization_id=acme.organization.id, source_system="zoho",
            module="currencies", external_id="not-synced-yet",
            waiting_table="org_management.organizations", waiting_id=acme.organization.id,
            waiting_column="currency_id",
        ))
        await db.flush()
        report = await drain_pending_references(db, tenant_id=acme.tenant.id)

    assert report.linked == 0 and report.still_missing == 1
    waiter = await db.scalar(select(PendingReference))
    assert waiter is not None and waiter.attempts == 1


async def test_a_waiter_naming_an_unsafe_table_is_skipped_not_executed(db, worlds):
    """The queue is data. The waiting table reaches SQL as an identifier, so it
    passes an allow-list first — a row that fails it is reported, never run."""
    from app.database.tenancy import tenant_scope
    from app.modules.currencies.model import Currency
    from app.modules.sync.crosswalk import upsert_record
    from app.modules.sync.models import LinkState, PendingReference
    from app.modules.sync.reconcile import drain_pending_references

    _, acme, _ = worlds
    tenant_id, org_id = acme.tenant.id, acme.organization.id
    with tenant_scope(tenant_id, org_id):
        currency = Currency(currency_code="SGD", currency_name="Singapore Dollar",
                            tenant_id=tenant_id, organization_id=org_id,
                            owner_type="organization", owner_id=org_id)
        db.add(currency)
        await db.flush()
        await upsert_record(
            db, tenant_id=tenant_id, source_system="zoho", module="currencies",
            external_id="evil", values={"entity_table": "currency.currencies",
                                        "entity_id": currency.id, "link_state": LinkState.LINKED},
        )
        db.add(PendingReference(
            tenant_id=tenant_id, organization_id=org_id, source_system="zoho",
            module="currencies", external_id="evil",
            waiting_table="users; DROP TABLE users--", waiting_id=1, waiting_column="currency_id",
        ))
        await db.flush()
        report = await drain_pending_references(db, tenant_id=tenant_id)

    assert report.skipped == 1 and report.linked == 0
