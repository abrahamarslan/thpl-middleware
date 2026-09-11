"""Users module — transport schemas (schema layer).

Conventions:
  - Geography columns travel as WKT strings, SRID 4326, lng/lat order:
      "POINT(72.8777 19.0760)", "LINESTRING(72.8 19.0, 72.9 19.1)"
    On output, WKB from PostGIS is converted back to WKT (shapely).
  - Secrets never leave the API: password, two_factor_secret,
    two_factor_recovery_codes, api_token, remember_token are write/internal only.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.users.password_policy import PasswordStr

GEO_FIELDS = (
    "location", "current_location", "route_points", "coordinates",
    "constituency_geometry", "sub_constituency_geometry",
    "assembly_constituency_geometry", "parliamentary_constituency_geometry",
    "pincode_geometry", "taluka_geometry", "district_geometry",
    "city_geometry", "state_geometry", "country_geometry",
)


def _wkb_to_wkt(value: Any) -> Any:
    """Convert a geoalchemy2 WKBElement to a WKT string for API output."""
    if value is None or isinstance(value, str):
        return value
    try:
        from geoalchemy2.shape import to_shape

        return to_shape(value).wkt
    except Exception:  # pragma: no cover - unparseable geometry
        return None


class UserProfileBase(BaseModel):
    """Every editable profile field. Used by Create (with required core
    fields added), Update (everything optional) and Out (plus read-only)."""

    # == Identification ==
    name: str | None = None
    username: str | None = None
    salutation: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None

    # == Status, Roles & Type ==
    role_id: int | None = None
    user_type: str | None = None
    status: str | None = None
    user_status: str | None = None
    status_reason: str | None = None
    is_deactivated: bool | None = None
    deactivation_date: datetime | None = None
    deactivation_reason: str | None = None
    confirmation_status: int | None = None

    # == Contact ==
    phone: str | None = None
    contact: str | None = None

    # == Personal ==
    gender: str | None = None
    date_of_birth: date | None = None
    is_married: bool | None = None
    citizenship: str | None = None
    blood_group: str | None = None
    pan: str | None = None
    gstin: str | None = None
    tax_preference: str | None = None
    gst_treatment: str | None = None
    languages_known: list | None = None
    social_links: dict | None = None
    emergency_contact: dict | None = None
    medical_history: dict | None = None
    insurance_details: dict | None = None

    # == Parent / Family ==
    parent_one_gender: str | None = None
    parent_two_gender: str | None = None
    parent_one_contact: str | None = None
    parent_two_contact: str | None = None
    family_details: dict | None = None

    # == Professional / Education ==
    occupation: str | None = None
    designation: str | None = None
    department: str | None = None
    education_qualification: str | None = None
    education_specialization: str | None = None
    education_history: list | dict | None = None
    work_history: list | dict | None = None
    reference_details: dict | None = None
    referred_by_user_id: int | None = None
    communication_preferences: dict | None = None

    # == Company ==
    company_name: str | None = None
    company_address: str | None = None
    company_email: str | None = None
    company_phone: str | None = None
    company_website: str | None = None
    company_gstin: str | None = None
    company_pan: str | None = None
    company_cin: str | None = None
    company_tan: str | None = None
    date_of_joining: datetime | None = None

    # == Membership & Sessions ==
    member_id: str | None = None
    current_sessions: dict | list | None = None
    has_active_session: bool | None = None
    zoho_user_id: str | None = None
    onboarding_status: str | None = None

    # == Profile customization ==
    image: str | None = None
    avatar: str | None = None
    thumbnail: str | None = None
    preview_image: str | None = None
    profile_completion_percentage: int | None = Field(default=None, ge=0, le=100)
    other_details: dict | None = None
    other_information: dict | None = None
    payment_details: dict | None = None
    bank_details: dict | None = None
    billing_address: dict | None = None
    shipping_address: dict | None = None

    # == Preferences ==
    language: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    currency: str | None = None
    currency_symbol: str | None = None
    thousand_separator: str | None = None
    decimal_separator: str | None = None
    locale_settings: dict | None = None
    online_status_preference: int | None = None
    is_location_set: bool | None = None
    application_settings: dict | None = None
    default_language: str | None = None

    # == Location (textual) ==
    constituency: str | None = None
    sub_constituency: str | None = None
    assembly_constituency: str | None = None
    parliamentary_constituency: str | None = None
    pincode: str | None = None
    street_address: str | None = None
    landmark: str | None = None
    village_town: str | None = None
    taluka: str | None = None
    district: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None

    # == Location (geospatial — WKT strings, SRID 4326, lng/lat) ==
    location: str | None = None
    current_location: str | None = None
    route_points: str | None = None
    coordinates: str | None = None
    constituency_geometry: str | None = None
    sub_constituency_geometry: str | None = None
    assembly_constituency_geometry: str | None = None
    parliamentary_constituency_geometry: str | None = None
    pincode_geometry: str | None = None
    taluka_geometry: str | None = None
    district_geometry: str | None = None
    city_geometry: str | None = None
    state_geometry: str | None = None
    country_geometry: str | None = None

    # == Location (coordinates & IDs) ==
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    current_pincode: str | None = None
    current_location_latitude: str | None = None
    current_location_longitude: str | None = None
    constituency_latitude: Decimal | None = None
    constituency_longitude: Decimal | None = None
    district_latitude: Decimal | None = None
    district_longitude: Decimal | None = None
    taluka_latitude: Decimal | None = None
    taluka_longitude: Decimal | None = None
    city_latitude: Decimal | None = None
    city_longitude: Decimal | None = None
    state_latitude: Decimal | None = None
    state_longitude: Decimal | None = None
    country_latitude: Decimal | None = None
    country_longitude: Decimal | None = None
    postal_code_latitude: Decimal | None = None
    postal_code_longitude: Decimal | None = None
    constituency_geonameId: str | None = None
    sub_constituency_geonameId: str | None = None
    assembly_constituency_geonameId: str | None = None
    parliamentary_constituency_geonameId: str | None = None
    pincode_geonameId: str | None = None
    taluka_geonameId: str | None = None
    district_geonameId: str | None = None
    city_geonameId: str | None = None
    state_geonameId: str | None = None
    country_geonameId: str | None = None

    # == Tracking metadata ==
    altitude: Decimal | None = None
    altitude_accuracy: float | None = None
    heading: float | None = None
    speed: float | None = None
    location_accuracy: str | None = None
    location_source: str | None = None
    location_timestamp: datetime | None = None
    location_timezone: str | None = None
    location_ip: str | None = None
    geocode: dict | None = None
    recorded_at: datetime | None = None
    last_tracked_at: datetime | None = None
    device_id: str | None = None
    device_type: str | None = None
    network_type: str | None = None
    is_tracking_active: bool | None = None
    background_tracking_enabled: bool | None = None

    # == Integration IDs ==
    external_id: str | None = None
    zoho_id: str | None = None
    zoho_customer_id: str | None = None
    zoho_contact_id: str | None = None

    # == Targets ==
    targets: dict | None = None
    target_history: dict | list | None = None
    target_progress: dict | None = None
    target_achievements: dict | None = None
    target_achievements_history: dict | list | None = None

    # == Sync ==
    last_sync_time: datetime | None = None


class UserCreate(UserProfileBase):
    name: str
    email: EmailStr
    password: PasswordStr


class UserUpdate(UserProfileBase):
    email: EmailStr | None = None


class UserOut(UserProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    email_verified_at: datetime | None = None
    phone_verified_at: datetime | None = None
    two_factor_confirmed_at: datetime | None = None
    # Authentik mirror state (read-only; see app/modules/users/authentik_sync.py)
    authentik_pk: str | None = None
    authentik_sync_status: str | None = None
    authentik_synced_at: datetime | None = None
    last_login: datetime | None = None
    last_password_change_at: datetime | None = None
    failed_login_attempts: int | None = None
    locked_at: datetime | None = None
    # Moderation (read-only; see app/modules/users/moderation.py)
    is_banned: bool | None = None
    banned_at: datetime | None = None
    banned_until: datetime | None = None
    ban_reason: str | None = None
    is_throttled: bool | None = None
    throttled_at: datetime | None = None
    throttled_until: datetime | None = None
    throttle_reason: str | None = None
    created_by: int | None = None
    updated_by: int | None = None
    deleted_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    @field_validator(*GEO_FIELDS, mode="before")
    @classmethod
    def _serialise_geography(cls, v: Any) -> Any:
        return _wkb_to_wkt(v)


class UserListFilters(BaseModel):
    q: str | None = Field(default=None, description="Search in name/email/username/phone")
    status: str | None = None
    user_type: str | None = None
    role_id: int | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    include_deleted: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    order_by: str = Field(default="-created_at", description="column or -column")


# ── Auth schemas ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: PasswordStr
    username: str | None = Field(
        default=None, max_length=50, description="Optional unique login handle (also usable to sign in)"
    )
    phone: str | None = Field(default=None, max_length=32, description="Optional phone (also usable to sign in)")

    @field_validator("username", "phone", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        # Frontends often submit "" for untouched optional fields.
        if isinstance(v, str) and not v.strip():
            return None
        return v


class LoginRequest(BaseModel):
    identifier: str = Field(
        min_length=3, max_length=255,
        description="Username, email address, or phone number of the account",
    )
    password: str
    device_id: str | None = None
    device_type: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: PasswordStr


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(
        min_length=3, max_length=255, description="Account email, username or phone number"
    )
    reset_type: str = Field(default="code", pattern="^(link|code)$")


class ResetPasswordRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)
    token_or_code: str = Field(min_length=3, max_length=255, description="The emailed code or link token")
    new_password: PasswordStr


class LoginOtpRequest(BaseModel):
    identifier: str = Field(
        min_length=3, max_length=255, description="Account email, username or phone number"
    )


class LoginOtpVerifyRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=4, max_length=10)
    device_id: str | None = None
    device_type: str | None = None


class PasswordPolicyOut(BaseModel):
    """The active password rules, for client-side pre-validation/hints."""

    min_length: int
    max_length: int
    require_uppercase: bool
    require_lowercase: bool
    require_digit: bool
    require_special: bool
    min_unique_chars: int
    disallow_common: bool
    disallow_user_info: bool


# ── Moderation schemas ────────────────────────────────────────────────────────

def _ensure_utc(value: datetime | None) -> datetime | None:
    """Coerce a naive datetime to UTC so comparisons never mix aware/naive."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class BanRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    until: datetime | None = Field(
        default=None, description="Ban expiry (UTC). Omit for a permanent ban."
    )

    @field_validator("until", mode="after")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return _ensure_utc(v)


class ThrottleRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    until: datetime | None = Field(
        default=None, description="Throttle expiry (UTC). Omit to hold until lifted."
    )

    @field_validator("until", mode="after")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return _ensure_utc(v)


class ModerationOut(BaseModel):
    """Current moderation state of a user (see `moderation.moderation_state`)."""

    state: str
    is_banned: bool
    ban_reason: str | None = None
    banned_at: datetime | None = None
    banned_until: datetime | None = None
    is_throttled: bool
    throttle_reason: str | None = None
    throttled_at: datetime | None = None
    throttled_until: datetime | None = None
    is_locked: bool
    locked_at: datetime | None = None
    is_deactivated: bool
