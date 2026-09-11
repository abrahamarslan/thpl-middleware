"""Auth email templates + request-audit helpers (hermetic)."""

from starlette.requests import Request

from app.common import geoip
from app.common.client_info import build_client_info, format_utc, parse_user_agent
from app.modules.users import auth_emails  # noqa: F401 — registers auth templates
from app.modules.emails.templates import registered_names, render_email


def _request(headers: dict[str, str], client=("1.2.3.4", 1234)) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_all_auth_templates_registered():
    assert {"welcome", "login_otp", "password_reset_code", "password_reset_link", "password_changed"} <= set(
        registered_names()
    )


def test_login_otp_template_renders_code_and_audit():
    rendered = render_email(
        "login_otp",
        {
            "code": "739421",
            "code_formatted": "739-421",
            "expires_minutes": 15,
            "device": "Chrome on macOS",
            "location": "Ahmedabad, Gujarat, India",
            "ip": "1.2.3.4",
            "requested_at": "September 10, 2026, 21:30 UTC",
        },
    )
    assert "739-421" in rendered.html
    assert "739421" in rendered.text
    assert "Chrome on macOS" in rendered.html
    assert "Ahmedabad" in rendered.html


def test_password_reset_code_template_iterates_digits():
    rendered = render_email(
        "password_reset_code",
        {
            "code": "7419",
            "expires_minutes": 10,
            "attempts_allowed": 3,
            "email": "a@b.co",
        },
    )
    for digit in "7419":
        assert digit in rendered.html
    assert "3 attempts maximum" in rendered.html
    assert "a@b.co" in rendered.text


def test_welcome_template_renders_dashboard_link():
    rendered = render_email(
        "welcome",
        {
            "email": "a@b.co",
            "name": "Asha",
            "account_id": "TH-000001",
            "dashboard_url": "https://app.local/dashboard",
        },
    )
    assert "https://app.local/dashboard" in rendered.html
    assert "Asha" in rendered.html


def test_password_reset_link_template_renders_url():
    rendered = render_email(
        "password_reset_link",
        {"reset_url": "https://app.local/reset?token=abc", "expires_minutes": 60, "email": "a@b.co"},
    )
    assert "https://app.local/reset?token=abc" in rendered.html


def test_parse_user_agent():
    assert parse_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/120 Safari/537") == "Chrome on Windows"
    assert parse_user_agent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Version/17.0 Mobile Safari") == "Safari on iOS"
    assert parse_user_agent("TarrinaApp/1.2 (Android 14)") == "Tarrina App on Android"
    assert parse_user_agent(None) == "Unknown device"


def test_format_utc_is_platform_independent():
    from datetime import UTC, datetime

    assert format_utc(datetime(2026, 9, 10, 21, 30, tzinfo=UTC)) == "September 10, 2026, 21:30 UTC"


def test_client_info_uses_forwarded_for_and_geoip_off(monkeypatch):
    monkeypatch.setattr("app.common.client_info.lookup_ip", lambda ip: None)
    info = build_client_info(
        _request({"x-forwarded-for": "203.0.113.9, 10.0.0.1", "user-agent": "curl/8.0"})
    )
    assert info.ip == "203.0.113.9"
    assert info.device == "API client"
    assert info.location == "Unknown location"  # GeoIP disabled by default


def test_private_ips_are_never_looked_up():
    assert geoip.is_public_ip("8.8.8.8") is True
    assert geoip.is_public_ip("10.0.0.1") is False
    assert geoip.is_public_ip("127.0.0.1") is False
    assert geoip.is_public_ip("203.0.113.9") is False  # TEST-NET-3 (reserved)
    assert geoip.is_public_ip("not-an-ip") is False
