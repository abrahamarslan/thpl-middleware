"""Apply hooks for the Zoho Books category adapter.

``pre_upsert`` is synchronous and has no DB access (the engine calls it before
the row exists), so it only does payload-shape work: a slug fallback when
Zoho's required ``url`` arrives blank. The per-organization ``zoho`` taxonomy is
provisioned by the database trigger ``core.fill_category_default_taxonomy()``,
which fires BEFORE INSERT when ``taxonomy_id`` is NULL — the only place that can
query before the NOT NULL / composite-FK checks.

``post_upsert`` is async and owns the two cross-row jobs the field map cannot
express: resolving ``parent_category_id`` through the crosswalk (Zoho's ``-1``
sentinel means "no parent"), and recomputing the affected taxonomy's nested-set
bounds — the one writer of ``_lft``/``_rgt``/``depth``/``path`` — and turning the
detail document's ``category_tax_preferences`` into ``tax.tax_assignments`` (below).

Why the parent is resolved HERE and not by a declarative ``ReferenceRule``: the
engine resolves a page's references in one query *before* any row of that page
is written, and a category's parent is usually a row of the same page. A rule
would defer every child whose parent arrives alongside it. Hooks run after the
page is flushed and its crosswalk rows linked, when the parent is resolvable.
What a hook cannot resolve (the parent failed to apply, or comes in a later
page) goes on the same ``sync.pending_references`` queue a rule would have used,
so it is visible and the reconcile lane can link it — instead of the category
staying a silent orphan root, which nothing re-examines (an unchanged row never
reaches this hook again).
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_object_session

from app.modules.categories import crud, tree
from app.modules.categories.model import Category
from app.modules.sync.crosswalk import resolve_many
from app.modules.sync.models import PendingReference
from app.modules.taxes import assignment_service as tax_assignments

logger = structlog.get_logger("app.categories.zoho")

#: The taxes a category carries are stored under this ``core.entity_types`` code.
_TAXABLE_TYPE = "category"
_SPECIFICATIONS = {"inter", "intra"}

#: Zoho's sentinels for "this category is a root".
_ROOT_IDS = {None, "", "-1", -1}

_WORD = re.compile(r"[^a-z0-9]+")

_TABLE = "core.categories"
_COLUMN = "parent_id"


def _slugify(value: str) -> str:
    return _WORD.sub("-", value.strip().lower()).strip("-")


def normalise_category(payload: dict, values: dict[str, Any]) -> dict[str, Any]:
    """Slug fallback only — never overwrite a value Zoho actually sent."""
    if not values.get("slug") and values.get("name"):
        values["slug"] = _slugify(values["name"])[:180]
    return values


async def after_category_upsert(row: Category, payload: dict) -> None:
    db = async_object_session(row)
    if db is None or row.id is None:
        return
    await _link_parent(db, row, payload)
    await _recompute_tree(db, row)
    await _sync_tax_preferences(db, row, payload)


async def _link_parent(db, row: Category, payload: dict) -> None:
    external = payload.get("parent_category_id")
    if external in _ROOT_IDS or (isinstance(external, str) and not external.strip()):
        if row.parent_id is not None:
            row.parent_id = None
        await _clear_waiter(db, row)
        return
    external = str(external).strip()

    result = await db.execute(resolve_many(
        tenant_id=row.tenant_id, source_system="zoho", pairs=[("categories", external)],
    ))
    linked = result.first()
    if linked is None or linked.entity_table != _TABLE or linked.entity_id is None:
        await _defer_parent(db, row, external)
        return
    if linked.entity_id == row.id:
        return
    parent = await crud.get_category_by_id(db, linked.entity_id)
    if parent is None or parent.taxonomy_id != row.taxonomy_id:
        logger.warning("categories.zoho.parent_skipped", category_id=row.id, parent_zoho_id=external,
                       reason="parent missing or in another taxonomy")
        return
    if row.parent_id != parent.id:
        row.parent_id = parent.id
    await _clear_waiter(db, row)


async def _defer_parent(db, row: Category, external: str) -> None:
    """Queue the unresolved parent for the reconcile lane (idempotent)."""
    logger.warning("categories.zoho.parent_pending", category_id=row.id, parent_zoho_id=external,
                   action="queued on sync.pending_references; `zoho.cli reconcile` links it")
    await db.execute(
        pg_insert(PendingReference).values(
            tenant_id=row.tenant_id, organization_id=row.organization_id,
            source_system="zoho", module="categories", external_id=external,
            waiting_table=_TABLE, waiting_id=row.id, waiting_column=_COLUMN,
        ).on_conflict_do_nothing(constraint="uq_pending_references_waiter")
    )


async def _clear_waiter(db, row: Category) -> None:
    """The parent is now resolved (or gone): a stale waiter would re-link it."""
    await db.execute(
        delete(PendingReference).where(
            PendingReference.tenant_id == row.tenant_id,
            PendingReference.waiting_table == _TABLE,
            PendingReference.waiting_id == row.id,
            PendingReference.waiting_column == _COLUMN,
        )
    )


async def _sync_tax_preferences(db, row: Category, payload: dict) -> None:
    """``category_tax_preferences`` → the category's Zoho-sourced tax assignments.

    Only the DETAIL document carries the array; a thin list row says nothing about
    taxes, so its absence must not clear them. Zoho names each tax by its own id, which
    resolves through the crosswalk to a ``tax.tax_components`` row (a leaf tax and a tax
    group share one id namespace and both land in module ``taxes``). A tax that is not
    synced yet becomes a *pending* assignment: it waits on ``sync.pending_references``
    and the reconcile lane links it — the category is never left silently untaxed.

    A rule violation (two taxes for one context, the class opted out) is logged and
    skipped: one category's bad tax data must not fail the page.
    """
    preferences = payload.get("category_tax_preferences")
    if not isinstance(preferences, list):
        return
    wanted = [(str(p["tax_id"]).strip(), str(p.get("tax_specification") or "").strip().lower())
              for p in preferences if isinstance(p, dict) and p.get("tax_id")]
    resolved: dict[str, int] = {}
    if wanted:
        rows = await db.execute(resolve_many(
            tenant_id=row.tenant_id, source_system="zoho",
            pairs=[(module, tax_id) for tax_id, _ in wanted for module in ("taxes", "tax_groups")],
        ))
        for _module, external_id, entity_table, entity_id, _state in rows:
            if entity_id is not None and entity_table == "tax.tax_components":
                resolved[external_id] = entity_id
    specs = [
        tax_assignments.AssignmentSpec(
            tax_component_id=resolved.get(tax_id),
            external_ref=None if tax_id in resolved else tax_id,
            tax_specification=specification if specification in _SPECIFICATIONS else None,
            position=index,
        )
        for index, (tax_id, specification) in enumerate(wanted)
    ]
    try:
        await tax_assignments.replace_assignments(
            db, _TAXABLE_TYPE, row.id, specs, source_system="zoho", organization_id=row.organization_id,
        )
    except tax_assignments.TaxRuleError as exc:
        logger.warning("categories.zoho.tax_preferences_skipped", category_id=row.id, error=str(exc.msg))


async def _recompute_tree(db, row: Category) -> None:
    """Idempotent full recompute under the per-taxonomy advisory lock."""
    key = f"category_tree:{row.tenant_id}:{row.taxonomy_id}"
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    rows = await crud.list_categories_in_taxonomy(db, row.taxonomy_id)
    try:
        tree.recompute_bounds(rows)
    except tree.TreeError as exc:
        logger.warning("categories.zoho.tree_error", taxonomy_id=row.taxonomy_id, error=str(exc))
        return
    await db.flush()


__all__ = ["after_category_upsert", "normalise_category"]
