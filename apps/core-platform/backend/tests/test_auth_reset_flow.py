"""End-to-end password reset for tech@tarrinahealth.com (real Postgres).

Exercises the full wiring — identifier resolution, code/link delivery (captured
at the ``auth_emails`` boundary), hashing/attempts/single-use, Authentik
best-effort, and login with the new password. The HTTP test drives the actual
``/api/auth/forgot-password`` and ``/api/auth/reset-password`` routes with the
DB dependency overridden to the test session.
"""

import re

import httpx
import pytest
from httpx import ASGITransport

from app.common.exception.errors import AuthError
from app.database.db import get_db
from app.main import app
from app.modules.users import auth_emails, crud, password_reset, service
from app.modules.users.model import User
from app.modules.users.schema import LoginRequest
from app.modules.users.security import hash_password, verify_password

TECH = "tech@tarrinahealth.com"
OLD_PASSWORD = "OldTechPass1!"


async def _tech_user(db, password: str = OLD_PASSWORD) -> User:
    user = await crud.get_by_email(db, TECH)
    if user is None:
        user = await crud.create(
            db, {"name": "Tech", "email": TECH, "password": hash_password(password)}
        )
    else:
        user.password = hash_password(password)
        user.is_banned = False
        user.is_throttled = False
        await db.flush()
    return user


def _patch_emails(mocker):
    send_code = mocker.patch.object(
        auth_emails, "send_password_reset_code_email", new=mocker.AsyncMock()
    )
    send_link = mocker.patch.object(
        auth_emails, "send_password_reset_link_email", new=mocker.AsyncMock()
    )
    mocker.patch.object(auth_emails, "send_password_changed_email", new=mocker.AsyncMock())
    mocker.patch.object(password_reset, "sync_set_password", new=mocker.AsyncMock())
    return send_code, send_link


async def test_code_reset_flow_service(db, mocker):
    user = await _tech_user(db)
    send_code, _ = _patch_emails(mocker)

    result = await password_reset.request_password_reset(db, identifier=TECH, reset_type="code")
    assert result.sent is True
    code = send_code.await_args.kwargs["code"]
    assert re.fullmatch(r"\d{4}", code)

    await password_reset.reset_password(
        db, identifier=TECH, token_or_code=code, new_password="N3wSecurePass!"
    )
    assert verify_password("N3wSecurePass!", user.password)

    # New password logs in; the old one is rejected.
    _, tokens = await service.login(db, LoginRequest(identifier=TECH, password="N3wSecurePass!"))
    assert tokens.access_token
    with pytest.raises(AuthError):
        await service.login(db, LoginRequest(identifier=TECH, password=OLD_PASSWORD))


async def test_link_reset_flow_service(db, mocker):
    user = await _tech_user(db)
    _, send_link = _patch_emails(mocker)

    await password_reset.request_password_reset(db, identifier=TECH, reset_type="link")
    reset_url = send_link.await_args.kwargs["reset_url"]
    token = reset_url.split("token=")[1]

    await password_reset.reset_password(
        db, identifier=TECH, token_or_code=token, new_password="N3wLinkPass!"
    )
    assert verify_password("N3wLinkPass!", user.password)


async def test_wrong_code_rejected(db, mocker):
    await _tech_user(db)
    _patch_emails(mocker)
    await password_reset.request_password_reset(db, identifier=TECH, reset_type="code")

    with pytest.raises(AuthError):
        await password_reset.reset_password(
            db, identifier=TECH, token_or_code="0000", new_password="N3wSecurePass!"
        )


async def test_forgot_and_reset_via_http(db, mocker):
    await _tech_user(db)
    send_code, _ = _patch_emails(mocker)

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            forgot = await client.post(
                "/api/auth/forgot-password", json={"identifier": TECH, "reset_type": "code"}
            )
            assert forgot.status_code == 200, forgot.text
            assert forgot.json()["data"]["sent"] is True
            code = send_code.await_args.kwargs["code"]

            reset = await client.post(
                "/api/auth/reset-password",
                json={"identifier": TECH, "token_or_code": code, "new_password": "N3wHttpPass!"},
            )
            assert reset.status_code == 200, reset.text
            assert reset.json()["data"]["reset"] is True

            old = await client.post(
                "/api/auth/login", json={"identifier": TECH, "password": OLD_PASSWORD}
            )
            assert old.status_code == 401

            new = await client.post(
                "/api/auth/login", json={"identifier": TECH, "password": "N3wHttpPass!"}
            )
            assert new.status_code == 200, new.text
            assert new.json()["data"]["access_token"]
    finally:
        app.dependency_overrides.pop(get_db, None)
