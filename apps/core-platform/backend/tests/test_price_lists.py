"""Price lists — Zoho price lists (its API: pricebooks), their items and volume brackets.

  * hermetic — the quote arithmetic, the rounding we refuse to guess, the translator on the live
    shapes (``""`` everywhere; Zoho's ``pricebook_*`` keys → our ``price_list_*`` / ``rate`` columns),
    the engine's detail age gate;
  * database — the replace-set projection of Zoho's ``pricebook_items`` (update in place, soft-delete
    what left, never touch children from a list row), the composite scope FKs;
  * API — list / detail / quote under ``/api/price-lists``, organization isolation.

The full Zoho path (real transport, list + undocumented detail, the age gate re-confirming a
list whose timestamp did not move) is ``tests/zoho_core/test_masters_e2e.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.tenancy import tenant_scope
from app.modules.price_lists.errors import PricingError, RoundingNotSupportedError
from app.modules.price_lists.model import PriceList, PriceListItem, PriceListItemBracket
from app.modules.price_lists.service import apply_rounding, compute_price
from app.modules.price_lists.zoho.hooks import REMOVED_REASON, after_price_list_upsert, project_items
from app.modules.price_lists.zoho.spec import PRICE_LISTS_CONFIG, PRICE_LISTS_TRANSLATOR
from app.modules.sync.translation import PayloadShape
from app.modules.zoho.sync.engine import _already_current, _StoredVersion

D = Decimal


def _list(**kw):
    base = {"id": 1, "price_list_type": "per_item", "pricing_scheme": "unit", "percentage": None,
            "is_increase": False, "rounding_type": "no_rounding", "decimal_place": 0, "is_active": True}
    return SimpleNamespace(**{**base, **kw})


# ── hermetic: the quote ───────────────────────────────────────────────────────

def test_a_unit_list_quotes_its_rate_and_falls_back_only_when_told_how():
    entry = SimpleNamespace(rate=D("64.41"), discount=None)
    quote = compute_price(_list(), "i1", D(3), base_rate=None, entry=entry, bracket=None)
    assert (quote.rate, quote.basis) == (D("64.41"), "unit_rate")
    with pytest.raises(PricingError, match="not in this price list"):
        compute_price(_list(), "i2", D(1), base_rate=None, entry=None, bracket=None)
    fallback = compute_price(_list(), "i2", D(1), base_rate=D(70), entry=None, bracket=None)
    assert (fallback.rate, fallback.basis) == (D(70), "base_rate_fallback")


def test_a_volume_list_picks_the_bracket_in_force_and_flags_a_gap():
    entry = SimpleNamespace(rate=None, discount=None)
    bracket = SimpleNamespace(start_quantity=D(10), end_quantity=D(19), rate=D(19), discount=None)
    volume = _list(pricing_scheme="volume")
    inside = compute_price(volume, "i1", D(12), base_rate=None, entry=entry, bracket=bracket)
    assert (inside.rate, inside.basis, inside.between_brackets) == (D(19), "volume_bracket", False)
    gap = compute_price(volume, "i1", D("19.5"), base_rate=None, entry=entry, bracket=bracket)   # 19 < q < 20
    assert gap.between_brackets is True and gap.rate == D(19)
    with pytest.raises(PricingError, match="below this price list's first bracket"):
        compute_price(volume, "i1", D(5), base_rate=None, entry=entry, bracket=None)


def test_a_percentage_list_marks_up_or_down_and_rounds():
    up = _list(price_list_type="fixed_percentage", pricing_scheme=None, percentage=D("35.71"), is_increase=True,
               rounding_type="round_to_dollar")
    assert compute_price(up, "i", D(1), base_rate=D(100), entry=None, bracket=None).rate == D(136)
    down = _list(price_list_type="fixed_percentage", pricing_scheme=None, percentage=D(10), is_increase=False,
                 rounding_type="no_rounding")
    assert compute_price(down, "i", D(1), base_rate=D("19.99"), entry=None, bracket=None).rate == D("17.991000")
    with pytest.raises(PricingError, match="needs the item's base_rate"):
        compute_price(down, "i", D(1), base_rate=None, entry=None, bracket=None)


def test_rounding_is_refused_where_zoho_does_not_document_the_arithmetic():
    assert apply_rounding(D("12.345"), "round_based_on_decimal", 2) == D("12.35")
    assert apply_rounding(D("12.5"), "round_to_dollar", 0) == D(13)
    with pytest.raises(RoundingNotSupportedError):
        apply_rounding(D("12.3"), "round_to_dollar_minus_01", 0)


# ── hermetic: the translator and the spec ─────────────────────────────────────

# Zoho's own list row (its API says "pricebook").
LIST_ROW = {"pricebook_id": "1", "name": "Markup", "description": "", "currency_id": "", "currency_code": "",
            "decimal_place": 0, "is_increase": True, "percentage": 35.71, "pricebook_rate": 35.71,
            "pricebook_type": "fixed_percentage", "pricing_scheme": "", "rounding_type": "round_to_dollar",
            "sales_or_purchase_type": "sales", "status": "inactive", "last_modified_time": "2024-05-04T23:48:16+0530"}


def test_the_translator_maps_zohos_pricebook_keys_onto_price_list_columns():
    listed = PRICE_LISTS_TRANSLATOR.decode(LIST_ROW, shape=PayloadShape.INDEX).values
    assert listed["price_list_type"] == "fixed_percentage" and listed["rate"] == D("35.71")
    assert not any("pricebook" in column for column in listed)                         # no Zoho name leaks
    assert listed["pricing_scheme"] is None and listed["description"] is None          # "" -> NULL
    assert listed["percentage"] == D("35.71") and listed["status"] == "inactive"
    assert "is_default" not in listed                                                  # detail-only: absent, not NULL
    unit = PRICE_LISTS_TRANSLATOR.decode({**LIST_ROW, "pricebook_type": "per_item", "pricing_scheme": "unit",
                                          "percentage": "", "pricebook_rate": ""}, shape=PayloadShape.INDEX).values
    assert unit["percentage"] is None and unit["rate"] is None


def test_the_spec_reads_zohos_endpoint_under_our_name_and_rechecks_daily():
    cfg = PRICE_LISTS_CONFIG
    assert cfg.module == "price_lists" and cfg.contract.entity_table == "pricing.price_lists"
    assert (cfg.endpoint, cfg.zoho_id_attr, cfg.detail_path("7")) == ("/pricebooks", "pricebook_id", "/pricebooks/7")
    assert cfg.detail_required and cfg.index_then_detail and cfg.detail_max_age_minutes == 1440
    assert cfg.modified_since_param is None and cfg.soft_delete_missing


def test_the_age_gate_trusts_a_timestamp_only_while_the_detail_is_fresh():
    record = {"last_modified_time": "2025-05-15T12:23:11+0530"}
    listed = datetime(2025, 5, 15, 6, 53, 11, tzinfo=UTC)
    now = datetime.now(UTC)
    fresh = _StoredVersion(listed, "detail_fetch", False, now - timedelta(hours=2))
    stale = _StoredVersion(listed, "detail_fetch", False, now - timedelta(days=2))
    thin = _StoredVersion(listed, "list:full", False, now)
    assert _already_current(fresh, record) and _already_current(stale, record)          # 0 = trust the timestamp
    assert _already_current(fresh, record, max_age_minutes=1440)
    assert not _already_current(stale, record, max_age_minutes=1440)
    assert not _already_current(_StoredVersion(listed, "detail_fetch", False, None), record, max_age_minutes=60)
    assert not _already_current(thin, record, max_age_minutes=1440)                    # never had the detail


# ── database: the projection ──────────────────────────────────────────────────

UNIT_ITEMS = [
    {"pricebook_item_id": "pi-1", "item_id": "it-1", "name": "Scrub", "can_be_sold": True, "can_be_purchased": True,
     "pricebook_discount": "", "pricebook_rate": 64.41},
    {"pricebook_item_id": "pi-2", "item_id": "it-2", "name": "Gel", "can_be_sold": True, "can_be_purchased": False,
     "pricebook_discount": "5%", "pricebook_rate": 120},
]
VOLUME_ITEMS = [{"item_id": "it-1", "name": "Scrub", "can_be_sold": True, "can_be_purchased": True, "price_brackets": [
    {"pricebook_item_id": "br-1", "start_quantity": 10.0, "end_quantity": 19.0, "pricebook_discount": "",
     "pricebook_rate": 19.0},
    {"pricebook_item_id": "br-2", "start_quantity": 20.0, "end_quantity": "", "pricebook_discount": "",
     "pricebook_rate": 18.0}]}]


async def _make_list(db, world, *, scheme="unit", zoho_id="pl-1", name="Partner") -> PriceList:
    with tenant_scope(world.tenant.id, world.organization.id):
        price_list = PriceList(organization_id=world.organization.id, name=name, price_list_type="per_item",
                               pricing_scheme=scheme, sales_or_purchase_type="sales", zoho_id=zoho_id)
        db.add(price_list)
        await db.flush()
    return price_list


async def test_items_are_replaced_as_a_set_and_what_left_is_soft_deleted(worlds, db):
    _, acme, _ = worlds
    price_list = await _make_list(db, acme)
    with tenant_scope(acme.tenant.id, acme.organization.id):
        counts = await project_items(db, price_list, UNIT_ITEMS)
        assert counts["items_added"] == 2
        first = {i.item_zoho_id: i for i in await db.scalars(select(PriceListItem))}
        assert first["it-2"].discount == "5%" and first["it-1"].discount is None
        assert {i.organization_id for i in first.values()} == {acme.organization.id}

        again = await project_items(db, price_list, UNIT_ITEMS)              # same document: no write at all
        assert not any(again.values())
        versions = {i.id: i.row_version for i in first.values()}

        changed = [{**UNIT_ITEMS[0], "pricebook_rate": 60}]                   # Gel leaves, Scrub reprices
        counts = await project_items(db, price_list, changed)
        assert (counts["items_updated"], counts["items_removed"], counts["items_added"]) == (1, 1, 0)
        live = list(await db.scalars(select(PriceListItem)))
        assert [(i.item_zoho_id, i.rate) for i in live] == [("it-1", D(60))]
        assert live[0].id == first["it-1"].id and live[0].row_version > versions[live[0].id]   # updated in place
        gone = await db.scalar(select(PriceListItem).where(PriceListItem.item_zoho_id == "it-2")
                               .execution_options(include_deleted=True))
        assert gone.deleted_reason == REMOVED_REASON == "zoho:removed_from_price_list"


async def test_brackets_follow_their_ids_and_a_list_row_never_touches_children(worlds, db):
    _, acme, _ = worlds
    price_list = await _make_list(db, acme, scheme="volume")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await project_items(db, price_list, VOLUME_ITEMS)
        brackets = list(await db.scalars(select(PriceListItemBracket).order_by(PriceListItemBracket.position)))
        assert [(b.zoho_id, b.end_quantity) for b in brackets] == [("br-1", D(19)), ("br-2", None)]   # "" = open

        edited = [{**VOLUME_ITEMS[0], "price_brackets": [
            {**VOLUME_ITEMS[0]["price_brackets"][1], "pricebook_rate": 17.5}]}]          # br-1 removed, br-2 repriced
        counts = await project_items(db, price_list, edited)
        assert (counts["brackets_updated"], counts["brackets_removed"]) == (1, 1)
        live = list(await db.scalars(select(PriceListItemBracket)))
        assert [(b.id, b.rate) for b in live] == [(brackets[1].id, D("17.5"))]

        # the index phase applies the LIST row: no pricebook_items key -> children untouched
        await after_price_list_upsert(price_list, {"pricebook_id": "pl-1", "name": "Partner"})
        assert len(list(await db.scalars(select(PriceListItemBracket)))) == 1
        # an explicit empty list is Zoho saying "no items": everything goes
        await after_price_list_upsert(price_list, {"pricebook_id": "pl-1", "pricebook_items": []})
        assert list(await db.scalars(select(PriceListItem))) == []


async def test_a_child_cannot_hang_under_another_organizations_list(tree_world, db):
    _, world = tree_world
    with tenant_scope(world.tenant.id, world.branch_a.id):
        price_list = PriceList(organization_id=world.branch_a.id, name="A's list", price_list_type="per_item",
                               pricing_scheme="unit", sales_or_purchase_type="sales")
        db.add(price_list)
        await db.flush()
    await db.commit()
    with pytest.raises(IntegrityError, match="fk_price_list_items_price_list"):
        with tenant_scope(world.tenant.id, world.branch_b.id):
            db.add(PriceListItem(organization_id=world.branch_b.id, price_list_id=price_list.id, item_zoho_id="x"))
            await db.flush()
    await db.rollback()


# ── API ───────────────────────────────────────────────────────────────────────

async def test_the_api_lists_details_and_quotes_within_the_organization(worlds, db):
    client, acme, globex = worlds
    unit = await _make_list(db, acme)
    volume = await _make_list(db, acme, scheme="volume", zoho_id="pl-2", name="Volume")
    with tenant_scope(acme.tenant.id, acme.organization.id):
        await project_items(db, unit, UNIT_ITEMS)
        await project_items(db, volume, VOLUME_ITEMS)
    await db.commit()
    headers = acme.auth(acme.admin)

    listed = (await client.get("/api/price-lists", headers=headers)).json()["data"]
    assert [(p["name"], p["price_list_type"], p["item_count"]) for p in listed] == [
        ("Partner", "per_item", 2), ("Volume", "per_item", 1)]
    detail = (await client.get(f"/api/price-lists/{volume.uuid}", headers=headers)).json()["data"]
    assert [(b["zoho_id"], b["rate"] is not None) for b in detail["items"][0]["brackets"]] == [
        ("br-1", True), ("br-2", True)]

    quote = (await client.get(f"/api/price-lists/{volume.id}/price?item_id=it-1&quantity=25",
                              headers=headers)).json()["data"]
    assert (D(quote["rate"]), quote["basis"], quote["price_list_id"]) == (D(18), "volume_bracket", volume.id)
    refused = await client.get(f"/api/price-lists/{unit.id}/price?item_id=nope&quantity=1", headers=headers)
    assert refused.status_code == 422 and refused.json()["code"] == "pricing_unavailable"
    fallback = (await client.get(f"/api/price-lists/{unit.id}/price?item_id=nope&quantity=1&base_rate=9",
                                 headers=headers)).json()["data"]
    assert fallback["basis"] == "base_rate_fallback"
    assert (await client.get("/api/pricebooks", headers=headers)).status_code == 404   # the old route is gone

    globex_headers = globex.auth(globex.admin)
    assert (await client.get("/api/price-lists", headers=globex_headers)).json()["data"] == []
    assert (await client.get(f"/api/price-lists/{unit.id}", headers=globex_headers)).status_code == 404
