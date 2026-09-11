"""Password policy: configurable complexity rules (hermetic, no services)."""

import pytest

from app.modules.users.password_policy import PasswordPolicy, PasswordPolicyError, validate_password


def _policy(**overrides) -> PasswordPolicy:
    base = dict(
        min_length=8,
        max_length=64,
        require_uppercase=True,
        require_lowercase=True,
        require_digit=True,
        require_special=False,
        min_unique_chars=4,
        disallow_common=True,
        disallow_user_info=True,
    )
    base.update(overrides)
    return PasswordPolicy(**base)


def test_accepts_password_meeting_all_rules():
    assert _policy().validate("Str0ngPass") == "Str0ngPass"


def test_rejects_short_password():
    with pytest.raises(PasswordPolicyError) as exc:
        _policy(min_length=10).validate("Str0ng1")
    assert "10 characters" in str(exc.value)


def test_rejects_overlong_password():
    with pytest.raises(PasswordPolicyError):
        _policy().validate("Aa1" + "b" * 100)


def test_requires_character_classes_when_enabled():
    policy = _policy()
    with pytest.raises(PasswordPolicyError):
        policy.validate("alllowercase1")  # no uppercase
    with pytest.raises(PasswordPolicyError):
        policy.validate("ALLUPPERCASE1")  # no lowercase
    with pytest.raises(PasswordPolicyError):
        policy.validate("NoDigitsHere")  # no digit


def test_special_requirement_is_optional_and_enforceable():
    assert _policy(require_special=False).validate("PlainPass1")
    with pytest.raises(PasswordPolicyError):
        _policy(require_special=True).validate("PlainPass1")


def test_min_unique_chars():
    with pytest.raises(PasswordPolicyError):
        _policy().validate("Aaaaaaa1")  # only 3 distinct characters


def test_rejects_common_password_even_when_complexity_passes():
    policy = _policy(require_uppercase=False, require_digit=False, min_unique_chars=0)
    with pytest.raises(PasswordPolicyError):
        policy.validate("password")


def test_rejects_user_info():
    policy = _policy(require_uppercase=False, require_digit=False, min_unique_chars=0)
    with pytest.raises(PasswordPolicyError):
        policy.validate("JayeshSecure", email="jayesh@example.com", name="Jayesh Patel")


def test_module_helper_uses_settings():
    # Default settings (min 8, upper/lower/digit) accept this password.
    assert validate_password("Str0ngPass") == "Str0ngPass"


def test_policy_endpoint_exposes_rules_and_rejects_weak_password():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    policy = client.get("/api/auth/password-policy")
    assert policy.status_code == 200
    assert policy.json()["data"]["min_length"] == 8

    # Weak password fails at the boundary — before any DB work.
    resp = client.post(
        "/api/auth/register",
        json={"name": "x", "email": "weak@example.com", "password": "short"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "password_policy"
