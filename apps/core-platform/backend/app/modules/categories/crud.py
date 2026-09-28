"""Data access for ``core`` taxonomies / categories / assignments.

Lists use ``load_only`` (Slim); the detail reads use ``selectinload`` for the
tree whitelist and the shared tags/documents relationships (Fat). Every model
relationship is ``lazy="raise"``, so nothing here can trigger a lazy load.
"""

from __future__ import annotations

import uuid as uuid_lib

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, load_only, selectinload

from app.modules.categories.model import Category, Categorizable, Taxonomy, TaxonomyEntityType
from app.modules.entities.model import EntityType
from app.modules.taxes.assignment import TaxAssignment

_TAXONOMY_SLIM = (Taxonomy.id, Taxonomy.uuid, Taxonomy.slug, Taxonomy.name, Taxonomy.status)

_CATEGORY_SLIM = (
    Category.id, Category.uuid, Category.taxonomy_id, Category.name, Category.taxonomy_slug,
    Category.parent_id, Category.is_root, Category.can_have_children, Category.depth,
    Category.category, Category.code, Category.title, Category.sub_title, Category.slug,
    Category.short_description, Category.description, Category.type, Category.ondc_category_type,
    Category.position, Category.display_order, Category.menu_order, Category.show_in_menu,
    Category.status, Category.is_verified, Category.is_active, Category.is_blocked,
    Category.is_featured, Category.is_promoted, Category.is_sponsored, Category.is_partnered,
    Category.is_visible, Category.visibility, Category.is_bookmarked,
    Category.icon, Category.color, Category.icon_color, Category.icon_bg_color,
    Category.icon_bg_image, Category.icon_border_color, Category.preview_image,
    Category.thumbnail, Category.banner, Category.image_url, Category.thumbnail_url, Category.banner_url,
    Category.settings, Category.metadata_, Category.extra_attributes, Category.record_notes,
)


# ── taxonomy ─────────────────────────────────────────────────────────────────

def _taxonomy_ref(ref: str):
    try:
        return Taxonomy.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        if str(ref).isdigit():
            return Taxonomy.id == int(ref)
        return Taxonomy.slug == str(ref)


async def list_taxonomies(
    db: AsyncSession, *, q: str | None = None, status: str | None = None,
    page: int = 1, page_size: int = 100,
) -> list[Taxonomy]:
    stmt = select(Taxonomy).options(load_only(*_TAXONOMY_SLIM)).order_by(Taxonomy.name, Taxonomy.id)
    if q:
        stmt = stmt.where(Taxonomy.name.ilike(f"%{q.strip()}%") | Taxonomy.slug.ilike(f"%{q.strip()}%"))
    if status:
        stmt = stmt.where(Taxonomy.status == status)
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def get_taxonomy(db: AsyncSession, ref: str) -> Taxonomy | None:
    stmt = (
        select(Taxonomy)
        .where(_taxonomy_ref(ref))
        .options(selectinload(Taxonomy.entity_types))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_taxonomy_by_id(db: AsyncSession, taxonomy_id: int) -> Taxonomy | None:
    return await db.get(Taxonomy, taxonomy_id)


async def find_taxonomy_by_slug(db: AsyncSession, organization_id: int, slug: str) -> Taxonomy | None:
    return await db.scalar(
        select(Taxonomy).where(Taxonomy.organization_id == organization_id,
                               Taxonomy.slug == slug).limit(1)
    )


async def create_taxonomy(db: AsyncSession, values: dict) -> Taxonomy:
    row = Taxonomy(**values)
    db.add(row)
    await db.flush()
    return row


async def list_entity_types(db: AsyncSession, taxonomy_id: int) -> list[TaxonomyEntityType]:
    return list((await db.scalars(
        select(TaxonomyEntityType)
        .where(TaxonomyEntityType.taxonomy_id == taxonomy_id)
        .order_by(TaxonomyEntityType.entity_type_code)
    )).all())


async def get_entity_type_row(
    db: AsyncSession, taxonomy_id: int, code: str, *, include_deleted: bool = False,
) -> TaxonomyEntityType | None:
    stmt = select(TaxonomyEntityType).where(
        TaxonomyEntityType.taxonomy_id == taxonomy_id,
        TaxonomyEntityType.entity_type_code == code,
    )
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    return await db.scalar(stmt.limit(1))


async def known_entity_type_codes(db: AsyncSession, codes: list[str]) -> set[str]:
    if not codes:
        return set()
    rows = await db.scalars(select(EntityType.code).where(EntityType.code.in_(codes)))
    return set(rows.all())


async def create_taxonomy_entity_type(db: AsyncSession, values: dict) -> TaxonomyEntityType:
    row = TaxonomyEntityType(**values)
    db.add(row)
    await db.flush()
    return row


# ── category ─────────────────────────────────────────────────────────────────

def _category_ref(ref: str):
    try:
        return Category.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        if str(ref).isdigit():
            return Category.id == int(ref)
        return Category.slug == str(ref)


async def list_categories(
    db: AsyncSession, *, taxonomy_id: int | None = None, parent_id: int | None = None,
    is_active: bool | None = None, q: str | None = None, view: str | None = None,
    page: int = 1, page_size: int = 200,
) -> list[Category]:
    order = (Category.taxonomy_id, Category.lft, Category.id) if view == "tree" else (
        Category.taxonomy_id, Category.position, Category.name, Category.id
    )
    stmt = select(Category).options(load_only(*_CATEGORY_SLIM)).order_by(*order)
    if taxonomy_id is not None:
        stmt = stmt.where(Category.taxonomy_id == taxonomy_id)
    if parent_id is not None:
        stmt = stmt.where(Category.parent_id == parent_id)
    if is_active is not None:
        stmt = stmt.where(Category.is_active.is_(is_active))
    if q:
        stmt = stmt.where(Category.name_normalized.ilike(f"%{q.strip().lower()}%"))
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def list_categories_in_taxonomy(db: AsyncSession, taxonomy_id: int) -> list[Category]:
    """Every live node of one tree (full rows — the bounds recompute needs them)."""
    return list((await db.scalars(
        select(Category)
        .where(Category.taxonomy_id == taxonomy_id)
        .order_by(Category.position, Category.id)
    )).all())


async def get_category(db: AsyncSession, ref: str) -> Category | None:
    stmt = (
        select(Category)
        .where(_category_ref(ref))
        .options(selectinload(Category.tags), selectinload(Category.documents),
                 selectinload(Category.tax_assignments).options(
                     joinedload(TaxAssignment.tax_component), joinedload(TaxAssignment.tax_exemption)))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_category_by_id(db: AsyncSession, category_id: int) -> Category | None:
    return await db.get(Category, category_id)


async def find_category_by_code(
    db: AsyncSession, taxonomy_id: int, code: str, *, exclude_id: int | None = None,
) -> Category | None:
    stmt = select(Category).where(Category.taxonomy_id == taxonomy_id, Category.code == code)
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    return await db.scalar(stmt.limit(1))


async def find_category_by_slug(
    db: AsyncSession, taxonomy_id: int, slug: str, *, exclude_id: int | None = None,
) -> Category | None:
    stmt = select(Category).where(Category.taxonomy_id == taxonomy_id, Category.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    return await db.scalar(stmt.limit(1))


async def count_live_children(db: AsyncSession, category_id: int) -> int:
    return int(await db.scalar(
        select(func.count()).select_from(Category).where(Category.parent_id == category_id)
    ) or 0)


async def create_category(db: AsyncSession, values: dict) -> Category:
    row = Category(**values)
    db.add(row)
    await db.flush()
    return row


# ── categorizable ────────────────────────────────────────────────────────────

async def get_categorizable(db: AsyncSession, ref: str) -> Categorizable | None:
    conditions = []
    if str(ref).isdigit():
        conditions.append(Categorizable.id == int(ref))
    else:
        try:
            conditions.append(Categorizable.uuid == uuid_lib.UUID(str(ref)))
        except ValueError:
            return None
    return await db.scalar(select(Categorizable).where(or_(*conditions)).limit(1))


async def list_categorizables(
    db: AsyncSession, *, category_id: int | None = None, categorizable_type: str | None = None,
    categorizable_id: int | None = None, taxonomy_id: int | None = None,
    valid_at=None, page: int = 1, page_size: int = 200,
) -> list[Categorizable]:
    stmt = select(Categorizable).order_by(Categorizable.category_id, Categorizable.sort_order, Categorizable.id)
    if category_id is not None:
        stmt = stmt.where(Categorizable.category_id == category_id)
    if categorizable_type is not None:
        stmt = stmt.where(Categorizable.categorizable_type == categorizable_type)
    if categorizable_id is not None:
        stmt = stmt.where(Categorizable.categorizable_id == categorizable_id)
    if taxonomy_id is not None:
        stmt = stmt.where(Categorizable.taxonomy_id == taxonomy_id)
    if valid_at is not None:
        stmt = stmt.where(
            Categorizable.valid_from <= valid_at,
            or_(Categorizable.valid_to.is_(None), Categorizable.valid_to > valid_at),
        )
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def list_live_assignments(
    db: AsyncSession, *, categorizable_type: str, categorizable_id: int, taxonomy_id: int,
) -> list[Categorizable]:
    return list((await db.scalars(
        select(Categorizable).where(
            Categorizable.categorizable_type == categorizable_type,
            Categorizable.categorizable_id == categorizable_id,
            Categorizable.taxonomy_id == taxonomy_id,
            Categorizable.valid_to.is_(None),
        )
    )).all())


async def create_categorizable(db: AsyncSession, values: dict) -> Categorizable:
    row = Categorizable(**values)
    db.add(row)
    await db.flush()
    return row


async def clear_other_primaries(
    db: AsyncSession, *, taxonomy_id: int, categorizable_type: str, categorizable_id: int,
    keep_id: int | None = None,
) -> None:
    stmt = select(Categorizable).where(
        Categorizable.taxonomy_id == taxonomy_id,
        Categorizable.categorizable_type == categorizable_type,
        Categorizable.categorizable_id == categorizable_id,
        Categorizable.is_primary.is_(True),
        Categorizable.valid_to.is_(None),
    )
    if keep_id is not None:
        stmt = stmt.where(Categorizable.id != keep_id)
    for other in (await db.scalars(stmt)).all():
        other.is_primary = False


__all__ = [
    "clear_other_primaries",
    "count_live_children",
    "create_category",
    "create_categorizable",
    "create_taxonomy",
    "create_taxonomy_entity_type",
    "find_category_by_code",
    "find_category_by_slug",
    "find_taxonomy_by_slug",
    "get_category",
    "get_category_by_id",
    "get_categorizable",
    "get_entity_type_row",
    "get_taxonomy",
    "get_taxonomy_by_id",
    "known_entity_type_codes",
    "list_categories",
    "list_categories_in_taxonomy",
    "list_categorizables",
    "list_entity_types",
    "list_live_assignments",
    "list_taxonomies",
]
