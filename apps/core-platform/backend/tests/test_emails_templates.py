"""Email provider adapter + template registry (hermetic).

Auth template *content* is exercised in ``test_auth_emails.py`` (which imports
the auth module that registers them); this file covers the provider layer and
the registry's failure modes.
"""

import pytest

from app.modules.emails.provider import (
    EmailAttachment,
    EmailProviderError,
    OutboundEmail,
    ResendProvider,
    build_provider,
)
from app.modules.emails.templates import (
    EmailTemplate,
    TemplateContextError,
    TemplateNotFoundError,
    register_template,
    render_email,
)


def test_unknown_template_raises():
    with pytest.raises(TemplateNotFoundError):
        render_email("definitely_not_a_template", {})


def test_missing_required_context_raises():
    register_template(
        EmailTemplate(
            name="_test_strict", subject="Hi", html="_test_strict",
            text=None, required_context=("must_have",),
        )
    )
    with pytest.raises(TemplateContextError):
        render_email("_test_strict", {})


def test_resend_payload_shape():
    provider = ResendProvider(api_key="re_test", api_url="https://api.resend.test/emails")
    message = OutboundEmail(
        to=["a@b.co"],
        cc=["c@d.co"],
        subject="Hi",
        sender="Tarrina <noreply@example.com>",
        html="<b>hi</b>",
        attachments=[EmailAttachment(filename="a.txt", content=b"hello", content_id="cid:1")],
    )
    payload = provider._payload(message)
    assert payload["to"] == ["a@b.co"]
    assert payload["cc"] == ["c@d.co"]
    assert payload["html"] == "<b>hi</b>"
    attachment = payload["attachments"][0]
    assert attachment["filename"] == "a.txt"
    assert attachment["content_id"] == "cid:1"
    assert attachment["content"] == "aGVsbG8="  # base64("hello")


def test_build_provider_rejects_unknown_key():
    with pytest.raises(EmailProviderError):
        build_provider("carrier-pigeon")


def test_default_provider_is_resend():
    assert isinstance(build_provider("resend"), ResendProvider)
