"""Zoho Auth module English language messages."""

MESSAGES: dict[str, str] = {
    "auth_initiated": "Zoho authorization initiated successfully.",
    "auth_connected": "Successfully authenticated with Zoho.",
    "auth_disconnected": "Successfully disconnected from Zoho.",
    "status_connected": "Zoho connection is active.",
    "status_disconnected": "Zoho connection is not configured or has been disconnected.",
    "state_invalid": "Invalid or expired OAuth state parameter (CSRF protection).",
    "revoke_missing_token": "No Zoho refresh token available to revoke.",
}
