"""HTTP endpoints for emails (mounted at /api/emails)."""

from fastapi import APIRouter, Query, Request

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.emails import crud, schema, service
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.post("/send", response_model=ResponseModel[schema.EmailOut], status_code=202)
async def send_email(user: CurrentUser, db: DBSession, email_in: schema.EmailCreate):
    """Compose + persist + queue for async delivery via Resend."""
    email = await service.compose_and_queue_email(db, email_in, actor_id=user.id)
    full = await crud.get_email(db, email.id)  # eager-load documents for the response
    return ResponseModel(data=schema.EmailOut.model_validate(full), msg="Email queued")


@router.get("", response_model=ResponseModel[list[schema.EmailOut]])
async def list_emails(
    _: CurrentUser,
    db: DBSession,
    status: str | None = Query(None),
    recipient: str | None = Query(None, description="Matches To/CC/BCC"),
    emailable_type: str | None = Query(None),
    emailable_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    emails = await crud.list_emails(
        db, status=status, recipient=recipient,
        emailable_type=emailable_type, emailable_id=emailable_id,
        page=page, page_size=page_size,
    )
    return ResponseModel(data=[schema.EmailOut.model_validate(e) for e in emails])


@router.get("/{email_id}", response_model=ResponseModel[schema.EmailOut])
async def get_email(_: CurrentUser, db: DBSession, email_id: int):
    email = await service.get_email(db, email_id)
    return ResponseModel(data=schema.EmailOut.model_validate(email))


@router.post("/webhooks/resend", include_in_schema=False)
async def resend_webhook(request: Request, db: DBSession):
    """Resend event sink (delivered/opened/clicked/bounced). Unauthenticated
    endpoint — protected by svix signature verification instead of JWT."""
    body = await request.body()
    service.verify_resend_signature(body, {k.lower(): v for k, v in request.headers.items()})
    payload = await request.json()
    await service.process_resend_webhook(db, payload)
    return {"status": "received"}
