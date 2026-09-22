"""The irreducible bits of the tax adapter.

Everything expressible as a field rule lives in ``fields.py``. What is left is
procedural:

  * ``enforce_group_shape`` — a row synced through ``/settings/taxgroups`` IS a
    group, whatever the payload says about ``tax_type``;
  * ``project_group_members`` — turn ``taxes[]`` into ``tax_group_members`` rows;
  * ``grant_to_context_organization`` — record that the organization whose
    connection synced a component may use it.

Nothing here matches on a source id column: the crosswalk is the identity of
record, and members are resolved through it (``sync.crosswalk.resolve_many``).
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session

from app.database.tenancy import current_organization_id
from app.modules.sync.crosswalk import resolve_many
from app.modules.taxes.component import TaxComponent, TaxGroupMember
from app.modules.taxes.enums import TAX_SCHEMA, TaxType
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.zoho.translator import TAX_GROUP_TRANSLATOR

logger = structlog.get_logger("app.taxes.zoho")

#: The crosswalk module that owns leaf components — group members reference it.
MEMBER_MODULE = "taxes"
_COMPONENT_TABLE = f"{TAX_SCHEMA}.tax_components"


class TaxGroupError(ValueError):
    """A group payload cannot be projected yet (or ever).

    Raised, not swallowed: it fails the record, the engine rolls the record's
    transaction back — crosswalk row included — and the next attempt is judged
    afresh instead of being skipped as "unchanged". That is the retry the field
    catalog calls quarantine (``stage='reference'``): a group is never silently
    linked to fewer members than the source lists.
    """


def enforce_group_shape(payload: dict, values: dict[str, Any]) -> dict[str, Any]:
    """A group is a ``tax_group`` with no specific leg (``chk_tax_components_group_no_specific_type``)."""
    return {**values, "tax_type": TaxType.TAX_GROUP.value, "tax_specific_type": None}


async def grant_to_context_organization(component: TaxComponent, payload: dict) -> None:
    """Grant the sync's organization the use of this component.

    A Zoho settings record belongs to the Zoho organization the connection is
    for, so the organization in context is the one that should see it. Without
    one (a tenant-level run) there is nobody to grant, and that is not an error.

    A grant that exists in ANY state — including soft-deleted — is left alone: an
    operator who revoked an organization's access has made a decision the sync
    must not undo, the same rule the apply gate applies to a locally deleted row.
    """
    organization_id = current_organization_id()
    db = async_object_session(component)
    if organization_id is None or db is None or component.id is None:
        return
    existing = await db.scalar(
        select(OrganizationTaxComponent.id).where(
            OrganizationTaxComponent.tenant_id == component.tenant_id,
            OrganizationTaxComponent.organization_id == organization_id,
            OrganizationTaxComponent.tax_component_id == component.id,
        ).execution_options(include_deleted=True).limit(1)
    )
    if existing is None:
        db.add(OrganizationTaxComponent(
            tenant_id=component.tenant_id, organization_id=organization_id,
            tax_component_id=component.id,
        ))
        await db.flush()


async def _resolve_members(db: AsyncSession, group: TaxComponent, external_ids: list[str]) -> dict[str, int]:
    """External tax id → local component id, in one crosswalk query; all or raise."""
    if not external_ids:
        return {}
    rows = (await db.execute(resolve_many(
        tenant_id=group.tenant_id, source_system="zoho",
        pairs=[(MEMBER_MODULE, external_id) for external_id in external_ids],
    ))).all()
    resolved = {
        external_id: entity_id
        for _module, external_id, entity_table, entity_id, _state in rows
        if entity_table == _COMPONENT_TABLE and entity_id is not None
    }
    missing = [external_id for external_id in external_ids if external_id not in resolved]
    if missing:
        raise TaxGroupError(
            f"tax group {group.tax_name!r} lists member taxes that are not synced yet: {missing}"
        )

    kinds = dict((await db.execute(
        select(TaxComponent.id, TaxComponent.tax_type).where(TaxComponent.id.in_(set(resolved.values())))
    )).all())
    nested = sorted(external_id for external_id, local_id in resolved.items()
                    if kinds.get(local_id) == TaxType.TAX_GROUP.value)
    if nested:
        raise TaxGroupError(f"tax group {group.tax_name!r} lists tax groups as members: {nested}")
    gone = sorted(external_id for external_id, local_id in resolved.items() if local_id not in kinds)
    if gone:
        raise TaxGroupError(f"tax group {group.tax_name!r} lists deleted member taxes: {gone}")
    return resolved


async def project_group_members(group: TaxComponent, payload: dict) -> None:
    """Make ``tax_group_members`` match the payload's ``taxes[]``.

    A payload without a ``taxes`` array says nothing about membership and
    changes nothing; an empty array is a real statement (the group has no
    members) and soft-deletes them all. Memberships that left the array are
    soft-deleted, never hard-deleted — the row may be referenced by history.
    """
    db = async_object_session(group)
    if db is None or group.id is None:
        return
    desired = TAX_GROUP_TRANSLATOR.decode(payload).children.get("members")
    if desired is None:
        return

    resolved = await _resolve_members(db, group, [entry["tax_id"] for entry in desired])
    wanted = {resolved[entry["tax_id"]]: entry["position"] for entry in desired}

    existing = {
        row.member_tax_id: row
        for row in (await db.scalars(
            select(TaxGroupMember).where(TaxGroupMember.tax_group_id == group.id)
        )).all()
    }
    for member_id, position in wanted.items():
        row = existing.get(member_id)
        if row is None:
            db.add(TaxGroupMember(
                tenant_id=group.tenant_id, tax_group_id=group.id,
                member_tax_id=member_id, position=position,
            ))
        elif row.position != position:
            row.position = position
    for member_id, row in existing.items():
        if member_id not in wanted:
            row.soft_delete(reason="no longer listed by the source")
    await db.flush()
    logger.info("taxes.group.members_projected", group_id=group.id, members=len(wanted),
                removed=len(existing.keys() - wanted.keys()))


async def after_tax_group(group: TaxComponent, payload: dict) -> None:
    await project_group_members(group, payload)
    await grant_to_context_organization(group, payload)


__all__ = [
    "MEMBER_MODULE",
    "TaxGroupError",
    "after_tax_group",
    "enforce_group_shape",
    "grant_to_context_organization",
    "project_group_members",
]
