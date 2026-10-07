"""The permission catalogue — THE audited list of everything that can be granted.

Deliberately ONE file rather than a list per module: this is a security
artefact, and "what can a role be given?" should be answerable by reading a
single page. Feature modules never register permissions; they *use* them, and
``rbac.deps.Perm(code)`` refuses to import if a code is not in this file — so a
typo is a startup failure, not a permanent 403 (docs/rbac-module.md §4.2).

Format
------
``module.resource:action`` — three parts, lower snake case. The database keeps
the parts and GENERATES the code from them (``rbac.permissions.permission_code``),
so a code can never disagree with its own parts.

Actions: ``create read update delete manage assign approve export import verify
send use``. ``manage`` implies ``create/read/update/delete`` on the same
resource (expanded when grants are loaded); it does NOT imply the others.

``owner_only`` marks the few permissions the ``admin`` role does not get
(``all_but_owner_only`` mode); ``owner`` (mode ``all``) has everything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CRUD = ("create", "read", "update", "delete")
_CODE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    module: str
    resource: str
    action: str
    description: str = ""
    owner_only: bool = False

    @property
    def code(self) -> str:
        return f"{self.module}.{self.resource}:{self.action}"


def _p(module: str, resource: str, actions: str, label: str | None = None, *, owner_only: bool = False):
    """One resource, several actions: ``_p("core", "brand", "create update delete")``."""
    label = label or resource.replace("_", " ")
    return [
        PermissionSpec(module, resource, action, f"{action.capitalize()} {label}", owner_only)
        for action in actions.split()
    ]


_ENTRIES: list[PermissionSpec] = [
    # ── identity & access ───────────────────────────────────────────────────
    *_p("users", "directory", "read", "the user directory (names and avatars of colleagues)"),
    *_p("users", "user", "create read update delete restore assign_role", "users"),
    *_p("users", "moderation", "manage", "user bans, throttles and locks"),
    *_p("users", "location", "read", "other users' last known location"),
    *_p("users", "session", "read delete", "other users' sign-in sessions (delete = revoke)"),
    *_p("rbac", "permission", "read", "the permission catalogue"),
    *_p("rbac", "role", "create update delete manage", "roles and their permission sets"),
    *_p("rbac", "assignment", "read assign", "contextual role assignments"),
    *_p("rbac", "owner", "assign", "the owner role (grant or revoke)", owner_only=True),
    # ── tenancy ─────────────────────────────────────────────────────────────
    *_p("org", "organization", "create update delete manage", "organizations"),
    # ── teams & structure ───────────────────────────────────────────────────
    *_p("teams", "department", "create read update delete manage", "departments"),
    *_p("teams", "job_title", "create read update delete", "job titles"),
    *_p("teams", "team_type", "create read update delete manage", "team types"),
    *_p("teams", "team_role", "create read update delete", "team roles"),
    *_p("teams", "team", "create read update delete manage", "teams"),
    *_p("teams", "membership", "read assign approve", "team membership"),
    *_p("hr", "employment", "create read update", "employment records"),
    # ── master data ─────────────────────────────────────────────────────────
    *_p("core", "brand", "create update delete", "brands"),
    *_p("core", "manufacturer", "create update delete", "manufacturers"),
    *_p("core", "taxonomy", "create update delete", "taxonomies"),
    *_p("core", "category", "create update delete", "categories"),
    *_p("core", "categorizable", "assign", "category assignments"),
    *_p("core", "alias", "create delete", "entity aliases"),
    *_p("currency", "currency", "create update delete manage verify", "currencies"),
    *_p("currency", "rate", "create", "exchange rates"),
    *_p("tax", "assignment", "manage", "tax assignments"),
    *_p("extfields", "definition", "create update delete", "custom field definitions"),
    *_p("extfields", "value", "update delete manage", "custom field values"),
    *_p("tags", "tag", "create update delete assign", "tags"),
    *_p("comments", "comment", "create read update delete manage", "comments"),
    # ── documents, files, mail ──────────────────────────────────────────────
    *_p("documents", "document", "read create update delete verify", "documents"),
    *_p("files", "file", "create update delete", "files"),
    *_p("emails", "email", "read send", "emails"),
    # ── operations ──────────────────────────────────────────────────────────
    *_p("hubs", "hub", "create update delete manage", "hubs"),
    *_p("hubs", "assignment", "read manage", "users' hub of the day (date-effective assignments)"),
    *_p("fleet", "partner", "create update delete manage", "fleet partners"),
    *_p("fleet", "vehicle", "create update delete manage", "vehicles"),
    *_p("fleet", "driving_license", "read create", "driving licences"),
    # ── field operations (docs/fieldops/) ───────────────────────────────────
    *_p("fieldops", "field_work", "use", "the field app: own shifts, pauses, visits, tasks and location"),
    *_p("fieldops", "telephonic_visit", "create", "telephonic and video visits (granted per organization role)"),
    *_p("fieldops", "shift", "create read update delete approve manage", "field shifts (create = schedule)"),
    *_p("fieldops", "visit", "create read update delete approve manage", "field visits (create = plan stops)"),
    *_p("fieldops", "shift_template", "create read update delete manage", "shift templates"),
    *_p("fieldops", "anomaly", "read approve", "field-ops anomalies (approve = resolve / dismiss)"),
    *_p("fieldops", "policy", "create read update delete manage", "field policy layers"),
    # ── location hub ────────────────────────────────────────────────────────
    *_p("geo", "place", "create update delete manage verify", "places"),
    *_p("geo", "address", "create update delete verify", "addresses"),
    *_p("geo", "geofence", "create update delete", "geofences"),
    *_p("geo", "boundary", "create", "administrative boundaries"),
    *_p("geo", "geocoding", "use manage", "the geocoding providers (billable calls)"),
    # ── platform integration & audit ────────────────────────────────────────
    *_p("zoho", "integration", "read manage", "the Zoho integration"),
    *_p("activity", "log", "read export", "the audit log"),
]

#: code -> Permission, in declaration order.
PERMISSIONS: dict[str, PermissionSpec] = {p.code: p for p in _ENTRIES}

#: Every code the platform knows.
ALL_CODES: frozenset[str] = frozenset(PERMISSIONS)

#: Codes the ``admin`` role does not get (only ``owner`` does).
OWNER_ONLY: frozenset[str] = frozenset(p.code for p in _ENTRIES if p.owner_only)


def _validate() -> None:
    if len(PERMISSIONS) != len(_ENTRIES):
        seen: set[str] = set()
        dupes = [p.code for p in _ENTRIES if p.code in seen or seen.add(p.code)]
        raise RuntimeError(f"duplicate permission codes in the catalogue: {sorted(set(dupes))}")
    for code in PERMISSIONS:
        if not _CODE.match(code):
            raise RuntimeError(f"malformed permission code {code!r} (want module.resource:action)")


_validate()


def expand(codes) -> set[str]:
    """Apply ``manage`` ⇒ create/read/update/delete on the same resource.

    Only adds a derived code that ACTUALLY EXISTS in the catalogue: several resources declare
    ``manage`` without the full CRUD set (``tax.assignment``, ``geo.geocoding``, ``currency.currency``
    has no separate ``read``, …), and adding an undeclared code would let a role's effective
    permission set include one nothing can ever hold — not even ``owner`` (whose ``has()`` also
    checks ``code in ALL_CODES``) — turning "grant this role" into a standing refusal.
    """
    out = set(codes)
    for code in list(out):
        head, _, action = code.rpartition(":")
        if action == "manage":
            out.update(f"{head}:{a}" for a in CRUD if f"{head}:{a}" in ALL_CODES)
    return out


def codes_matching(*, actions: set[str] | None = None, modules: set[str] | None = None) -> set[str]:
    """Catalogue codes filtered by action and/or module (used to build templates)."""
    return {
        p.code for p in _ENTRIES
        if (actions is None or p.action in actions) and (modules is None or p.module in modules)
    }


def require_known(code: str) -> str:
    """Return ``code`` if it is in the catalogue, else raise — used by ``Perm``."""
    if code not in ALL_CODES:
        raise RuntimeError(
            f"unknown permission {code!r}: add it to app/modules/rbac/catalogue.py "
            f"(or fix the typo)"
        )
    return code


__all__ = [
    "ALL_CODES", "CRUD", "OWNER_ONLY", "PERMISSIONS", "PermissionSpec",
    "codes_matching", "expand", "require_known",
]
