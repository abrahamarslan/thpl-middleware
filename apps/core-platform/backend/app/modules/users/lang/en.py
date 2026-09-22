"""Users module English language messages."""

MESSAGES: dict[str, str] = {
    # Auth flows
    "register_success": "Your account has been created successfully.",
    "login_success": "Login successful.",
    "logout_success": "You have been logged out successfully.",
    "login_otp_sent": "A one-time login code has been sent to your email.",
    "login_otp_verified": "Login verified successfully.",
    "password_changed": "Your password has been changed successfully.",
    "password_reset_sent": "If an account matches those details, a reset code or link has been sent.",
    "password_reset_success": "Your password has been reset successfully.",
    "token_refreshed": "Token refreshed successfully.",

    # Profile & settings
    "profile_updated": "Your profile has been updated successfully.",
    "country_updated": "Country updated successfully.",
    "timezone_updated": "Timezone updated successfully.",
    "profile_fetched": "Profile retrieved successfully.",

    # Location telemetry
    "location_recorded": "Location recorded successfully.",

    # User lifecycle / moderation
    "user_created": "User created successfully.",
    "user_updated": "User updated successfully.",
    "user_deleted": "User deleted successfully.",
    "user_restored": "User restored successfully.",
    "user_banned": "User has been banned successfully.",
    "user_unbanned": "User ban has been lifted.",
    "user_throttled": "User has been throttled.",
    "user_unthrottled": "User throttle has been lifted.",

    # Reference data
    "countries_fetched": "Countries retrieved successfully.",
    "timezones_fetched": "Timezones retrieved successfully.",
}
