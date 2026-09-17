"""Unit tests for the module-level message resolution and ResponseModel.ok helper."""

from app.common.response.messages import (
    get_current_language,
    get_message,
    set_current_language,
)
from app.common.response.schema import ResponseModel


def test_get_message_users_en():
    msg = get_message("users", "register_success")
    assert msg == "Your account has been created successfully."

    msg_login = get_message("users", "login_success")
    assert msg_login == "Login successful."


def test_get_message_zoho_auth_en():
    msg = get_message("zoho.auth", "auth_connected")
    assert msg == "Successfully authenticated with Zoho."

    # Slashed module notation should also work cleanly
    msg_slashed = get_message("zoho/auth", "auth_disconnected")
    assert msg_slashed == "Successfully disconnected from Zoho."

    assert get_message("zoho.auth", "auth_initiated") == "Zoho authorization initiated successfully."
    assert get_message("zoho.auth", "status_connected") == "Zoho connection is active."
    assert get_message("zoho.auth", "status_disconnected") == "Zoho connection is not configured or has been disconnected."


def test_get_message_missing_key_fallback():
    msg = get_message("users", "non_existent_key_123", default="Default Fallback")
    assert msg == "Default Fallback"

    msg_no_default = get_message("users", "non_existent_key_456")
    assert msg_no_default == "non_existent_key_456"


def test_get_message_with_interpolation():
    # Catalog with formatting
    msg = get_message("users", "user_found", default="Hello {name}", name="John")
    assert msg == "Hello John"


def test_response_model_ok_with_msg_key():
    resp = ResponseModel.ok(data={"user_id": 1}, module="users", msg_key="register_success")
    assert resp.code == "ok"
    assert resp.msg == "Your account has been created successfully."
    assert resp.data == {"user_id": 1}


def test_response_model_ok_with_custom_msg():
    resp = ResponseModel.ok(data=None, msg="Custom status message")
    assert resp.msg == "Custom status message"


def test_current_language_context():
    set_current_language("gu-IN")
    assert get_current_language() == "gu"
    # Fallback to English when Gujarati catalog is not yet created
    msg = get_message("users", "register_success")
    assert msg == "Your account has been created successfully."

    set_current_language("en")
    assert get_current_language() == "en"
