"""HTTP endpoints of the resolution engine (mounted at /api/resolution).

| Endpoint | What |
|---|---|
| ``GET    /facets`` | every facet, its filters, context schema and code-default policies |
| ``GET    /policies/{facet}/{subject}`` | the EFFECTIVE policy for the request's organization (with its layer) |
| ``PUT    /policies/{facet}/{subject}`` | override it — ``scope=organization`` (default) or ``tenant`` |
| ``DELETE /policies/{facet}/{subject}`` | drop the override at that scope |
| ``POST   /{facet}/{subject}/resolve`` | resolve a batch of subjects (``explain=true`` adds the trace) |

Owners are ``{type, id}``: a ``core.entity_types`` code and the owner's internal id — the
``/api/taxes/assignments`` convention.
"""

from typing import Literal

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database import scope as org_scope
from app.database.db import DBSession
from app.modules.rbac.deps import Perm
from app.modules.resolution import engine, service
from app.modules.resolution.registry import resolution_registry
from app.modules.resolution.schema import FacetOut, PolicyOut, PolicyPut, ResolutionOut, ResolveRequest
from app.modules.resolution.types import OwnerRef, Subject
from app.modules.users.deps import CurrentUser

router = APIRouter()

_M = "resolution"


@router.get("/facets", response_model=ResponseModel[list[FacetOut]])
async def list_facets(_: CurrentUser):
    return ResponseModel(data=[
        FacetOut(code=f.code, description=f.description, filters=sorted(f.filters),
                 context_schema=f.context_model.model_json_schema(),
                 policies=[PolicyOut.of(p) for p in resolution_registry.policies(f.code)])
        for f in resolution_registry.facets()
    ])


async def _scope_org(db, scope_name: str) -> int | None:
    return None if scope_name == "tenant" else await org_scope.require_organization_id(db)


@router.get("/policies/{facet}/{subject}", response_model=ResponseModel[PolicyOut])
async def get_policy(_: CurrentUser, db: DBSession, facet: str, subject: str):
    org = await org_scope.require_organization_id(db)
    return ResponseModel(data=PolicyOut.of(await service.effective(db, facet, subject, org)))


@router.put("/policies/{facet}/{subject}", response_model=ResponseModel[PolicyOut])
async def put_policy(
    user: Perm("resolution.policy:manage"), db: DBSession, facet: str, subject: str, body: PolicyPut,
    scope: Literal["organization", "tenant"] = Query("organization"),
):
    policy = await service.put_override(
        db, facet, subject, steps=[s.to_step() for s in body.steps],
        use_organization_default=body.use_organization_default, organization_id=await _scope_org(db, scope),
        notes=body.notes, actor_id=user.id,
    )
    return ResponseModel.ok(data=PolicyOut.of(policy), module=_M, msg_key="resolution_policy_saved",
                            msg="Resolution policy saved")


@router.delete("/policies/{facet}/{subject}", response_model=ResponseModel[PolicyOut])
async def delete_policy(
    user: Perm("resolution.policy:manage"), db: DBSession, facet: str, subject: str,
    scope: Literal["organization", "tenant"] = Query("organization"),
):
    policy = await service.delete_override(db, facet, subject, organization_id=await _scope_org(db, scope),
                                           actor_id=user.id)
    return ResponseModel.ok(data=PolicyOut.of(policy), module=_M, msg_key="resolution_policy_reset",
                            msg="Resolution policy reset")


@router.post("/{facet}/{subject}/resolve", response_model=ResponseModel[list[ResolutionOut]])
async def resolve(_: CurrentUser, db: DBSession, facet: str, subject: str, body: ResolveRequest):
    default_org: int | None = None
    if any(s.organization_id is None for s in body.subjects):
        default_org = await org_scope.require_organization_id(db)
    subjects = [
        Subject(
            roles={role: (None if owner is None else
                          [OwnerRef(o.type, o.id) for o in owner] if isinstance(owner, list)
                          else OwnerRef(owner.type, owner.id))
                   for role, owner in s.roles.items()},
            organization_id=s.organization_id or default_org,
            context=s.context,
        )
        for s in body.subjects
    ]
    facet_impl = resolution_registry.facet(facet)
    results = await engine.resolve_many(db, facet, subject, subjects, explain=body.explain)
    return ResponseModel(data=[ResolutionOut.of(r, [facet_impl.describe(v) for v in r.values]) for r in results])
