"""The ``categories`` expander for the resolution engine: an owner → the categories it is in.

A policy step such as ``item_category`` asks the categories of the line's item; this is
where that role's owners come from (``Expansion(role="item_category", from_role="item",
expander="categories")``). ONE query for every owner of the batch, off
``ix_categorizables_thing``.

Order = relevance: the primary category first, then ``sort_order``, then the oldest
assignment — the engine asks them in that order and the first that answers wins. Only
assignments live NOW count (not soft-deleted, inside their validity window).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.model import Categorizable
from app.modules.resolution import OwnerRef, resolution_registry

#: The entity-types code a category is stored under (assignments, tax and account owners).
CATEGORY_TYPE = "category"


async def categories_of(db: AsyncSession, owners: Collection[OwnerRef]) -> dict[OwnerRef, list[OwnerRef]]:
    if not owners:
        return {}
    now = func.now()
    rows = (await db.execute(
        select(Categorizable.categorizable_type, Categorizable.categorizable_id, Categorizable.category_id)
        .where(tuple_(Categorizable.categorizable_type, Categorizable.categorizable_id).in_(sorted(owners)),
               Categorizable.valid_from <= now,
               or_(Categorizable.valid_to.is_(None), Categorizable.valid_to > now))
        .order_by(Categorizable.is_primary.desc(), Categorizable.sort_order, Categorizable.id)
    )).all()
    result: dict[OwnerRef, list[OwnerRef]] = defaultdict(list)
    for owner_type, owner_id, category_id in rows:
        target = OwnerRef(CATEGORY_TYPE, category_id)
        bucket = result[OwnerRef(owner_type, owner_id)]
        if target not in bucket:
            bucket.append(target)
    return dict(result)


resolution_registry.register_expander("categories", categories_of)

__all__ = ["CATEGORY_TYPE", "categories_of"]
