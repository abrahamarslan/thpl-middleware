"""Apply hooks for the Zoho Books brand adapter.

``stamp_scope`` is the ``currencies/zoho/hooks.py::stamp_scope`` pattern,
copied rather than shared because each caller's rule-error type differs:
``core.brands`` requires a provenance pair (``PolymorphicOwnerMixin``:
``owner_type`` + ``owner_id``) the payload cannot supply, and the sync has no
user to ask — the organization comes from the run's context (the connection
that scheduled the sync), same as every other org-scoped Zoho *settings*
record.

A slug fallback mirrors ``categories/zoho/hooks.py::normalise_category``: Zoho
sends no URL-friendly key for a brand, so one is derived from the name — but
only when the row does not already have one (a rename must not silently change
a slug something else may already link to).
"""

from __future__ import annotations

import re
from typing import Any

from app.database.tenancy import current_organization_id
from app.modules.entities.enums import MasterOwnerType
from app.modules.entities.scope import CoreRuleError

_WORD = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    return _WORD.sub("-", value.strip().lower()).strip("-")


def stamp_scope(payload: dict, values: dict[str, Any]) -> dict[str, Any]:
    organization_id = current_organization_id()
    if organization_id is None:
        raise CoreRuleError(
            "cannot place a synced brand: no organization in context. Zoho's /brands is "
            "tenant-wide, but core.brands requires an organization — resolve the "
            "connection→organization mapping first (docs/implementation-plan/"
            "sync-crosswalk-redesign.md §10.1)."
        )
    stamped: dict[str, Any] = {
        **values,
        "owner_type": MasterOwnerType.ORGANIZATION.value,
        "owner_id": organization_id,
    }
    if not stamped.get("slug") and stamped.get("name"):
        stamped["slug"] = _slugify(stamped["name"])[:180] or None
    return stamped


__all__ = ["stamp_scope"]
