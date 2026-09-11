"""Email lifecycle: webhook event processing + aggregates (real Postgres)."""

from sqlalchemy import select

from app.modules.emails import crud as email_crud
from app.modules.emails import schema as email_schema
from app.modules.emails import service
from app.modules.emails.model import Email, EmailEvent


async def _sent_email(db) -> Email:
    email = Email(
        email_to=["ceo@acme.com"],
        all_recipients=["ceo@acme.com"],
        email_from="noreply@example.com",
        subject="Q3 report",
        status="sent",
        provider_message_id="re_msg_123",
    )
    db.add(email)
    await db.flush()
    return email


async def test_delivered_event_updates_status_and_timeline(db):
    email = await _sent_email(db)

    handled = await service.process_resend_webhook(
        db, {"type": "email.delivered", "data": {"email_id": "re_msg_123"}}
    )
    assert handled is True
    assert email.status == "delivered"
    assert email.delivered_at is not None
    assert email.status_history[-1]["status"] == "delivered"

    events = (await db.scalars(select(EmailEvent).where(EmailEvent.email_id == email.id))).all()
    assert [e.event_type for e in events] == ["email.delivered"]


async def test_open_and_click_aggregates(db):
    email = await _sent_email(db)

    for _ in range(2):
        await service.process_resend_webhook(
            db, {"type": "email.opened", "data": {"email_id": "re_msg_123"}}
        )
    await service.process_resend_webhook(
        db,
        {"type": "email.clicked", "data": {"email_id": "re_msg_123", "click": {"link": "https://x.co"}}},
    )

    assert email.open_count == 2
    assert email.first_opened_at is not None
    assert email.click_count == 1
    click_event = await db.scalar(select(EmailEvent).where(EmailEvent.event_type == "email.clicked"))
    assert click_event.url == "https://x.co"


async def test_bounce_marks_failed_with_type(db):
    email = await _sent_email(db)
    await service.process_resend_webhook(
        db,
        {"type": "email.bounced",
         "data": {"email_id": "re_msg_123", "bounce": {"message": "mailbox full", "subType": "soft"}}},
    )
    assert email.status == "bounced"
    assert email.bounce_type == "soft"
    assert email.failed_at is not None


async def test_unknown_provider_message_is_acknowledged_not_errored(db):
    handled = await service.process_resend_webhook(
        db, {"type": "email.delivered", "data": {"email_id": "unknown-id"}}
    )
    assert handled is False  # 2xx to the provider; never retry-storm us


async def test_stats_aggregate_and_slim_list_query(db):
    email = await _sent_email(db)
    email.push_status("delivered")
    email.open_count = 3
    email.click_count = 1
    await db.flush()

    stats = await email_crud.email_stats(db)
    assert stats["total"] == 1
    assert stats["delivered"] == 1
    assert stats["opens"] == 3
    assert stats["click_rate"] == 1.0  # 1 click / 1 delivered

    # Slim list query loads only the rendered columns but still returns rows.
    rows = await email_crud.list_emails(db)
    assert [r.id for r in rows] == [email.id]
    # Every EmailSlimOut field must be loaded by the load_only query, or this
    # would raise MissingGreenlet under AsyncSession.
    slim = email_schema.EmailSlimOut.model_validate(rows[0])
    assert slim.id == email.id
    assert slim.template_name is None
