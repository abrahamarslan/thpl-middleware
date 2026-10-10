"""The resolution registry — facets, expanders and default policies, registered BY features.

The engine is source- and feature-neutral (``.importlinter``: ``app.modules.resolution``
imports no feature module). Features register into it on import, discovered by package
name — the same inversion as the Zoho adapter registry:

    taxes/resolution.py        TaxFacet + the tax policies
    accounting/resolution.py   AccountFacet + the account policies
    categories/resolution.py   the ``categories`` expander (owner → its categories)

A policy that names an unknown facet, role, filter or expander FAILS THE BOOT
(``validate``), like a bad sync spec: a typo must die at startup, not at 03:00 on an
invoice.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Iterable
from importlib import import_module

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.resolution.facet import Facet
from app.modules.resolution.types import ORGANIZATION_ROLE, OwnerRef, Policy, Step

logger = structlog.get_logger("app.resolution.registry")

#: Packages imported by ``autodiscover``; each registers itself on import.
_PACKAGES = (
    "app.modules.taxes.resolution",
    "app.modules.accounting.resolution",
    "app.modules.categories.resolution",
)

#: owner → the owners it inherits from, most relevant first. ONE query for the whole batch.
Expander = Callable[[AsyncSession, Collection[OwnerRef]], Awaitable[dict[OwnerRef, list[OwnerRef]]]]


class ResolutionRegistryError(RuntimeError):
    """A facet/policy declaration is inconsistent."""


class ResolutionRegistry:
    def __init__(self) -> None:
        self._facets: dict[str, Facet] = {}
        self._expanders: dict[str, Expander] = {}
        self._policies: dict[tuple[str, str], Policy] = {}
        self._discovered = False

    # ── registration ──────────────────────────────────────────────────────────
    def register_facet(self, facet: Facet) -> Facet:
        self._facets[facet.code] = facet
        return facet

    def register_expander(self, name: str, expander: Expander) -> None:
        self._expanders[name] = expander

    def register_policy(self, policy: Policy) -> Policy:
        self._policies[(policy.facet, policy.subject)] = policy
        return policy

    # ── lookup ────────────────────────────────────────────────────────────────
    def autodiscover(self) -> None:
        if self._discovered:
            return
        self._discovered = True
        for package in _PACKAGES:
            import_module(package)
        self.validate()

    def facet(self, code: str) -> Facet:
        self.autodiscover()
        try:
            return self._facets[code]
        except KeyError:
            raise NotFoundError(f"Unknown resolution facet '{code}'") from None

    def expander(self, name: str) -> Expander:
        self.autodiscover()
        return self._expanders[name]

    def policy(self, facet: str, subject: str) -> Policy:
        self.autodiscover()
        try:
            return self._policies[(facet, subject)]
        except KeyError:
            raise NotFoundError(f"No resolution policy for facet '{facet}' and subject '{subject}'") from None

    def facets(self) -> list[Facet]:
        self.autodiscover()
        return [self._facets[k] for k in sorted(self._facets)]

    def policies(self, facet: str | None = None) -> list[Policy]:
        self.autodiscover()
        return [p for (f, _), p in sorted(self._policies.items()) if facet is None or f == facet]

    # ── validation ────────────────────────────────────────────────────────────
    def problems_of(self, policy: Policy, steps: Iterable[Step] | None = None) -> list[str]:
        """What is wrong with ``policy`` (or with ``steps`` proposed for it); [] = fine."""
        problems: list[str] = []
        facet = self._facets.get(policy.facet)
        if facet is None:
            return [f"{policy.facet}/{policy.subject}: unknown facet '{policy.facet}'"]
        steps = tuple(policy.steps if steps is None else steps)
        allowed = policy.all_roles
        if ORGANIZATION_ROLE in allowed:
            problems.append(f"{policy.facet}/{policy.subject}: '{ORGANIZATION_ROLE}' is the implicit last "
                            "step, not a role")
        seen: set[tuple[str, str | None]] = set()
        for index, step in enumerate(steps):
            if step.role not in allowed:
                problems.append(f"{policy.facet}/{policy.subject}: step {index} names unknown role '{step.role}' "
                                f"(known: {sorted(allowed)})")
            if step.filter is not None and step.filter not in facet.filters:
                problems.append(f"{policy.facet}/{policy.subject}: step {index} uses unknown filter '{step.filter}' "
                                f"(known: {sorted(facet.filters)})")
            if step.on_unusable not in ("fail", "skip"):
                problems.append(f"{policy.facet}/{policy.subject}: step {index} on_unusable must be fail|skip")
            key = (step.role, step.filter)
            if key in seen:
                problems.append(f"{policy.facet}/{policy.subject}: step {index} repeats role '{step.role}' "
                                f"with the same filter")
            seen.add(key)
        for expansion in policy.expansions:
            if expansion.expander not in self._expanders:
                problems.append(f"{policy.facet}/{policy.subject}: expansion '{expansion.role}' uses unregistered "
                                f"expander '{expansion.expander}'")
            if expansion.from_role not in policy.roles:
                problems.append(f"{policy.facet}/{policy.subject}: expansion '{expansion.role}' derives from "
                                f"unknown role '{expansion.from_role}'")
        return problems

    def validate(self) -> None:
        problems = [p for policy in self._policies.values() for p in self.problems_of(policy)]
        if problems:
            for problem in problems:
                logger.critical("resolution.registry.invalid_policy", problem=problem)
            raise ResolutionRegistryError("invalid resolution policies:\n  " + "\n  ".join(problems))


resolution_registry = ResolutionRegistry()

__all__ = ["Expander", "ResolutionRegistry", "ResolutionRegistryError", "resolution_registry"]
