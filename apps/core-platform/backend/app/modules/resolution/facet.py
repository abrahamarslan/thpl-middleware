"""The facet contract — what a kind of answer (taxes, accounts, …) must provide.

A facet owns its semantics; the engine owns the walk. The split is the point: the engine
knows nothing about taxes or accounts, and a facet knows nothing about chains, policies or
batching.

    load()    ONE batch for every owner of every subject (plus whatever the facet needs to
              judge usability and the organization defaults) — a fixed number of queries,
              whatever the subject count.
    select()  PURE: narrow one owner's candidates to what applies in a context. ``[]`` = this
              owner has no answer here.

The object ``load`` returns (``FacetData``) answers the per-owner questions in memory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resolution.types import OwnerRef, Subject


class FacetData(Protocol):
    def candidates(self, owner: OwnerRef) -> Sequence[Any]:
        """Every candidate this owner carries (pending ones included — ``select`` drops them)."""

    def has_pending(self, owner: OwnerRef) -> bool:
        """Does this owner carry an unresolved (source-named, not yet synced) value?"""

    def organization_default(self, organization_id: int | None, context: Any) -> Sequence[Any]:
        """The organization's default for this context (already narrowed)."""

    def unusable(self, candidate: Any, organization_id: int | None) -> str | None:
        """Why this answer cannot be used (inactive, deleted, not granted), else None."""


class Facet(ABC):
    #: Registry key: "tax", "account".
    code: ClassVar[str]
    #: Validates a subject's context at the API edge and in the engine.
    context_model: ClassVar[type[BaseModel]]
    #: Named candidate filters a policy step may use (``exemption_only``).
    filters: ClassVar[Mapping[str, Callable[[Any], bool]]] = {}
    description: ClassVar[str] = ""

    @abstractmethod
    async def load(self, db: AsyncSession, owners: Collection[OwnerRef], subjects: Sequence[Subject]) -> FacetData:
        ...

    @abstractmethod
    def select(self, candidates: Sequence[Any], context: Any) -> list[Any]:
        ...

    def describe(self, value: Any) -> dict[str, Any]:
        """A JSON-safe summary of one resolved value, for the API and audit traces."""
        return {"value": repr(value)}

    def context(self, raw: Any) -> Any:
        if isinstance(raw, self.context_model):
            return raw
        return self.context_model.model_validate(raw or {})


__all__ = ["Facet", "FacetData"]
