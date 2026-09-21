"""Mocked-boundary tests for Profile, Countries, and Localized Response Endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.common.client_info import get_client_info
from app.database.db import get_db
from app.main import app
from app.modules.users.deps import get_current_user
from app.modules.users.model import TimezoneSource, User, UserProfile
from app.modules.users.schema import UserOut


def test_countries_endpoint(mocker):
    mocker.patch(
        "app.modules.users.service.get_cached_countries",
        new_callable=AsyncMock,
        return_value=[
            {
                "iso2": "IN",
                "iso3": "IND",
                "numeric_code": "356",
                "name": "India",
                "official_name": "Republic of India",
                "region": "Asia",
                "subregion": "Southern Asia",
                "phone_code": "+91",
                "currency_code": "INR",
                "is_active": True,
            }
        ],
    )

    client = TestClient(app)
    response = client.get("/api/countries")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "ok"
    assert body["msg"] == "Countries retrieved successfully."
    assert len(body["data"]) == 1
    assert body["data"][0]["iso2"] == "IN"


def test_country_timezones_endpoint(mocker):
    mocker.patch(
        "app.modules.users.service.get_cached_country_timezones",
        new_callable=AsyncMock,
        return_value=[
            {"timezone_name": "Asia/Kolkata", "is_default": True}
        ],
    )

    client = TestClient(app)
    response = client.get("/api/countries/IN/timezones")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "ok"
    assert body["msg"] == "Timezones retrieved successfully."
    assert body["data"][0]["timezone_name"] == "Asia/Kolkata"
    assert body["data"][0]["is_default"] is True


def test_get_my_profile_endpoint(mocker):
    mock_user = User(id=1, email="test@example.com", name="Test User")
    mock_profile = UserProfile(
        id=101,
        uuid=uuid.uuid4(),
        user_id=1,
        country_iso2="IN",
        timezone_name="Asia/Kolkata",
        timezone_source=TimezoneSource.auto,
        updated_at=datetime.now(UTC),
    )

    mocker.patch(
        "app.modules.users.service.get_or_create_profile",
        new_callable=AsyncMock,
        return_value=mock_profile,
    )

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    try:
        client = TestClient(app)
        response = client.get("/api/me/profile")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "ok"
        assert body["msg"] == "Profile retrieved successfully."
        assert body["data"]["user_id"] == 1
        assert body["data"]["country_iso2"] == "IN"
        assert body["data"]["timezone_name"] == "Asia/Kolkata"
        assert body["data"]["timezone_source"] == "auto"
        assert "uuid" in body["data"]
    finally:
        app.dependency_overrides.clear()


def test_patch_my_profile_endpoint(mocker):
    mock_user = User(id=1, email="test@example.com", name="Test User")
    mock_profile = UserProfile(
        id=101,
        uuid=uuid.uuid4(),
        user_id=1,
        country_iso2="US",
        timezone_name="America/New_York",
        timezone_source=TimezoneSource.auto,
        updated_at=datetime.now(UTC),
    )

    mocker.patch(
        "app.modules.users.service.update_user_profile",
        new_callable=AsyncMock,
        return_value=mock_profile,
    )

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    try:
        client = TestClient(app)
        response = client.patch("/api/me/profile", json={"country": "US"})
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "ok"
        assert body["msg"] == "Your profile has been updated successfully."
        assert body["data"]["country_iso2"] == "US"
        assert body["data"]["timezone_name"] == "America/New_York"
    finally:
        app.dependency_overrides.clear()


def test_register_returns_friendly_message(mocker):
    mock_user = User(
        id=1,
        email="newuser@example.com",
        name="New User",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mocker.patch(
        "app.modules.users.service.register",
        new_callable=AsyncMock,
        return_value=mock_user,
    )

    app.dependency_overrides[get_db] = lambda: AsyncMock()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/auth/register",
            json={
                "name": "New User",
                "email": "newuser@example.com",
                "password": "Password123!",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["code"] == "ok"
        # Verify the user-requested copy!
        assert body["msg"] == "Your account has been created successfully."
        assert body["data"]["email"] == "newuser@example.com"
    finally:
        app.dependency_overrides.clear()


def test_zoho_auth_revoke_returns_clean_envelope(mocker):
    mocker.patch(
        "app.modules.zoho.auth.service.zoho_auth_service.revoke_token",
        new_callable=AsyncMock,
        return_value=None,
    )

    app.dependency_overrides[get_db] = lambda: AsyncMock()

    try:
        client = TestClient(app)
        response = client.post("/api/zoho/auth/revoke")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "ok"
        assert body["msg"] == "Successfully disconnected from Zoho."
        assert body["data"]["disconnected"] is True
        # Verify data does NOT contain nested 'message' key
        assert "message" not in body["data"]
    finally:
        app.dependency_overrides.clear()


def test_zoho_auth_initiate_json_endpoint(mocker):
    mocker.patch(
        "app.modules.zoho.auth.service.zoho_auth_service.get_authorization_url",
        new_callable=AsyncMock,
        return_value="https://accounts.zoho.com/oauth/v2/auth?client_id=123",
    )

    client = TestClient(app)
    response = client.get("/api/zoho/auth/initiate?redirect=false")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "ok"
    assert body["msg"] == "Zoho authorization initiated successfully."
    assert body["data"]["authorization_url"] == "https://accounts.zoho.com/oauth/v2/auth?client_id=123"


def test_zoho_auth_status_endpoint(mocker):
    mock_token = mocker.patch(
        "app.modules.zoho.core.auth.zoho_token_manager.get_refresh_token",
        new_callable=AsyncMock,
        return_value="ref_token_abc",
    )

    client = TestClient(app)
    # Active connection
    res = client.get("/api/zoho/auth/status")
    assert res.status_code == 200
    b = res.json()
    assert b["code"] == "ok"
    assert b["msg"] == "Zoho connection is active."
    assert b["data"]["is_connected"] is True

    # Inactive / disconnected
    mock_token.return_value = None
    res2 = client.get("/api/zoho/auth/status")
    assert res2.status_code == 200
    b2 = res2.json()
    assert b2["code"] == "ok"
    assert b2["msg"] == "Zoho connection is not configured or has been disconnected."
    assert b2["data"]["is_connected"] is False


def test_forgot_password_returns_email_and_masked_email(mocker):
    mocker.patch(
        "app.modules.users.service.request_password_reset",
        new_callable=AsyncMock,
        return_value={
            "sent": True,
            "email": "tech@tarrinahealth.com",
            "masked_email": "t****************h@tarrinahealth.com",
            "expires_at": datetime.now(UTC),
        },
    )

    app.dependency_overrides[get_db] = lambda: AsyncMock()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/auth/forgot-password",
            json={"identifier": "tech@tarrinahealth.com", "reset_type": "code"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "ok"
        assert body["msg"] == "If an account matches those details, a reset code or link has been sent."
        assert body["data"]["sent"] is True
        assert body["data"]["email"] == "tech@tarrinahealth.com"
        assert body["data"]["masked_email"] == "t****************h@tarrinahealth.com"
        assert "expires_at" in body["data"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_otp_timestamp_in_user_timezone(mocker):
    from app.common.client_info import ClientInfo
    from app.modules.users import auth_emails

    mock_send = mocker.patch.object(auth_emails, "send_template_email", new=AsyncMock())
    fixed_time = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

    # User in New York timezone (EDT in September)
    user_ny = User(id=1, name="NY User", email="ny@example.com", timezone="America/New_York")
    client = ClientInfo(ip="1.2.3.4", device="Chrome", location="New York, USA")

    await auth_emails.send_login_otp_email(
        AsyncMock(), user_ny, code="123456", expires_minutes=15, client=client
    )
    context_ny = mock_send.await_args.kwargs["context"]
    # Verify timestamp reflects America/New_York (EDT, -4 hours = 08:00)
    assert "EDT" in context_ny["requested_at"] or "America/New_York" in context_ny["requested_at"]
    assert "UTC" not in context_ny["requested_at"]

    # User in Kolkata timezone (IST, +5:30 = 17:30)
    user_in = User(id=2, name="IN User", email="in@example.com", timezone="Asia/Kolkata")
    await auth_emails.send_login_otp_email(
        AsyncMock(), user_in, code="654321", expires_minutes=15, client=client
    )
    context_in = mock_send.await_args.kwargs["context"]
    assert "IST" in context_in["requested_at"] or "Asia/Kolkata" in context_in["requested_at"]
    assert "UTC" not in context_in["requested_at"]


@pytest.mark.asyncio
async def test_register_assigns_country_and_timezone_from_geoip(mocker):
    from app.common.client_info import ClientInfo
    from app.modules.users import service
    from app.modules.users.model import Country
    from app.modules.users.schema import RegisterRequest

    mock_db = AsyncMock()
    mocker.patch("app.modules.users.crud.get_by_email", new_callable=AsyncMock, return_value=None)
    mocker.patch("app.modules.users.crud.get_by_username", new_callable=AsyncMock, return_value=None)
    mocker.patch("app.modules.users.service.validate_password", return_value=None)
    mocker.patch("app.modules.users.authentik_sync.sync_create", new_callable=AsyncMock)
    mocker.patch("app.modules.users.auth_emails.send_welcome_email", new_callable=AsyncMock)
    mocker.patch("app.modules.users.service.audit", new_callable=AsyncMock)

    mock_create = mocker.patch("app.modules.users.crud.create", new_callable=AsyncMock)
    created_user = User(id=99, email="ususer@example.com", name="US User")
    mock_create.return_value = created_user

    mocker.patch("app.modules.users.service.get_or_create_profile", new_callable=AsyncMock)

    # Mock Country lookup for US
    us_country = Country(iso2="US", iso3="USA", name="United States", currency_code="USD")
    mock_db.scalar.return_value = us_country

    client_geoip = ClientInfo(
        ip="198.51.100.1",
        country="United States",
        country_code="US",
        timezone="America/New_York",
    )

    reg_body = RegisterRequest(
        name="US User",
        email="ususer@example.com",
        password="ValidPassword123!",
    )

    await service.register(mock_db, reg_body, client=client_geoip)

    # Verify that GeoIP country and timezone were properly assigned to user record
    mock_create.assert_awaited_once()
    create_args = mock_create.await_args.args[1]
    assert create_args["country"] == "United States"
    assert create_args["country_code"] == "US"
    assert create_args["timezone"] == "America/New_York"
    assert create_args["currency"] == "USD"
