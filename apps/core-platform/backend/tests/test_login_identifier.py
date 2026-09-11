"""Login accepts a single `identifier`: email, username or phone."""

import uuid

import pytest
from pydantic import ValidationError

from app.common.exception.errors import AuthError
from app.modules.users import service
from app.modules.users.schema import LoginRequest, RegisterRequest

PASSWORD = "Str0ngPass1"


def test_login_requires_identifier_field():
    with pytest.raises(ValidationError):
        LoginRequest(password=PASSWORD)  # type: ignore[call-arg]


def test_register_blank_optional_fields_normalise_to_none():
    body = RegisterRequest(
        name="Blank", email="blank@example.com", password=PASSWORD, username="  ", phone=""
    )
    assert body.username is None
    assert body.phone is None


async def test_login_by_email_username_and_phone(db, mocker):
    mocker.patch("app.modules.users.auth_emails.send_welcome_email", new=mocker.AsyncMock())
    suffix = uuid.uuid4().hex[:8]
    email = f"ident-{suffix}@example.com"
    username = f"user_{suffix}"
    phone = "+9198" + str(uuid.uuid4().int)[:8]

    await service.register(
        db,
        RegisterRequest(
            name="Ident", email=email, password=PASSWORD, username=username, phone=phone
        ),
    )

    for identifier in (email, username, phone):
        _, tokens = await service.login(db, LoginRequest(identifier=identifier, password=PASSWORD))
        assert tokens.access_token, f"login failed for identifier={identifier!r}"


async def test_login_unknown_identifier_is_unauthorized(db):
    with pytest.raises(AuthError):
        await service.login(db, LoginRequest(identifier="ghost@example.com", password=PASSWORD))
