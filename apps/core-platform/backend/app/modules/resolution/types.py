"""The vocabulary of the resolution engine — plain data, no I/O.

    OwnerRef     an entity that can CARRY facet values: ``("item", 4)``. ``type_code`` is a
                 ``core.entity_types.code``.
    Subject      the thing a value is resolved FOR (one invoice line): role → owner(s),
                 its organization, and the facet's typed context.
    Step         one rung of a policy: ask this role (optionally through a facet filter);
                 what to do when its answer is unusable.
    Expansion    "role X is derived from role Y by expander Z" (an item → its categories).
    Policy       ordered steps for one (facet, subject kind); the organization default is
                 the implicit last step unless switched off.
    Resolution   the answer: values + provenance (``via`` role, ``owner``) + a trace.

Docs: docs/implementation-plan/accounts-module.md §7.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, NamedTuple

#: The role name the organization default answers under, in traces and ``via``.
ORGANIZATION_ROLE = "organization"


class OwnerRef(NamedTuple):
    type_code: str
    id: int

    def __str__(self) -> str:
        return f"{self.type_code}:{self.id}"


OnUnusable = Literal["fail", "skip"]


@dataclass(frozen=True, slots=True)
class Step:
    role: str
    #: A facet-declared candidate filter (``exemption_only``); None = every candidate.
    filter: str | None = None
    #: ``fail`` (default): an unusable answer is an error — falling through would silently
    #: post to the wrong place. ``skip``: carry on down the chain (genuinely optional layers).
    on_unusable: OnUnusable = "fail"

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "filter": self.filter, "on_unusable": self.on_unusable}


@dataclass(frozen=True, slots=True)
class Expansion:
    role: str            # the derived role, e.g. "item_category"
    from_role: str       # the role it is derived from, e.g. "item"
    expander: str        # a registered expander, e.g. "categories"


@dataclass(frozen=True, slots=True)
class Policy:
    facet: str
    subject: str
    steps: tuple[Step, ...]
    #: The roles a caller may supply for this subject kind.
    roles: frozenset[str]
    expansions: tuple[Expansion, ...] = ()
    use_organization_default: bool = True
    description: str = ""
    #: ``code`` | ``tenant`` | ``organization`` — where the effective policy came from.
    layer: str = "code"

    @property
    def all_roles(self) -> frozenset[str]:
        return self.roles | {e.role for e in self.expansions}

    def with_steps(self, steps: Sequence[Step], *, use_organization_default: bool, layer: str) -> Policy:
        return Policy(facet=self.facet, subject=self.subject, steps=tuple(steps), roles=self.roles,
                      expansions=self.expansions, use_organization_default=use_organization_default,
                      description=self.description, layer=layer)


@dataclass(slots=True)
class Subject:
    #: role → one owner, several owners (most relevant first), or None (not applicable).
    roles: Mapping[str, OwnerRef | Sequence[OwnerRef] | None]
    #: The organization whose defaults close the chain (None = tenant-wide defaults only).
    organization_id: int | None
    #: The facet's context model instance (validated by the engine).
    context: Any = None

    def owners_of(self, role: str) -> list[OwnerRef]:
        value = self.roles.get(role)
        if value is None:
            return []
        if isinstance(value, OwnerRef):
            return [value]
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
            return [OwnerRef(*value)]           # a bare ("item", 4)
        return [OwnerRef(*v) for v in value]


class Outcome(StrEnum):
    ANSWERED = "answered"                       # an owner in the chain answered
    ORGANIZATION_DEFAULT = "organization_default"
    NONE = "none"                               # nobody answered — the caller decides
    UNUSABLE = "unusable"                       # an answer exists but cannot be used (fail-closed)


@dataclass(slots=True)
class TraceEntry:
    step: int | None
    role: str
    owner: OwnerRef | None
    result: str          # no_owner | no_candidates | pending | filtered | unusable:<r> | skipped:<r> | answered
    detail: str | None = None


@dataclass(slots=True)
class Resolution:
    outcome: Outcome
    values: list[Any] = field(default_factory=list)
    via: str | None = None              # the role that answered
    owner: OwnerRef | None = None       # the owner that answered
    reason: str | None = None           # for UNUSABLE
    trace: list[TraceEntry] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.outcome in (Outcome.ANSWERED, Outcome.ORGANIZATION_DEFAULT)


__all__ = [
    "ORGANIZATION_ROLE",
    "Expansion",
    "OnUnusable",
    "Outcome",
    "OwnerRef",
    "Policy",
    "Resolution",
    "Step",
    "Subject",
    "TraceEntry",
]
