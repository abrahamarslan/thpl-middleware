"""Apply hooks for the Zoho organization adapter.

pre_upsert   the Zoho name is the registered name of a Zoho-linked legal
             entity → ``legal_name`` follows it (org_code / org_type / tree
             position are never touched; a new node becomes a root via the
             model's ``before_insert``).

There is no ``post_upsert`` any more. Linking ``currency_id`` used to be a
hand-written hook here — the first crosswalk lookup in the codebase, and the
proof the idea worked. It is now a declared ``ReferenceRule`` on the module's
contract (``spec.py``), resolved by the engine for every module at once, in one
query per page. A rule a registry can read beats a function only this module
knows about: the planner can order on it, the resolver can budget it, and the
next module gets it for free.
"""

from typing import Any


def zoho_owned_legal_name(payload: dict, values: dict[str, Any]) -> dict[str, Any]:
    if values.get("name"):
        values["legal_name"] = values["name"]
    return values


__all__ = ["zoho_owned_legal_name"]
