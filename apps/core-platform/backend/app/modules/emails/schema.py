"""Transport schemas for the emails module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.documents.schema import DocumentOut


class EmailAttachmentMeta(BaseModel):
    """Reference an existing Document to attach (single source of file truth)."""

    document_id: UUID
    is_inline: bool = False
    content_id: str | None = Field(None, description='Inline CID, e.g. "cid:logo"')


class EmailCreate(BaseModel):
    to: list[EmailStr]
    cc: list[EmailStr] = []
    bcc: list[EmailStr] = []

    subject: str
    body_html: str | None = None
    body_text: str | None = None

    email_from: str | None = None       # defaults to RESEND_DEFAULT_FROM
    reply_to: str | None = None

    emailable_id: str | None = None
    emailable_type: str | None = None
    campaign_id: str | None = None

    attachments: list[EmailAttachmentMeta] = []
    scheduled_at: datetime | None = None
    metadata_: dict | None = None


class EmailEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str | None = None
    event_at: datetime | None = None
    url: str | None = None
    ip_address: str | None = None
    provider_event_id: str | None = None


class EmailTemplateSend(BaseModel):
    """Send a registered template (app/modules/emails/templates.py)."""

    template_name: str
    to: list[EmailStr]
    context: dict = Field(default_factory=dict)
    locale: str | None = None
    cc: list[EmailStr] = []
    bcc: list[EmailStr] = []
    email_from: str | None = None
    reply_to: str | None = None
    emailable_id: str | None = None
    emailable_type: str | None = None
    scheduled_at: datetime | None = None


class EmailStatsOut(BaseModel):
    total: int
    sent: int
    delivered: int
    bounced: int
    failed: int
    suppressed: int
    opens: int
    clicks: int
    delivery_rate: float
    open_rate: float
    click_rate: float
    since: datetime | None = None
    until: datetime | None = None


class EmailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    email_to: list
    email_cc: list | None = None
    email_bcc: list | None = None
    email_from: str
    reply_to: str | None = None
    subject: str | None = None
    status: str | None = None
    status_message: str | None = None
    error_message: str | None = None
    attempts: int | None = None
    provider: str | None = None
    provider_message_id: str | None = None
    template_name: str | None = None
    locale: str | None = None
    actor_id: int | None = None
    source_ip: str | None = None
    request_id: str | None = None
    open_count: int | None = None
    click_count: int | None = None
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    documents: list[DocumentOut] = []   # loaded via HasDocumentsMixin
    events: list[EmailEventOut] = []


class EmailSlimOut(BaseModel):
    """List-view DTO: no message bodies, no documents/events (Slim/Fat rule).

    Deliberately excludes body_html/body_text (potentially large) and the
    relationship collections — the list crud query ``load_only``s exactly
    these columns so the DB never ships the rest.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    email_to: list
    subject: str | None = None
    status: str | None = None
    template_name: str | None = None
    open_count: int | None = None
    click_count: int | None = None
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
