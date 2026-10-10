"""Resolution engine — "what applies here?" for every facet (taxes, accounts, …).

One engine, many facets: features register a ``Facet`` (how candidates load, how a context
narrows them, what the organization default is) and default ``Policy`` objects (ordered
owner steps per subject kind); tenants and organizations may override a policy through
``/api/resolution/policies``. Batched: a page of subjects costs a fixed number of queries.

This package imports NO feature module (``.importlinter``); features register into it.
Docs: docs/implementation-plan/accounts-module.md §7.
"""

from app.modules.resolution.engine import ResolutionError, resolve_many, resolve_one
from app.modules.resolution.registry import resolution_registry
from app.modules.resolution.types import Expansion, Outcome, OwnerRef, Policy, Resolution, Step, Subject

__all__ = [
    "Expansion",
    "Outcome",
    "OwnerRef",
    "Policy",
    "Resolution",
    "ResolutionError",
    "Step",
    "Subject",
    "resolution_registry",
    "resolve_many",
    "resolve_one",
]
