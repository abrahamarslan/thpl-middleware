"""HTTP endpoints for emails (mounted at /api/emails)."""

from datetime import datetime

from fastapi import APIRouter, Query, Request

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.emails import crud, schema, service
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.post("/send", response_model=ResponseModel[schema.EmailOut], status_code=202)
async def send_email(user: CurrentUser, db: DBSession, email_in: schema.EmailCreate, request: Request):
    """Compose + persist + queue for async delivery via Resend."""
    email = await service.compose_and_queue_email(
        db, email_in, actor_id=user.id, user_agent=request.headers.get("user-agent")
    )
    full = await crud.get_email(db, email.id)  # eager-load documents for the response
    return ResponseModel(data=schema.EmailOut.model_validate(full), msg="Email queued")


@router.post("/send-template", response_model=ResponseModel[schema.EmailOut], status_code=202)
async def send_template_email(user: CurrentUser, db: DBSession, body: schema.EmailTemplateSend):
    """Render a registered template and queue it — the reusable send path."""
    email = await service.send_template_email(
        db,
        body.template_name,
        to=list(body.to),
        context=body.context,
        locale=body.locale,
        cc=list(body.cc),
        bcc=list(body.bcc),
        email_from=body.email_from,
        reply_to=body.reply_to,
        emailable_type=body.emailable_type,
        emailable_id=body.emailable_id,
        scheduled_at=body.scheduled_at,
        actor_id=user.id,
    )
    full = await crud.get_email(db, email.id)
    return ResponseModel(data=schema.EmailOut.model_validate(full), msg="Email queued")


@router.get("/stats", response_model=ResponseModel[schema.EmailStatsOut])
async def email_stats(
    _: CurrentUser,
    db: DBSession,
    date_from: datetime | None = Query(None, description="Inclusive lower bound (ISO 8601)"),
    date_to: datetime | None = Query(None, description="Inclusive upper bound (ISO 8601)"),
):
    """Aggregate delivery/engagement analytics for a window."""
    stats = await service.get_email_stats(db, since=date_from, until=date_to)
    return ResponseModel(data=schema.EmailStatsOut(**stats))


@router.get("", response_model=ResponseModel[list[schema.EmailSlimOut]])
async def list_emails(
    _: CurrentUser,
    db: DBSession,
    status: str | None = Query(None),
    recipient: str | None = Query(None, description="Matches To/CC/BCC"),
    emailable_type: str | None = Query(None),
    emailable_id: str | None = Query(None),
    template_name: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    emails = await crud.list_emails(
        db, status=status, recipient=recipient,
        emailable_type=emailable_type, emailable_id=emailable_id,
        template_name=template_name, date_from=date_from, date_to=date_to,
        page=page, page_size=page_size,
    )
    return ResponseModel(data=[schema.EmailSlimOut.model_validate(e) for e in emails])


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
