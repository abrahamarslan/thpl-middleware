"""Organizations business logic — the tenant's legal / hierarchy tree.

Rules (docs/tenancy/README.md §5):

| Rule | Enforced by |
|---|---|
| a node and its parent share a tenant | composite FK ``fk_organizations_parent`` (DB) + tenant-scoped lookup |
| parent type allowed for the node type (``ALLOWED_PARENTS``) | service |
| ``solo`` has no parent and no children | CHECK ``chk_org_solo_rootless`` + service |
| no cycles (never under yourself or a descendant) | service (path prefix test) |
| ``org_code`` unique per tenant among live nodes | partial unique index |
| archive only when every child is archived; delete only a leaf | service |
| Zoho-owned profile fields are read-only on Zoho-linked nodes | service (edit them in Zoho) |
| concurrent edits don't overwrite each other | ``row_version`` (client sends the version it loaded) |

``hierarchy_path`` includes the node itself; moving a node rewrites the path
and depth of its whole subtree in one UPDATE.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.database.tenancy import current_actor
from app.modules.activity.recorder import record_activity
from app.modules.organizations.model import Organization
from app.modules.organizations.schema import (
    OrganizationCreate,
    OrganizationMove,
    OrganizationStatusChange,
    OrganizationUpdate,
)
from app.modules.tenants.enums import ALLOWED_PARENTS, OrganizationStatus, OrganizationType

logger = structlog.get_logger("app.organizations")

#: Profile fields the Zoho sync owns on a Zoho-linked node.
ZOHO_OWNED_FIELDS = frozenset({
    "name", "contact_name", "email", "phone", "website", "industry_type", "industry_size",
    "language_code", "date_format", "fiscal_year_start_month",
    "address_street1", "address_street2", "address_city", "address_state", "address_country", "address_zip",
})


class OrganizationRuleError(AppError):
    status_code = 422
    code = "organization_rule_violation"


# ── reads ───────────────────────────────────────────────────────────────────

def _by_ref(ref: str):
    """uuid, org_code or numeric id."""
    try:
        return Organization.uuid == uuid.UUID(str(ref))
    except ValueError:
        if str(ref).isdigit():
            return Organization.id == int(ref)
        return Organization.org_code == str(ref)


async def get_organization(db: AsyncSession, ref: str | uuid.UUID) -> Organization:
    org = await db.scalar(select(Organization).where(_by_ref(str(ref))).limit(1))
    if org is None:
        raise NotFoundError(f"Organization '{ref}' not found")
    return org


async def list_organizations(
    db: AsyncSession, *, status: str | None = None, org_type: str | None = None, q: str | None = None,
    roots_only: bool = False,
) -> list[Organization]:
    stmt = select(Organization).order_by(Organization.hierarchy_path)
    if status:
        stmt = stmt.where(Organization.status == status)
    if org_type:
        stmt = stmt.where(Organization.org_type == org_type)
    if roots_only:
        stmt = stmt.where(Organization.parent_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Organization.legal_name.ilike(like) | Organization.org_code.ilike(like)
            | Organization.trading_name.ilike(like) | Organization.name.ilike(like)
        )
    return list((await db.scalars(stmt)).all())


async def children(db: AsyncSession, org: Organization) -> list[Organization]:
    return list((await db.scalars(
        select(Organization).where(Organization.parent_id == org.id).order_by(Organization.org_code)
    )).all())


async def subtree(db: AsyncSession, org: Organization) -> list[Organization]:
    """The node and all its descendants (path-prefix scan), in tree order."""
    return list((await db.scalars(
        select(Organization)
        .where(Organization.tenant_id == org.tenant_id, Organization.hierarchy_path.startswith(org.hierarchy_path))
        .order_by(Organization.hierarchy_path)
    )).all())


async def ancestors(db: AsyncSession, org: Organization) -> list[Organization]:
    """Root first, excluding the node itself."""
    chain = org.path_uuids[:-1]
    if not chain:
        return []
    rows = (await db.scalars(select(Organization).where(Organization.uuid.in_(chain)))).all()
    order = {u: i for i, u in enumerate(chain)}
    return sorted(rows, key=lambda o: order[o.uuid])


def build_tree(nodes: list[Organization]) -> list[dict]:
    """Nest a path-ordered node list: [{…node, children: […]}]."""
    from app.modules.organizations.schema import OrganizationNode

    by_uuid: dict[uuid.UUID, OrganizationNode] = {}
    roots: list[OrganizationNode] = []
    for org in sorted(nodes, key=lambda o: o.hierarchy_path):
        node = OrganizationNode.model_validate(org)
        by_uuid[org.uuid] = node
        parent = by_uuid.get(org.parent_uuid) if org.parent_uuid else None
        (parent.children if parent else roots).append(node)
    return roots


# ── writes ──────────────────────────────────────────────────────────────────

async def _resolve_parent(db: AsyncSession, parent_ref: uuid.UUID | None) -> Organization | None:
    if parent_ref is None:
        return None
    parent = await db.scalar(select(Organization).where(Organization.uuid == parent_ref))
    if parent is None:
        raise NotFoundError(f"Parent organization '{parent_ref}' not found")
    return parent


def _check_placement(org_type: OrganizationType, parent: Organization | None) -> None:
    parent_type = OrganizationType(parent.org_type) if parent else None
    if parent_type not in ALLOWED_PARENTS[org_type]:
        allowed = sorted(t.value if t else "root" for t in ALLOWED_PARENTS[org_type])
        raise OrganizationRuleError(
            f"A {org_type.value} cannot be placed under "
            f"{'the root' if parent is None else 'a ' + parent_type.value}; allowed: {', '.join(allowed)}",
        )
    if parent is not None and parent.status == OrganizationStatus.ARCHIVED.value:
        raise OrganizationRuleError(f"Parent '{parent.org_code}' is archived")


async def _ensure_code_free(db: AsyncSession, code: str, *, except_id: int | None = None) -> None:
    stmt = select(Organization.id).where(func.lower(Organization.org_code) == code.lower())
    if except_id is not None:
        stmt = stmt.where(Organization.id != except_id)
    if await db.scalar(stmt.limit(1)):
        raise ConflictError(f"Organization code '{code}' is already used in this tenant")


def _check_version(org: Organization, seen: int) -> None:
    if org.row_version != seen:
        raise ConflictError(
            f"Organization '{org.org_code}' changed since you loaded it (version {seen} → {org.row_version}); "
            "reload and retry",
            data={"current_row_version": org.row_version},
        )


async def create_organization(db: AsyncSession, body: OrganizationCreate, *, actor_id: int | None) -> Organization:
    parent = await _resolve_parent(db, body.parent)
    _check_placement(body.org_type, parent)
    await _ensure_code_free(db, body.org_code)

    values = body.model_dump(exclude={"parent"}, exclude_none=True)
    values["org_type"] = body.org_type.value
    org = Organization(**values, uuid=uuid.uuid4())
    if parent is not None:
        org.tenant_id = parent.tenant_id
        org.parent_id = parent.id
        org.hierarchy_path = f"{parent.hierarchy_path}{org.uuid}/"
        org.depth = parent.depth + 1
    db.add(org)
    await db.flush()
    await record_activity(
        db, action="organization_created", actor_id=actor_id, subject_type="Organization", subject_id=org.id,
        changes={"after": {"org_code": org.org_code, "org_type": org.org_type,
                           "parent": str(parent.uuid) if parent else None}},
    )
    logger.info("organizations.created", org_id=org.id, code=org.org_code, parent=parent.org_code if parent else None)
    return org


async def update_organization(
    db: AsyncSession, ref: str, body: OrganizationUpdate, *, actor_id: int | None,
) -> Organization:
    org = await get_organization(db, ref)
    _check_version(org, body.row_version)
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if org.is_zoho_linked:
        blocked = sorted(set(changes) & ZOHO_OWNED_FIELDS)
        if blocked:
            raise OrganizationRuleError(
                f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} owned by Zoho for this organization "
                f"(zoho_id {org.zoho_id}); change {'it' if len(blocked) == 1 else 'them'} in Zoho — the next sync "
                "brings it here",
                data={"zoho_owned": blocked},
            )
    if "org_code" in changes and changes["org_code"] != org.org_code:
        await _ensure_code_free(db, changes["org_code"], except_id=org.id)
    before = {k: getattr(org, k) for k in changes}
    for field, value in changes.items():
        setattr(org, field, value)
    await db.flush()
    await record_activity(
        db, action="organization_updated", actor_id=actor_id, subject_type="Organization", subject_id=org.id,
        changes={"before": {k: _jsonable(v) for k, v in before.items()},
                 "after": {k: _jsonable(v) for k, v in changes.items()}},
    )
    return org


async def move_organization(db: AsyncSession, ref: str, body: OrganizationMove, *, actor_id: int | None) -> Organization:
    org = await get_organization(db, ref)
    _check_version(org, body.row_version)
    parent = await _resolve_parent(db, body.parent)
    if parent is not None and parent.hierarchy_path.startswith(org.hierarchy_path):
        raise OrganizationRuleError("An organization cannot be moved under itself or one of its descendants")
    _check_placement(OrganizationType(org.org_type), parent)
    if parent is not None and parent.org_type == OrganizationType.SOLO.value:
        raise OrganizationRuleError("A solo organization cannot have children")
    if (parent.id if parent else None) == org.parent_id:
        return org

    old_path, old_depth = org.hierarchy_path, org.depth
    new_path = f"{parent.hierarchy_path if parent else '/'}{org.uuid}/"
    new_depth = parent.depth + 1 if parent else 0
    org.parent_id = parent.id if parent else None
    org.hierarchy_path, org.depth = new_path, new_depth
    await db.flush()
    # Rewrite every descendant in one statement (Core UPDATE: bump row_version explicitly).
    await db.execute(
        update(Organization)
        .where(
            Organization.tenant_id == org.tenant_id,
            Organization.hierarchy_path.startswith(old_path),
            Organization.id != org.id,
        )
        .values(
            hierarchy_path=func.concat(new_path, func.substr(Organization.hierarchy_path, len(old_path) + 1)),
            depth=Organization.depth + (new_depth - old_depth),
            row_version=Organization.row_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    await record_activity(
        db, action="organization_moved", actor_id=actor_id, subject_type="Organization", subject_id=org.id,
        changes={"before": {"path": old_path}, "after": {"path": new_path}},
    )
    logger.info("organizations.moved", org_id=org.id, old_path=old_path, new_path=new_path)
    return org


async def change_status(
    db: AsyncSession, ref: str, body: OrganizationStatusChange, *, actor_id: int | None,
) -> Organization:
    """active ↔ suspended → archived. Suspending/archiving records the
    deactivation (who, when, why); re-activating clears it."""
    org = await get_organization(db, ref)
    target = body.status
    if target is OrganizationStatus.ARCHIVED:
        open_children = await db.scalar(
            select(func.count()).select_from(Organization).where(
                and_(Organization.parent_id == org.id, Organization.status != OrganizationStatus.ARCHIVED.value)
            )
        )
        if open_children:
            raise OrganizationRuleError(
                f"Archive the {open_children} child organization(s) of '{org.org_code}' first"
            )
    if target is not OrganizationStatus.ACTIVE and not body.reason:
        raise OrganizationRuleError("A reason is required to suspend or archive an organization")
    before = org.status
    org.status = target.value
    if target is OrganizationStatus.ACTIVE:
        org.reactivate()
    else:
        org.deactivate(reason=body.reason, by=actor_id if actor_id is not None else current_actor().user_id)
    await db.flush()
    await record_activity(
        db, action="organization_status_changed", actor_id=actor_id, subject_type="Organization",
        subject_id=org.id, changes={"before": {"status": before}, "after": {"status": org.status}},
        context={"reason": body.reason},
    )
    return org


async def delete_organization(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None) -> None:
    org = await get_organization(db, ref)
    if await db.scalar(select(func.count()).select_from(Organization).where(Organization.parent_id == org.id)):
        raise OrganizationRuleError(f"'{org.org_code}' still has child organizations; move or delete them first")
    if org.is_zoho_linked:
        raise OrganizationRuleError(
            f"'{org.org_code}' is linked to Zoho organization {org.zoho_id}; archive it instead "
            "(the sync would recreate it)"
        )
    org.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="organization_deleted", actor_id=actor_id, subject_type="Organization", subject_id=org.id,
        context={"reason": reason},
    )


def trigger_zoho_sync(mode: str | None = None) -> str:
    """Pull the Zoho organization(s) into the tree now (leased manual lane)."""
    from app.tasks.zoho_sync import sync_module

    return sync_module.delay("organizations", mode).id


def _jsonable(value):
    return value if isinstance(value, (str, int, float, bool, type(None), dict, list)) else str(value)
