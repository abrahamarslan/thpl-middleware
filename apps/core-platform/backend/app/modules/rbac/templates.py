"""System role templates — seeded for every organization.

``owner`` and ``admin`` are COMPUTED (``grant_mode``): they hold no
``role_permissions`` rows, so a new catalogue permission reaches them with no
per-organization sync. The other templates are ``explicit`` and get their rows
from here, added missing-only (a permission an operator removed is not put back
unless ``--prune``/re-seed is asked for).

Codes are lower snake case (the ``roles.code`` pattern). ``hierarchy_level``
feeds the escalation guard: an actor may only assign a role whose level is below
the highest they hold (docs/rbac-module.md §4.8).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.rbac.catalogue import codes_matching
from app.modules.rbac.enums import GrantMode


@dataclass(frozen=True, slots=True)
class RoleTemplate:
    code: str
    name: str
    description: str
    level: int
    grant_mode: GrantMode
    permissions: frozenset[str] = frozenset()


#: Day-to-day business actions that were open to ANY signed-in user before RBAC existed (the routes
#: took only ``CurrentUser`` — never ``TenantAdmin``). ``member`` gets exactly these, so enforcing
#: permissions does not silently lock ordinary employees out of ordinary work (uploading your own KYC
#: document, tagging a record, creating a brand or currency, geocoding an address, …). What was already
#: ``TenantAdmin`` before (delete, verify, archive, deactivate, manage) stays admin+-only — that is the
#: real tightening this migration makes, not a side effect of it.
#:
#: Two codes are coarser than their old routes: ``core.categorizable:assign`` and ``tax.assignment:manage``
#: each cover a pair of routes where only one half was open before (assign vs. unassign; replace vs.
#: delete) — the catalogue has one action for the pair, so granting the operational half also reaches
#: the other. ``users.location:read`` and ``activity.log:read`` were ALSO open before, but are deliberately
#: NOT restored here: the platform-wide "any user can see any user's live location / read the whole
#: tenant's audit trail" access was a gap, not a feature (docs/rbac-module.md F2), and closing it is the
#: point of enforcing RBAC at all.
_OPERATIONAL: frozenset[str] = frozenset({
    "core.brand:create", "core.brand:update",
    "core.manufacturer:create", "core.manufacturer:update",
    "core.taxonomy:create", "core.taxonomy:update",
    "core.category:create", "core.category:update",
    "core.categorizable:assign",
    "core.alias:create",
    "currency.currency:create", "currency.currency:update",
    "currency.rate:create",
    "tax.assignment:manage",
    "extfields.definition:create", "extfields.definition:update",
    "extfields.value:update",
    "tags.tag:create", "tags.tag:update", "tags.tag:delete", "tags.tag:assign",
    "documents.document:read", "documents.document:create", "documents.document:update",
    "documents.document:delete",
    "files.file:create", "files.file:update", "files.file:delete",
    "emails.email:read", "emails.email:send",
    "hubs.hub:create", "hubs.hub:update",
    "fleet.partner:create", "fleet.partner:update",
    "fleet.vehicle:create", "fleet.vehicle:update",
    "fleet.driving_license:read", "fleet.driving_license:create",
    "geo.place:create", "geo.place:update", "geo.place:verify",
    "geo.address:create", "geo.address:update", "geo.address:verify", "geo.address:delete",
    "geo.geocoding:use",
})


def _templates() -> tuple[RoleTemplate, ...]:
    reads = codes_matching(actions={"read"})
    return (
        RoleTemplate(
            "owner", "Owner", "Owns the organization and its tenant; every permission",
            100, GrantMode.ALL,
        ),
        RoleTemplate(
            "admin", "Administrator", "Manages the organization, roles and users; everything but owner-only actions",
            80, GrantMode.ALL_BUT_OWNER_ONLY,
        ),
        RoleTemplate(
            "department_head", "Head of Department",
            "Oversees a department and the teams under it", 60, GrantMode.EXPLICIT,
            frozenset({
                "users.directory:read", "teams.department:read", "teams.department:update",
                "teams.job_title:read", "teams.team_type:read", "teams.team_role:read",
                "teams.team:read", "teams.membership:read", "teams.membership:assign",
                "teams.membership:approve", "hr.employment:read",
            }),
        ),
        RoleTemplate(
            "team_manager", "Team Manager", "Manages a team and its members", 50, GrantMode.EXPLICIT,
            frozenset({
                "users.directory:read", "teams.department:read", "teams.job_title:read",
                "teams.team_type:read", "teams.team_role:read", "teams.team:read",
                "teams.team:update", "teams.membership:read", "teams.membership:assign",
                "teams.membership:approve",
            }),
        ),
        RoleTemplate(
            "auditor", "Auditor", "Read-only access to everything, plus the audit log",
            30, GrantMode.EXPLICIT, frozenset(reads | {"activity.log:export"}),
        ),
        RoleTemplate(
            "member", "Member", "Regular user — day-to-day operational access; no deletes, verification or management",
            10, GrantMode.EXPLICIT,
            frozenset({
                "users.directory:read", "teams.department:read", "teams.job_title:read",
                "teams.team_type:read", "teams.team_role:read", "teams.team:read",
                "teams.membership:read",
                # A brand-new feature (never open pre-RBAC, so it does NOT belong in
                # _OPERATIONAL): any member may comment and edit/remove their OWN comment
                # (comments.service._check_owner enforces "own" — comments.comment:manage,
                # admin+ only, is what lets a moderator touch anyone's).
                "comments.comment:create", "comments.comment:read",
                "comments.comment:update", "comments.comment:delete",
            }) | _OPERATIONAL,
        ),
    )


#: Seeded for every organization, in this order.
ROLE_TEMPLATES: tuple[RoleTemplate, ...] = _templates()
TEMPLATE_BY_CODE: dict[str, RoleTemplate] = {t.code: t for t in ROLE_TEMPLATES}

__all__ = ["ROLE_TEMPLATES", "TEMPLATE_BY_CODE", "RoleTemplate"]
