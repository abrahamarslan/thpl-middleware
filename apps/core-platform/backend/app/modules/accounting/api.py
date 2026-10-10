"""HTTP endpoints of the accounting module (mounted at /api/accounting).

| Endpoint | What |
|---|---|
| ``GET    /account-types`` | the 46 account types (global) |
| ``GET    /purposes`` · ``GET /purpose-policies`` | why an entity points at an account; which classes may |
| ``GET    /accounts`` | Slim list — filters ``group``, ``type``, ``usage`` (sales/purchase/inventory pickers), ``status``, ``parent_id``, ``q``; ``tree=true`` nests it |
| ``GET    /accounts/{ref}`` | Fat detail (``ref`` = id or uuid) |
| ``POST   /accounts`` · ``PATCH /accounts/{ref}`` | local writes (refused on a Zoho-mastered chart / Zoho-owned fields) |
| ``POST   /accounts/{ref}/activate`` · ``/deactivate`` | the one lifecycle switch |
| ``DELETE /accounts/{ref}`` | soft delete; refused while in use |
| ``GET    /chart-violations`` | Zoho-side breaches of Zoho's own sub-account rules (reported, not refused) |
| ``GET    /assignments/{owner_type}/{owner_id}`` | one owner's accounts |
| ``PUT    /assignments/{owner_type}/{owner_id}`` | replace the owner's LOCAL accounts (a source's rows are read-only) |

"Which account applies to this line?" is the resolution engine:
``POST /api/resolution/account/{subject}/resolve``.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database import scope
from app.database.db import DBSession
from app.modules.accounting import assignment_service, crud, service
from app.modules.accounting.enums import AccountGroup, AccountStatus, AccountUsage
from app.modules.accounting.schema import (
    AccountAssignmentOut,
    AccountAssignmentsReplace,
    AccountCreate,
    AccountOut,
    AccountPurposeOut,
    AccountPurposePolicyOut,
    AccountSlimOut,
    AccountTreeNode,
    AccountTypeOut,
    AccountUpdate,
    ChartViolationOut,
)
from app.modules.rbac.deps import Perm, org_of
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "accounting"
_ACCOUNT_TARGET = org_of("app.modules.accounting.model:Account")


async def _fat(db, account) -> AccountOut:
    return AccountOut.model_validate({**AccountOut.model_validate(account).model_dump(),
                                      **await service.describe(db, account)})


# ── reference data ────────────────────────────────────────────────────────────

@router.get("/account-types", response_model=ResponseModel[list[AccountTypeOut]])
async def list_account_types(_: CurrentUser, db: DBSession, enabled_only: bool = Query(False)):
    return ResponseModel(data=[AccountTypeOut.model_validate(t) for t in await crud.list_types(
        db, enabled_only=enabled_only)])


@router.get("/purposes", response_model=ResponseModel[list[AccountPurposeOut]])
async def list_purposes(_: CurrentUser, db: DBSession):
    return ResponseModel(data=[AccountPurposeOut.model_validate(p) for p in await crud.list_purposes(db)])


@router.get("/purpose-policies", response_model=ResponseModel[list[AccountPurposePolicyOut]])
async def list_purpose_policies(_: CurrentUser, db: DBSession, entity_type: str | None = Query(None)):
    return ResponseModel(data=[AccountPurposePolicyOut.model_validate(p)
                               for p in await crud.list_policies(db, entity_type)])


# ── accounts ──────────────────────────────────────────────────────────────────

@router.get("/accounts", response_model=ResponseModel[list[AccountSlimOut] | list[AccountTreeNode]])
async def list_accounts(
    _: CurrentUser, db: DBSession,
    group: AccountGroup | None = Query(None),
    type: str | None = Query(None, max_length=64),  # noqa: A002 — the API's vocabulary
    usage: AccountUsage | None = Query(None, description="sales / purchase / inventory picker"),
    status: AccountStatus | None = Query(None),
    parent_id: int | None = Query(None, gt=0),
    q: str | None = Query(None, max_length=200),
    tree: bool = Query(False, description="Nest the result into roots with children"),
    page: int = Query(1, ge=1),
    page_size: int = Query(500, ge=1, le=2000),
):
    rows = await crud.list_accounts_slim(
        db, group=group.value if group else None, account_type=type, usage=usage,
        status=status.value if status else None, parent_id=parent_id, q=q,
        limit=None if tree else page_size, offset=0 if tree else (page - 1) * page_size,
    )
    if tree:
        return ResponseModel(data=[AccountTreeNode.model_validate(node) for node in service.build_tree(rows)])
    return ResponseModel(data=[AccountSlimOut.model_validate(r) for r in rows])


@router.get("/accounts/{ref}", response_model=ResponseModel[AccountOut])
async def get_account(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=await _fat(db, await service.get_account(db, ref)))


@router.post("/accounts", response_model=ResponseModel[AccountOut], status_code=201)
async def create_account(user: Perm("accounting.account:create"), db: DBSession, body: AccountCreate):
    account = await service.create_account(db, body, actor_id=user.id)
    return ResponseModel.ok(data=await _fat(db, account), module=_M, msg_key="account_created",
                            msg="Account created", name=account.display_name)


@router.patch("/accounts/{ref}", response_model=ResponseModel[AccountOut])
async def update_account(user: Perm("accounting.account:update", target=_ACCOUNT_TARGET), db: DBSession, ref: str,
                         body: AccountUpdate):
    account = await service.update_account(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=await _fat(db, account), module=_M, msg_key="account_updated",
                            msg="Account updated", name=account.display_name)


@router.post("/accounts/{ref}/activate", response_model=ResponseModel[AccountOut])
async def activate_account(user: Perm("accounting.account:update", target=_ACCOUNT_TARGET), db: DBSession, ref: str):
    account = await service.set_status(db, ref, AccountStatus.ACTIVE.value, actor_id=user.id)
    return ResponseModel(data=await _fat(db, account))


@router.post("/accounts/{ref}/deactivate", response_model=ResponseModel[AccountOut])
async def deactivate_account(user: Perm("accounting.account:update", target=_ACCOUNT_TARGET), db: DBSession,
                             ref: str):
    account = await service.set_status(db, ref, AccountStatus.INACTIVE.value, actor_id=user.id)
    return ResponseModel(data=await _fat(db, account))


@router.delete("/accounts/{ref}", response_model=ResponseModel[None])
async def delete_account(user: Perm("accounting.account:delete", target=_ACCOUNT_TARGET), db: DBSession, ref: str,
                         reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_account(db, ref, reason=reason, actor_id=user.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="account_deleted", msg="Account deleted", name=ref)


@router.get("/chart-violations", response_model=ResponseModel[list[ChartViolationOut]])
async def chart_violations(_: CurrentUser, db: DBSession):
    organization_id = await scope.require_organization_id(db)
    return ResponseModel(data=[ChartViolationOut(**v)
                               for v in await service.find_chart_violations(db, organization_id)])


# ── assignments ───────────────────────────────────────────────────────────────

@router.get("/assignments/{owner_type}/{owner_id}", response_model=ResponseModel[list[AccountAssignmentOut]])
async def list_assignments(_: CurrentUser, db: DBSession, owner_type: str, owner_id: int):
    rows = await assignment_service.list_assignments(db, owner_type, owner_id)
    return ResponseModel(data=[AccountAssignmentOut.model_validate(r) for r in rows])


@router.put("/assignments/{owner_type}/{owner_id}", response_model=ResponseModel[list[AccountAssignmentOut]])
async def replace_assignments(user: Perm("accounting.assignment:manage"), db: DBSession, owner_type: str,
                              owner_id: int, body: AccountAssignmentsReplace):
    specs = await assignment_service.specs_from_items(db, body.items)
    rows = await assignment_service.put_assignments(db, owner_type, owner_id, specs,
                                                    organization_id=body.organization_id, actor_id=user.id)
    return ResponseModel.ok(data=[AccountAssignmentOut.model_validate(r) for r in rows], module=_M,
                            msg_key="account_assignments_replaced", msg="Accounts updated",
                            name=f"{owner_type}:{owner_id}")
