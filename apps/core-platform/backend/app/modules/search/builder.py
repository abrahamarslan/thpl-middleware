"""ScoutBuilder — Laravel-Scout-style search with Postgres hydration.

    rows = await (
        ScoutBuilder(ZohoOrganization, "acme")
        .where("address_country", "India")
        .limit(10)
        .get(db)
    )

Meilisearch answers "which ids, in what order"; Postgres answers "the actual
rows" (fresh, relational, soft-delete-filtered). Results keep Meilisearch's
relevance ordering.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings

_meili_client = None


def get_meili_client():
    """Lazy singleton — only created when a search is actually issued."""
    global _meili_client
    if _meili_client is None:
        from meilisearch_python_sdk import AsyncClient

        _meili_client = AsyncClient(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY)
    return _meili_client


class ScoutBuilder:
    def __init__(self, model_class: type, query: str = "") -> None:
        self.model_class = model_class
        self.index_name = model_class.__tablename__
        self.query = query
        self._filters: list[str] = []
        self._limit = 20
        self._offset = 0

    def where(self, field: str, value: Any, operator: str = "=") -> "ScoutBuilder":
        if isinstance(value, str):
            escaped = value.replace("'", "\\'")
            self._filters.append(f"{field} {operator} '{escaped}'")
        else:
            self._filters.append(f"{field} {operator} {value}")
        return self

    def limit(self, limit: int) -> "ScoutBuilder":
        self._limit = limit
        return self

    def offset(self, offset: int) -> "ScoutBuilder":
        self._offset = offset
        return self

    async def raw(self) -> Any:
        """Raw Meilisearch response (hits carry only indexed fields)."""
        index = get_meili_client().index(self.index_name)
        kwargs: dict[str, Any] = {"limit": self._limit, "offset": self._offset}
        if self._filters:
            kwargs["filter"] = " AND ".join(self._filters)
        return await index.search(self.query, **kwargs)

    async def get(self, db: AsyncSession) -> list:
        """Search then hydrate from Postgres, preserving relevance order."""
        result = await self.raw()
        hits = result.hits or []
        if not hits:
            return []

        pk = self.model_class.id
        hit_ids = [hit["id"] for hit in hits if "id" in hit]
        try:
            typed_ids = [pk.type.python_type(h) for h in hit_ids]
        except (TypeError, ValueError):
            typed_ids = hit_ids

        rows = (await db.scalars(select(self.model_class).where(pk.in_(typed_ids)))).all()
        by_id = {row.id: row for row in rows}
        return [by_id[i] for i in typed_ids if i in by_id]
