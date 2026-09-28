"""Categories & taxonomies business logic.

| Rule | Pre-flight (clean 422) | Database (authoritative) |
|---|---|---|
| taxonomy slug unique per org | ``_unique_taxonomy_slug`` | ``uq_taxonomies_scope_slug`` |
| populated taxonomy cannot change organization | service | ``guard_taxonomy_organization_change`` + composite FKs |
| category shares taxonomy's scope | — | ``fk_categories_taxonomy_scope`` |
| parent shares child's scope | — | ``fk_categories_parent_scope`` |
| parent in same taxonomy | ``_validate_parent`` | ``fk_categories_parent`` |
| parent can have children | ``_validate_parent`` | ``guard_category_scope`` (b) |
| no cycles on move | ``_validate_parent`` ancestor walk | ``guard_category_scope`` (d) |
| nested-set bounds coherent | ``_recompute_tree`` (the only writer) | ``ck_categories_nested_set_bounds`` |
| Zoho-owned fields, the parent and the taxes immutable on linked rows | ``_guard_zoho_owned`` (adapter's ``FIELDS`` + ``parent_id`` + ``tax_preferences``) | — |
| a category's taxes: policy, grants, one per context | ``taxes.assignment_service.replace_assignments`` | ``tax.check_tax_assignment_integrity`` |
| thing exists | ``_validate_entity_type`` (registry) | deferred ``assert_entity_exists`` |
| assignment type whitelisted per taxonomy | ``_validate_whitelist`` | ``check_categorizable_integrity`` |
| assignment shares category's scope/taxonomy | — | ``fk_categorizables_category`` |
| single-valued taxonomy: one category per thing | ``_validate_whitelist`` / replace-set | ``check_categorizable_integrity`` 4–5 |
| no overlapping windows | — | ``check_categorizable_integrity`` 5 (23P01) |
| one primary per (thing, taxonomy) | ``clear_other_primaries`` | ``uq_categorizables_one_primary`` |
| concurrent edits don't clobber | ``_check_version`` | ``RowVersionMixin`` |

Tree bounds are owned by ``tree.py``; the service only holds the per-taxonomy
advisory lock and calls it. Zoho HTTP never happens here — the adapter (phase 3)
drives the engine, which recomputes the tree in its ``post_upsert`` hook.
"""

from __future__ import annotations

import datetime as dt
import re

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.categories import crud, tree
from app.modules.categories.model import Category, Categorizable, Taxonomy, TaxonomyEntityType
from app.modules.categories.schema import (
    CategoryCreate,
    CategoryMove,
    CategoryUpdate,
    CategorizableCreate,
    CategorizableSyncRequest,
    TaxonomyCreate,
    TaxonomyEntityTypesReplace,
    TaxonomyUpdate,
)
from app.modules.entities.scope import CoreRuleError, require_organization
from app.modules.taxes import assignment_service as tax_assignments

logger = structlog.get_logger("app.categories")

#: The ``core.entity_types`` code a category's tax assignments are stored under
#: (registered and opted in by migration ``84daf73430b6``).
TAXABLE_TYPE = "category"

#: Not a column: the category's taxes live in ``tax.tax_assignments``. Fed by Zoho
#: (``category_tax_preferences``), so a linked category's are read-only like its fields.
ZOHO_OWNED_RELATIONS = frozenset({"tax_preferences"})

def _check_version(row, seen: int, label: str) -> None:
    if row.row_version != seen:
        raise ConflictError(
            f"{label} changed since you loaded it (version {seen} → {row.row_version}); reload and retry",
            data={"current_row_version": row.row_version},
        )


def _stringify(values: dict) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


def _metadata_key(values: dict) -> dict:
    """The API field ``metadata`` maps to the model attribute ``metadata_``."""
    if "metadata" in values:
        values["metadata_"] = values.pop("metadata")
    return values


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.strip().lower()).strip("-")


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


async def _unique_taxonomy_slug(
    db: AsyncSession, organization_id: int, name: str, *, exclude_id: int | None = None,
) -> str:
    base = _slugify(name)[:180] or "taxonomy"
    candidate, n = base, 2
    while True:
        existing = await crud.find_taxonomy_by_slug(db, organization_id, candidate)
        if existing is None or existing.id == exclude_id:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


async def _unique_category_slug(
    db: AsyncSession, taxonomy_id: int, name: str, *, exclude_id: int | None = None,
) -> str:
    base = _slugify(name)[:180] or "category"
    candidate, n = base, 2
    while True:
        existing = await crud.find_category_by_slug(db, taxonomy_id, candidate, exclude_id=exclude_id)
        if existing is None:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


async def _lock_tree(db: AsyncSession, tenant_id: int, taxonomy_id: int) -> None:
    key = f"category_tree:{tenant_id}:{taxonomy_id}"
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


async def _recompute_tree(db: AsyncSession, taxonomy: Taxonomy) -> None:
    """The ONLY writer of the tree bounds — full recompute under the tree lock."""
    await _lock_tree(db, taxonomy.tenant_id, taxonomy.id)
    rows = await crud.list_categories_in_taxonomy(db, taxonomy.id)
    try:
        tree.recompute_bounds(rows)
    except tree.TreeError as exc:
        raise CoreRuleError(str(exc)) from exc
    await db.flush()


def _is_zoho_linked(row) -> bool:
    return getattr(row, "zoho_id", None) is not None


def _guard_zoho_owned(row, changes: dict) -> None:
    """Refuse a local edit to a column Zoho feeds (edit it in Zoho instead).

    The owned set is the adapter's, derived from its field map plus ``parent_id``
    — the hierarchy is Zoho's, and the sync re-links it on every re-apply, so a
    local move would be silently undone. Imported lazily: the adapter imports
    this package's model and crud, so a module-level import would be a cycle.
    """
    if not _is_zoho_linked(row):
        return
    from app.modules.categories.zoho.spec import ZOHO_OWNED_CATEGORY_FIELDS

    blocked = sorted(set(changes) & (ZOHO_OWNED_CATEGORY_FIELDS | ZOHO_OWNED_RELATIONS))
    if blocked:
        raise CoreRuleError(
            f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} owned by Zoho for this category "
            f"(zoho_id {row.zoho_id}); change {'it' if len(blocked) == 1 else 'them'} in Zoho — the next sync "
            "brings it here",
            data={"zoho_owned": blocked},
        )


# ── taxonomy ─────────────────────────────────────────────────────────────────

async def list_taxonomies(
    db: AsyncSession, *, q: str | None = None, status: str | None = None,
    page: int = 1, page_size: int = 100,
) -> list[Taxonomy]:
    return await crud.list_taxonomies(db, q=q, status=status, page=page, page_size=page_size)


async def get_taxonomy(db: AsyncSession, ref: str) -> Taxonomy:
    row = await crud.get_taxonomy(db, ref)
    if row is None:
        raise NotFoundError(f"Taxonomy '{ref}' not found")
    return row


async def create_taxonomy(db: AsyncSession, body: TaxonomyCreate, *, actor_id: int | None = None) -> Taxonomy:
    organization_id = await require_organization(db)
    values = _stringify(body.model_dump(exclude_none=True))
    values["name"] = body.name.strip()
    slug = values.get("slug") or await _unique_taxonomy_slug(db, organization_id, body.name)
    if await crud.find_taxonomy_by_slug(db, organization_id, slug) is not None:
        raise ConflictError(f"A taxonomy with slug '{slug}' already exists for this organization")
    row = await crud.create_taxonomy(db, {
        **values,
        "slug": slug,
        "organization_id": organization_id,
    })
    await record_activity(
        db, action="taxonomy_created", actor_id=actor_id, subject_type="Taxonomy",
        subject_id=str(row.uuid), changes={"after": {"slug": row.slug, "name": row.name}},
    )
    logger.info("taxonomy.created", taxonomy_id=row.id, organization_id=organization_id)
    return await crud.get_taxonomy(db, str(row.uuid)) or row


async def update_taxonomy(
    db: AsyncSession, ref: str, body: TaxonomyUpdate, *, actor_id: int | None = None,
) -> Taxonomy:
    row = await get_taxonomy(db, ref)
    _check_version(row, body.row_version, f"Taxonomy '{row.slug}'")
    changes = _stringify(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    if changes.get("slug") and changes["slug"] != row.slug:
        if await crud.find_taxonomy_by_slug(db, row.organization_id, changes["slug"]) is not None:
            raise ConflictError(f"A taxonomy with slug '{changes['slug']}' already exists for this organization")
    for field, value in changes.items():
        setattr(row, field, value)
    await db.flush()
    await record_activity(
        db, action="taxonomy_updated", actor_id=actor_id, subject_type="Taxonomy",
        subject_id=str(row.uuid), changes={"after": {k: str(v) for k, v in changes.items()}},
    )
    return await crud.get_taxonomy(db, str(row.uuid)) or row


async def delete_taxonomy(
    db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    row = await get_taxonomy(db, ref)
    live = await crud.list_categories(db, taxonomy_id=row.id, page_size=1)
    if live:
        raise ConflictError(
            f"Taxonomy '{row.slug}' still has categories; delete or move them first",
            data={"hint": "GET /api/categories?taxonomy_id=…"},
        )
    for whitelist in await crud.list_entity_types(db, row.id):
        whitelist.soft_delete(reason=f"taxonomy {row.uuid} deleted: {reason}", by=actor_id)
    row.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="taxonomy_deleted", actor_id=actor_id, subject_type="Taxonomy",
        subject_id=str(row.uuid), context={"reason": reason},
    )


async def list_taxonomy_entity_types(db: AsyncSession, ref: str) -> list[TaxonomyEntityType]:
    row = await get_taxonomy(db, ref)
    return await crud.list_entity_types(db, row.id)


async def replace_taxonomy_entity_types(
    db: AsyncSession, ref: str, body: TaxonomyEntityTypesReplace, *, actor_id: int | None = None,
) -> list[TaxonomyEntityType]:
    row = await get_taxonomy(db, ref)
    desired = {item.entity_type_code: item.allows_multiple for item in body.entity_types}
    if desired:
        known = await crud.known_entity_type_codes(db, list(desired))
        missing = sorted(set(desired) - known)
        if missing:
            raise CoreRuleError(
                f"Unknown entity type code(s): {', '.join(missing)}",
                data={"hint": "GET /api/entities/types lists the registered codes"},
            )
    existing = {r.entity_type_code: r for r in await crud.list_entity_types(db, row.id)}
    for code, current in existing.items():
        if code not in desired:
            current.soft_delete(reason=f"removed from taxonomy {row.uuid} whitelist", by=actor_id)
    for code, allows_multiple in desired.items():
        current = existing.get(code)
        if current is not None:
            current.allows_multiple = allows_multiple
        else:
            stale = await crud.get_entity_type_row(db, row.id, code, include_deleted=True)
            if stale is not None:
                stale.deleted_at = None
                stale.deleted_by = None
                stale.deleted_reason = None
                stale.allows_multiple = allows_multiple
            else:
                await crud.create_taxonomy_entity_type(db, {
                    "taxonomy_id": row.id,
                    "entity_type_code": code,
                    "allows_multiple": allows_multiple,
                    "organization_id": row.organization_id,
                })
    await db.flush()
    await record_activity(
        db, action="taxonomy_entity_types_replaced", actor_id=actor_id, subject_type="Taxonomy",
        subject_id=str(row.uuid), changes={"after": {"entity_types": sorted(desired)}},
    )
    return await crud.list_entity_types(db, row.id)


# ── category ─────────────────────────────────────────────────────────────────

async def list_categories(
    db: AsyncSession, *, taxonomy_id: int | None = None, parent_id: int | None = None,
    is_active: bool | None = None, q: str | None = None, view: str | None = None,
    page: int = 1, page_size: int = 200,
) -> list[Category]:
    return await crud.list_categories(db, taxonomy_id=taxonomy_id, parent_id=parent_id,
                                      is_active=is_active, q=q, view=view,
                                      page=page, page_size=page_size)


async def get_category(db: AsyncSession, ref: str) -> Category:
    row = await crud.get_category(db, ref)
    if row is None:
        raise NotFoundError(f"Category '{ref}' not found")
    return row


async def _validate_parent(
    db: AsyncSession, *, category: Category | None, parent_id: int, taxonomy_id: int,
) -> Category:
    parent = await crud.get_category_by_id(db, parent_id)
    if parent is None:
        raise NotFoundError(f"Parent category {parent_id} not found")
    if parent.taxonomy_id != taxonomy_id:
        raise CoreRuleError("The parent category belongs to a different taxonomy")
    if not parent.can_have_children:
        raise CoreRuleError(f"Category {parent_id} is not allowed to have children")
    if category is not None and parent.id == category.id:
        raise CoreRuleError("A category cannot be its own parent")
    if category is not None:
        nodes = await crud.list_categories_in_taxonomy(db, taxonomy_id)
        ancestors = {a.id for a in tree.ancestors_of(nodes, parent)}
        if category.id in ancestors or parent.id == category.id:
            raise CoreRuleError("Moving the category there would create a cycle")
    return parent


async def create_category(db: AsyncSession, body: CategoryCreate, *, actor_id: int | None = None) -> Category:
    organization_id = await require_organization(db)
    taxonomy = await crud.get_taxonomy_by_id(db, body.taxonomy_id)
    if taxonomy is None:
        raise NotFoundError(f"Taxonomy {body.taxonomy_id} not found")
    if taxonomy.organization_id != organization_id:
        raise CoreRuleError("The taxonomy belongs to a different organization")

    values = _metadata_key(_stringify(body.model_dump(exclude_none=True)))
    values.pop("tax_preferences", None)            # not a column — written through tax.tax_assignments below
    values["name"] = body.name.strip()
    tax_specs = await tax_assignments.specs_from_items(db, body.tax_preferences or [])
    if body.code and await crud.find_category_by_code(db, taxonomy.id, body.code) is not None:
        raise ConflictError(f"Category code '{body.code}' already exists in this taxonomy")
    if body.parent_id:
        await _validate_parent(db, category=None, parent_id=body.parent_id, taxonomy_id=taxonomy.id)
    values["slug"] = body.slug or await _unique_category_slug(db, taxonomy.id, body.name)
    if await crud.find_category_by_slug(db, taxonomy.id, values["slug"]) is not None:
        raise ConflictError(f"Category slug '{values['slug']}' already exists in this taxonomy")

    row = await crud.create_category(db, {
        **values,
        "organization_id": organization_id,
        "taxonomy_slug": taxonomy.slug,
        "is_root": body.parent_id is None,
    })
    await _recompute_tree(db, taxonomy)
    if tax_specs:
        await tax_assignments.replace_assignments(
            db, TAXABLE_TYPE, row.id, tax_specs, organization_id=organization_id, actor_id=actor_id,
        )
    await record_activity(
        db, action="category_created", actor_id=actor_id, subject_type="Category",
        subject_id=str(row.uuid),
        changes={"after": {"name": row.name, "taxonomy_id": taxonomy.id, "parent_id": row.parent_id}},
    )
    logger.info("category.created", category_id=row.id, taxonomy_id=taxonomy.id)
    return await crud.get_category(db, str(row.uuid)) or row


async def update_category(
    db: AsyncSession, ref: str, body: CategoryUpdate, *, actor_id: int | None = None,
) -> Category:
    row = await get_category(db, ref)
    _check_version(row, body.row_version, f"Category '{row.name}'")
    changes = _metadata_key(_stringify(body.model_dump(exclude_unset=True, exclude={"row_version"})))
    # ``tax_preferences`` present (even empty) = replace this category's local taxes.
    replace_taxes = "tax_preferences" in body.model_fields_set
    changes.pop("tax_preferences", None)
    _guard_zoho_owned(row, {**changes, **({"tax_preferences": None} if replace_taxes else {})})
    tax_specs = await tax_assignments.specs_from_items(db, body.tax_preferences or []) if replace_taxes else []

    if changes.get("name"):
        changes["name"] = changes["name"].strip()
    if changes.get("code") and await crud.find_category_by_code(
        db, row.taxonomy_id, changes["code"], exclude_id=row.id
    ) is not None:
        raise ConflictError(f"Category code '{changes['code']}' already exists in this taxonomy")
    if changes.get("slug") and await crud.find_category_by_slug(
        db, row.taxonomy_id, changes["slug"], exclude_id=row.id
    ) is not None:
        raise ConflictError(f"Category slug '{changes['slug']}' already exists in this taxonomy")

    # ``path`` is built from slugs, so a rename moves the whole subtree's path.
    tree_affected = bool({"parent_id", "position", "slug"} & set(changes))
    if "parent_id" in changes and changes["parent_id"] is not None:
        await _validate_parent(db, category=row, parent_id=changes["parent_id"], taxonomy_id=row.taxonomy_id)

    for field, value in changes.items():
        setattr(row, field, value)
    if "parent_id" in changes:
        row.is_root = changes["parent_id"] is None
    await db.flush()

    if tree_affected:
        taxonomy = await crud.get_taxonomy_by_id(db, row.taxonomy_id)
        if taxonomy is not None:
            await _recompute_tree(db, taxonomy)
    if replace_taxes:
        await tax_assignments.replace_assignments(
            db, TAXABLE_TYPE, row.id, tax_specs, organization_id=row.organization_id, actor_id=actor_id,
        )
        # `get_category` above loaded this row's taxes into the identity map; the re-read below would
        # hand back that stale collection unless it is expired first.
        db.expire(row, ["tax_assignments"])
    await record_activity(
        db, action="category_updated", actor_id=actor_id, subject_type="Category",
        subject_id=str(row.uuid), changes={"after": {k: str(v) for k, v in changes.items()}},
    )
    return await crud.get_category(db, str(row.uuid)) or row


async def move_category(
    db: AsyncSession, ref: str, body: CategoryMove, *, actor_id: int | None = None,
) -> Category:
    row = await get_category(db, ref)
    _check_version(row, body.row_version, f"Category '{row.name}'")
    _guard_zoho_owned(row, {"parent_id": body.parent_id})
    taxonomy = await crud.get_taxonomy_by_id(db, row.taxonomy_id)
    if taxonomy is None:
        raise NotFoundError(f"Taxonomy {row.taxonomy_id} not found")
    if body.parent_id is not None:
        await _validate_parent(db, category=row, parent_id=body.parent_id, taxonomy_id=row.taxonomy_id)
    if body.parent_id == row.parent_id:
        return row
    previous_parent = row.parent_id
    row.parent_id = body.parent_id
    row.is_root = body.parent_id is None
    await db.flush()
    await _recompute_tree(db, taxonomy)
    await record_activity(
        db, action="category_moved", actor_id=actor_id, subject_type="Category",
        subject_id=str(row.uuid),
        changes={"before": {"parent_id": previous_parent}, "after": {"parent_id": row.parent_id}},
    )
    logger.info("category.moved", category_id=row.id, parent_id=row.parent_id)
    return await crud.get_category(db, str(row.uuid)) or row


async def delete_category(
    db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    row = await get_category(db, ref)
    if await crud.count_live_children(db, row.id):
        raise ConflictError(
            f"Category '{row.name}' still has live children; re-parent or delete them first",
            data={"hint": "GET /api/categories?parent_id=…"},
        )
    taxonomy = await crud.get_taxonomy_by_id(db, row.taxonomy_id)
    for link in await crud.list_categorizables(db, category_id=row.id):
        link.soft_delete(reason=f"category {row.uuid} deleted: {reason}", by=actor_id)
    await tax_assignments.remove_owner_assignments(
        db, TAXABLE_TYPE, row.id, reason=f"category {row.uuid} deleted: {reason}", actor_id=actor_id,
    )
    row.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    if taxonomy is not None:
        await _recompute_tree(db, taxonomy)
    await record_activity(
        db, action="category_deleted", actor_id=actor_id, subject_type="Category",
        subject_id=str(row.uuid), context={"reason": reason},
    )


def to_zoho_payload(category: Category, *, create: bool = False) -> dict:
    """This category as the body Zoho's ``/categories`` endpoints expect.

    The outbound half of the anti-corruption layer; the shared command-outbox
    transport (not built platform-wide yet — see ``currencies/zoho/spec.py``)
    will call it. ``parent_category_id`` is intentionally omitted: the local
    ``parent_id`` is our PK, and the transport resolves the Zoho parent id
    through the crosswalk. Raises ``TranslationError`` when a required create
    argument is missing, so a payload Zoho would reject costs nothing.
    """
    from app.modules.categories.zoho.spec import CATEGORIES_TRANSLATOR
    from app.modules.sync.translation import WriteIntent

    return CATEGORIES_TRANSLATOR.encode(
        category, intent=WriteIntent.CREATE if create else WriteIntent.UPDATE
    )


# ── categorizable ────────────────────────────────────────────────────────────
async def list_categorizables(
    db: AsyncSession, *, category_id: int | None = None, categorizable_type: str | None = None,
    categorizable_id: int | None = None, taxonomy_id: int | None = None,
    valid_at: dt.datetime | None = None, page: int = 1, page_size: int = 200,
) -> list[Categorizable]:
    return await crud.list_categorizables(
        db, category_id=category_id, categorizable_type=categorizable_type,
        categorizable_id=categorizable_id, taxonomy_id=taxonomy_id,
        valid_at=valid_at, page=page, page_size=page_size,
    )


async def _validate_entity_type(db: AsyncSession, entity_type: str) -> None:
    if not await crud.known_entity_type_codes(db, [entity_type]):
        raise CoreRuleError(
            f"'{entity_type}' is not a registered entity type",
            data={"hint": "GET /api/entities/types lists the registered codes"},
        )


async def _validate_whitelist(db: AsyncSession, taxonomy_id: int, entity_type: str) -> bool:
    """Return ``allows_multiple``; reject a type the taxonomy does not accept."""
    whitelist = await crud.get_entity_type_row(db, taxonomy_id, entity_type)
    if whitelist is None:
        raise CoreRuleError(f"Entity type '{entity_type}' is not whitelisted for taxonomy {taxonomy_id}")
    return bool(whitelist.allows_multiple) if whitelist.allows_multiple is not None else True


async def _category_for_assignment(db: AsyncSession, category_id: int, taxonomy_id: int) -> Category:
    category = await crud.get_category_by_id(db, category_id)
    if category is None:
        raise NotFoundError(f"Category {category_id} not found")
    if category.taxonomy_id != taxonomy_id:
        raise CoreRuleError("The category belongs to a different taxonomy")
    return category


async def assign_category(
    db: AsyncSession, body: CategorizableCreate, *, actor_id: int | None = None,
) -> Categorizable:
    await _validate_entity_type(db, body.categorizable_type)
    category = await crud.get_category_by_id(db, body.category_id)
    if category is None:
        raise NotFoundError(f"Category {body.category_id} not found")
    await _validate_whitelist(db, category.taxonomy_id, body.categorizable_type)

    values = _metadata_key(_stringify(body.model_dump(exclude_none=True)))
    # The one-primary-per-(thing, taxonomy) unique index is IMMEDIATE, so the
    # old primary must be cleared and flushed before the new row is inserted.
    if body.is_primary:
        await crud.clear_other_primaries(
            db, taxonomy_id=category.taxonomy_id, categorizable_type=body.categorizable_type,
            categorizable_id=body.categorizable_id,
        )
        await db.flush()
    row = await crud.create_categorizable(db, {
        **values,
        "taxonomy_id": category.taxonomy_id,
        "organization_id": category.organization_id,
    })
    await record_activity(
        db, action="category_assigned", actor_id=actor_id, subject_type=body.categorizable_type,
        subject_id=str(body.categorizable_id),
        changes={"after": {"category_id": category.id, "taxonomy_id": category.taxonomy_id}},
    )
    return row


async def sync_categorizables(
    db: AsyncSession, body: CategorizableSyncRequest, *, actor_id: int | None = None,
) -> list[Categorizable]:
    """Replace the live assignment set of one thing within one taxonomy."""
    await _validate_entity_type(db, body.categorizable_type)
    taxonomy = await crud.get_taxonomy_by_id(db, body.taxonomy_id)
    if taxonomy is None:
        raise NotFoundError(f"Taxonomy {body.taxonomy_id} not found")
    await _validate_whitelist(db, body.taxonomy_id, body.categorizable_type)

    for item in body.items:
        await _category_for_assignment(db, item.category_id, body.taxonomy_id)

    existing = await crud.list_live_assignments(
        db, categorizable_type=body.categorizable_type,
        categorizable_id=body.categorizable_id, taxonomy_id=body.taxonomy_id,
    )
    kept: dict[int, Categorizable] = {}
    for current in existing:
        if any(item.category_id == current.category_id for item in body.items):
            kept[current.category_id] = current
        else:
            current.soft_delete(reason="replaced by categorizables sync", by=actor_id)

    # The one-primary unique index is immediate: clear any old primary (and
    # flush) before inserting the replacement primary below.
    if any(item.is_primary for item in body.items):
        await crud.clear_other_primaries(
            db, taxonomy_id=body.taxonomy_id, categorizable_type=body.categorizable_type,
            categorizable_id=body.categorizable_id,
        )
        await db.flush()

    for item in body.items:
        current = kept.get(item.category_id)
        if current is not None:
            current.sort_order = item.sort_order
            current.is_primary = item.is_primary
            current.is_featured = item.is_featured
            if item.metadata is not None:
                current.metadata_ = item.metadata
            continue
        values: dict = {
            "category_id": item.category_id,
            "taxonomy_id": body.taxonomy_id,
            "categorizable_type": body.categorizable_type,
            "categorizable_id": body.categorizable_id,
            "organization_id": taxonomy.organization_id,
            "sort_order": item.sort_order,
            "is_primary": item.is_primary,
            "is_featured": item.is_featured,
            "metadata_": item.metadata,
        }
        # valid_from is NOT NULL with a server default — omit rather than send NULL.
        if item.valid_from is not None:
            values["valid_from"] = item.valid_from
        if item.valid_to is not None:
            values["valid_to"] = item.valid_to
        await crud.create_categorizable(db, values)
    await db.flush()
    await record_activity(
        db, action="categories_synced", actor_id=actor_id, subject_type=body.categorizable_type,
        subject_id=str(body.categorizable_id),
        changes={"after": {"taxonomy_id": body.taxonomy_id,
                           "category_ids": [item.category_id for item in body.items]}},
    )
    return await crud.list_live_assignments(
        db, categorizable_type=body.categorizable_type,
        categorizable_id=body.categorizable_id, taxonomy_id=body.taxonomy_id,
    )


async def unassign_categorizable(
    db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    row = await crud.get_categorizable(db, ref)
    if row is None:
        raise NotFoundError(f"Assignment '{ref}' not found")
    row.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="category_unassigned", actor_id=actor_id, subject_type=row.categorizable_type,
        subject_id=str(row.categorizable_id), context={"reason": reason},
    )
