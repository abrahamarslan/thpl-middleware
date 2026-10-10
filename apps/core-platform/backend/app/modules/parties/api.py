"""HTTP endpoints of the parties module (mounted at /api/parties) — customers and vendors.

| Endpoint | What |
|---|---|
| ``GET /`` | Slim page — ``type`` (customer/vendor), ``status``, ``sub_type``, ``place_of_supply``, ``q`` (name / company, last-10-digit mobile, exact GSTIN or PAN) |
| ``GET /{ref}`` | Fat: persons, current addresses (with coordinates), registrations, payment term, custom fields |
| ``GET /{ref}/persons`` | The party's contact persons with their addresses and avatars |
| ``GET /persons/{ref}`` | One contact person |
| ``POST /persons/{ref}/avatar`` · ``DELETE`` | The person's avatar (media collection ``avatar``) |
| ``GET /payment-terms`` | Payment terms as Zoho names them |

Addresses (``/api/addresses?owner_type=party|contact_person``), documents, comments, custom-field values
and the sub-category (``/api/categorizables``, taxonomy ``customer_sub_category``) use their own modules'
APIs. Organization scope is the request's (``X-Organization-Code``; THPL by default).
"""

from fastapi import APIRouter, File, Query, Response, UploadFile

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.media import service as media_service
from app.modules.media.schema import AvatarOut
from app.modules.parties import crud, service
from app.modules.parties.enums import CustomerSubType, PartyStatus, PartyType
from app.modules.parties.schema import ContactPersonOut, PartyOut, PartyPage, PartySlimOut, PaymentTermOut
from app.modules.rbac.deps import Perm
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[PartyPage])
async def list_parties(
    _: CurrentUser, db: DBSession,
    type: PartyType | None = Query(None),  # noqa: A002 — the API's vocabulary
    status: PartyStatus | None = Query(None),
    sub_type: CustomerSubType | None = Query(None),
    place_of_supply: str | None = Query(None, max_length=4),
    q: str | None = Query(None, min_length=2, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    rows, total = await crud.list_parties(
        db, party_type=type.value if type else None, status=status.value if status else None,
        customer_sub_type=sub_type.value if sub_type else None, place_of_supply=place_of_supply, q=q,
        limit=page_size, offset=(page - 1) * page_size,
    )
    return ResponseModel(data=PartyPage(items=[PartySlimOut.model_validate(r) for r in rows], total=total,
                                        page=page, page_size=page_size))


@router.get("/payment-terms", response_model=ResponseModel[list[PaymentTermOut]])
async def list_payment_terms(_: CurrentUser, db: DBSession):
    return ResponseModel(data=[PaymentTermOut.model_validate(t) for t in await crud.list_payment_terms(db)])


@router.get("/persons/{ref}", response_model=ResponseModel[ContactPersonOut])
async def get_person(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=await service.person_out(db, await service.get_person(db, ref)))


@router.post("/persons/{ref}/avatar", response_model=ResponseModel[AvatarOut], status_code=202)
async def upload_person_avatar(user: Perm("party.contact_person:update"), db: DBSession, ref: str,
                               file: UploadFile = File(...)):
    """Set (or replace) a contact person's avatar (PNG / JPEG / WebP; EXIF/GPS stripped; variants async)."""
    media = await service.replace_person_avatar(db, ref, file, actor_id=user.id)
    return ResponseModel(
        data=AvatarOut(media_id=media.uuid, status=media.status, avatar_urls=media_service.media_urls(media)),
        msg="Avatar uploaded; conversions queued",
    )


@router.delete("/persons/{ref}/avatar", status_code=204)
async def delete_person_avatar(user: Perm("party.contact_person:update"), db: DBSession, ref: str):
    await service.delete_person_avatar(db, ref, actor_id=user.id)
    return Response(status_code=204)


@router.get("/{ref}", response_model=ResponseModel[PartyOut])
async def get_party(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=await service.describe(db, await service.get_party(db, ref, fat=True)))


@router.get("/{ref}/persons", response_model=ResponseModel[list[ContactPersonOut]])
async def list_persons(_: CurrentUser, db: DBSession, ref: str):
    party = await service.get_party(db, ref)
    persons = await crud.persons_of(db, party.id)
    return ResponseModel(data=[await service.person_out(db, p) for p in persons])
