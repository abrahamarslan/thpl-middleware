"""HTTP endpoints for tax assignments (mounted at /api/taxes/assignments).

| Endpoint | What |
|---|---|
| ``GET  /taxable-types`` | which entity classes may carry taxes, and their rule |
| ``GET  /resolve`` | which tax applies for a chain of owners in a context |
| ``GET  /{owner_type}/{owner_id}`` | one owner's taxes |
| ``PUT  /{owner_type}/{owner_id}`` | replace the owner's LOCAL taxes (a source's rows are read-only) |
| ``DELETE /{ref}`` | remove one local assignment |

``owner_type`` is a ``core.entity_types`` code (``category``, later ``item`` …) and
``owner_id`` the owner's internal id. Modules that own an entity usually expose the
same thing through their own resource (categories: ``tax_preferences``); these are
the generic form, and what a UI uses for a class that has no resource of its own.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.rbac.deps import Perm, org_of
from app.modules.taxes import assignment_service as service
from app.modules.taxes.assignment_schema import (
    TaxableEntityTypeOut,
    TaxAssignmentOut,
    TaxAssignmentsReplace,
    TaxResolutionOut,
)
from app.modules.taxes.enums import TaxSpecification, TaxTransactionType
from app.modules.taxes.schema import TaxComponentSlimOut, TaxExemptionOut
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "taxes"


def _parse_owners(raw: list[str]) -> list[tuple[str, int]]:
    owners: list[tuple[str, int]] = []
    for item in raw:
        owner_type, _, owner_id = item.partition(":")
        if not owner_type or not owner_id.isdigit():
            raise service.TaxRuleError(f"owner must look like 'category:5', got '{item}'")
        owners.append((owner_type, int(owner_id)))
    return owners


@router.get("/taxable-types", response_model=ResponseModel[list[TaxableEntityTypeOut]])
async def list_taxable_types(_: CurrentUser, db: DBSession):
    rows = await service.list_policies(db)
    return ResponseModel(data=[TaxableEntityTypeOut.model_validate(r) for r in rows])


@router.get("/resolve", response_model=ResponseModel[TaxResolutionOut])
async def resolve(
    _: CurrentUser, db: DBSession,
    owner: list[str] = Query(..., description="Most specific first, e.g. owner=item:4&owner=category:2"),
    specification: TaxSpecification | None = Query(None),
    transaction_type: TaxTransactionType | None = Query(None),
    organization_id: int | None = Query(None, description="For the organization-default fallback"),
):
    result = await service.resolve_taxes(
        db, _parse_owners(owner),
        specification=specification.value if specification else None,
        transaction_type=transaction_type.value if transaction_type else None,
        organization_id=organization_id,
    )
    origin = result.resolved_from
    return ResponseModel(data=TaxResolutionOut(
        via=result.via,
        resolved_from_type=origin[0] if origin else None,
        resolved_from_id=origin[1] if origin else None,
        taxes=[TaxComponentSlimOut.model_validate(c) for c in result.components],
        exemptions=[TaxExemptionOut.model_validate(e) for e in result.exemptions],
    ))


@router.get("/{owner_type}/{owner_id}", response_model=ResponseModel[list[TaxAssignmentOut]])
async def list_assignments(_: CurrentUser, db: DBSession, owner_type: str, owner_id: int):
    rows = await service.list_assignments(db, owner_type, owner_id)
    return ResponseModel(data=[TaxAssignmentOut.model_validate(r) for r in rows])


@router.put("/{owner_type}/{owner_id}", response_model=ResponseModel[list[TaxAssignmentOut]])
async def replace_assignments(user: Perm("tax.assignment:manage"), db: DBSession, owner_type: str, owner_id: int,
                              body: TaxAssignmentsReplace):
    specs = await service.specs_from_items(db, body.items)
    rows = await service.replace_assignments(db, owner_type, owner_id, specs, actor_id=user.id)
    return ResponseModel.ok(data=[TaxAssignmentOut.model_validate(r) for r in rows], module=_M,
                            msg_key="tax_assignments_replaced", msg="Taxes updated", name=f"{owner_type}:{owner_id}")


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_assignment(admin: Perm("tax.assignment:manage", target=org_of("app.modules.taxes.assignment:TaxAssignment")), db: DBSession, ref: str,
                            reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_assignment(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="tax_assignment_deleted",
                            msg="Tax assignment removed", name=ref)
