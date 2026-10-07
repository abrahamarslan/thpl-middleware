"""Self-service consent API — mounted at ``/api/me/consents`` (docs/compliance/consents.md)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.common.client_info import ClientInfoDep
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.compliance import consents
from app.modules.compliance.consents import ConsentIn, ConsentOut
from app.modules.compliance.enums import ConsentType
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[list[ConsentOut]])
async def my_consents(user: CurrentUser, db: DBSession, include_inactive: bool = False):
    """My consents (live ones; ``include_inactive`` adds withdrawn and superseded history)."""
    rows = await consents.list_mine(db, user, include_inactive=include_inactive)
    return ResponseModel(data=[ConsentOut.model_validate(r) for r in rows])


@router.post("", response_model=ResponseModel[ConsentOut], status_code=201)
async def give_consent(user: CurrentUser, db: DBSession, body: ConsentIn, client: ClientInfoDep) -> JSONResponse:
    """Record a consent — e.g. ``{"consent_type": "location_tracking", "consent_text_version": "1.0"}`` before
    the first shift. 201 recorded · 200 the same version was already given (idempotent)."""
    row, created = await consents.give(db, user, body, ip=client.ip if client else None)
    payload = ResponseModel(data=ConsentOut.model_validate(row),
                            msg="Consent recorded" if created else "Consent already recorded")
    return JSONResponse(status_code=201 if created else 200, content=payload.model_dump(mode="json"))


@router.post("/{consent_type}/withdraw", response_model=ResponseModel[dict])
async def withdraw_consent(consent_type: ConsentType, user: CurrentUser, db: DBSession):
    """Withdraw a consent. Withdrawing ``location_tracking`` during a shift ENDS that shift."""
    count = await consents.withdraw(db, user, consent_type.value)
    return ResponseModel(data={"withdrawn": count}, msg="Consent withdrawn")


__all__ = ["router"]
