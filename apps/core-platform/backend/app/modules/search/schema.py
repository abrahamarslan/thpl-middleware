"""Search transport schemas."""

from typing import Any

from pydantic import BaseModel, Field


class SearchResponse(BaseModel):
    """Hydrated search results + query echo.

    ``hits`` are full rows serialized by the entity's registered Out schema
    (fresh from Postgres, soft-delete filtered), in Meilisearch relevance
    order — never raw index documents.
    """

    index: str
    query: str
    limit: int
    offset: int
    count: int = Field(description="Number of hits returned (post-hydration)")
    hits: list[dict[str, Any]]
