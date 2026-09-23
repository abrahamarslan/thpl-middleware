"""Users module — transport schemas (schema layer).

Conventions:
  - Geography columns travel as WKT strings, SRID 4326, lng/lat order:
      "POINT(72.8777 19.0760)", "LINESTRING(72.8 19.0, 72.9 19.1)"
    On output, WKB from PostGIS is converted back to WKT (shapely).
  - Secrets never leave the API: password, two_factor_secret,
    two_factor_recovery_codes, api_token, remember_token are write/internal only.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.modules.geo.enums import LinkType
from app.modules.geo.schema import PostalFields
from app.modules.users.password_policy import PasswordStr


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

    # == Location (address/coordinates live in geo; only caches/pointers here) ==
    country_code: str | None = Field(None, max_length=2, description="ISO 3166-1 alpha-2 country code")
    primary_place_id: int | None = None

    # == Device metadata (auth/device binding) ==
    device_id: str | None = None
    device_type: str | None = None

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
    # Plain `str`, NOT `EmailStr`: this is an OUTPUT model. The row already
    # exists — its email was validated (or deliberately bypassed) at write
    # time by whichever path created it (RegisterRequest, Authentik JIT
    # provisioning, the DEBUG-only dev-token user). Re-validating on the way
    # out makes every read 500 for any row whose email uses a special-use
    # domain (`dev@local.test`, `<sub>@authentik.local`) that email-validator
    # rejects as syntactically ineligible, even though it's a normal string
    # already sitting in the database.
    email: str
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


class UserListFilters(BaseModel):
    q: str | None = Field(default=None, description="Search in name/email/username/phone")
    status: str | None = None
    user_type: str | None = None
    role_id: int | None = None
    country_code: str | None = Field(default=None, description="Cached ISO2 on the user row")
    # Resolved through the address book (geo.place_links → geo.places), not off
    # the user row — those columns are gone.
    city: str | None = Field(default=None, description="Matches any live address of the user")
    state: str | None = Field(default=None, description="Matches any live address of the user")
    country: str | None = Field(default=None, description="Address country name or ISO2 code")
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


class ForgotPasswordOut(BaseModel):
    sent: bool = True
    email: str | None = None
    masked_email: str | None = None
    expires_at: datetime | None = None
    debug_code: str | None = None
    debug_token: str | None = None


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


class CountryOut(BaseModel):
    """ISO 3166-1 country transport schema."""

    iso2: str
    iso3: str
    numeric_code: str | None = None
    name: str
    official_name: str | None = None
    region: str | None = None
    subregion: str | None = None
    phone_code: str | None = None
    currency_code: str | None = None
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class CountryTimezoneOut(BaseModel):
    """Country timezone mapping transport schema."""

    timezone_name: str
    is_default: bool

    model_config = ConfigDict(from_attributes=True)


# ── Self-service profile (GET/PATCH /api/auth/me/profile) ────────────────────
#
# The address is NOT a column on the users row. A residential address is a
# ``geo.places`` row (the only place coordinates are stored) plus a
# ``geo.place_links`` row with ``owner_type='user'`` — the profile endpoint is a
# convenience facade that writes through the location hub, never a second
# address store. See docs/geo/README.md §3.

class ProfileAddressIn(PostalFields):
    """Residential address: the postal block plus a point and link intent.

    ``link_type`` defaults to ``current`` because ``current``/``permanent`` are
    the effective-dated, single-valued link types: a new one auto-closes the
    one it supersedes, so an address change keeps its history.
    """

    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    link_type: LinkType = LinkType.CURRENT
    label: str | None = Field(None, max_length=100, description='User-facing label, e.g. "Home"')

    @model_validator(mode="after")
    def _coordinates_come_in_pairs(self) -> "ProfileAddressIn":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class UserAddressOut(BaseModel):
    """The user's current primary address (a ``geo.place_links`` row + its place)."""

    uuid: UUID
    link_type: str
    label: str | None = None
    is_primary: bool = False
    is_verified: bool = False
    latitude: float | None = None
    longitude: float | None = None
    place_uuid: UUID | None = None
    attention: str | None = None
    formatted_address: str | None = None
    building_name: str | None = None
    street: str | None = None
    street2: str | None = None
    landmark: str | None = None
    sub_locality: str | None = None
    locality: str | None = None
    city: str | None = None
    district: str | None = None
    taluka: str | None = None
    state: str | None = None
    state_code: str | None = None
    postal_code: str | None = None
    country: str | None = None
    country_code: str | None = None


class UserSelfUpdate(BaseModel):
    """Fields a user may change about THEMSELVES.

    An explicit allowlist — deliberately NOT ``UserUpdate``. The admin schema
    carries ``role_id``, ``status``, ``user_type``, ``is_deactivated`` and the
    rest of the privilege/lifecycle surface; accepting it here would let a user
    escalate their own role. ``extra="forbid"`` turns any such attempt into a
    422 instead of a silently applied change.
    """

    model_config = ConfigDict(extra="forbid")

    # Identification
    name: str | None = None
    salutation: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None

    # Contact
    phone: str | None = None
    contact: str | None = None

    # Personal
    gender: str | None = None
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

    # Parent / family
    parent_one_gender: str | None = None
    parent_two_gender: str | None = None
    parent_one_contact: str | None = None
    parent_two_contact: str | None = None
    family_details: dict | None = None

    # Professional / education
    occupation: str | None = None
    designation: str | None = None
    department: str | None = None
    education_qualification: str | None = None
    education_specialization: str | None = None
    education_history: list | dict | None = None
    work_history: list | dict | None = None
    reference_details: dict | None = None
    communication_preferences: dict | None = None

    # Company
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

    # Profile customization
    image: str | None = None
    avatar: str | None = None
    thumbnail: str | None = None
    preview_image: str | None = None

    # Preferences
    language: str | None = None
    default_language: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    currency: str | None = None
    currency_symbol: str | None = None
    thousand_separator: str | None = None
    decimal_separator: str | None = None
    locale_settings: dict | None = None
    online_status_preference: int | None = None
    application_settings: dict | None = None

    # Location cache (ISO2; routed through the localization profile)
    country_code: str | None = Field(None, max_length=2)

    # Misc
    other_details: dict | None = None
    other_information: dict | None = None

    # Residential address — written through the location hub
    address: ProfileAddressIn | None = None


class UserMeOut(UserOut):
    """What GET/PATCH ``/me/profile`` returns: the full self view.

    ``UserOut`` plus the localization source and the user's primary address.
    """

    timezone_source: str | None = None
    country_iso2: str | None = None
    timezone_name: str | None = None
    address: UserAddressOut | None = None


# ── Location telemetry ────────────────────────────────────────────────────────
# The `users` row carries no coordinates any more: the last known fix lives in
# `user_live_locations` and the history in the partitioned `user_location_pings`
# (docs/analysis-report/user-new-architecture.md §10.4). Latitude/longitude are
# the wire format; PostGIS geography is the storage format, converted in the
# service layer exactly as the geo module does.

class LocationUpdate(BaseModel):
    """One position fix reported by a device."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, description="Horizontal accuracy in metres")
    altitude_m: float | None = None
    altitude_accuracy_m: float | None = Field(default=None, ge=0)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    speed_mps: float | None = Field(default=None, ge=0)
    location_source: str | None = Field(default=None, pattern="^(gps|network|manual)$")
    is_moving: bool | None = None
    tracking_active: bool | None = None
    background_tracking_enabled: bool | None = None
    device_id: str | None = Field(default=None, max_length=255)
    device_type: str | None = Field(default=None, max_length=50)
    network_type: str | None = Field(default=None, max_length=50)
    place_id: int | None = Field(default=None, description="Resolved geo.places id, when the caller knows it")
    recorded_at: datetime | None = Field(
        default=None, description="Device clock for the fix; defaults to now. Offline queues send the real time."
    )

    @field_validator("recorded_at", mode="after")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return _ensure_utc(v)


class LiveLocationOut(BaseModel):
    """The last known position of a user."""

    user_id: int
    latitude: float | None = None
    longitude: float | None = None
    place_id: int | None = None
    accuracy_m: float | None = None
    altitude_m: float | None = None
    altitude_accuracy_m: float | None = None
    heading_deg: float | None = None
    speed_mps: float | None = None
    location_source: str | None = None
    is_moving: bool | None = None
    tracking_active: bool = False
    background_tracking_enabled: bool = False
    device_id: str | None = None
    device_type: str | None = None
    network_type: str | None = None
    ip_address: str | None = None
    recorded_at: datetime | None = None
    received_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> "LiveLocationOut":
        """Build from a ``UserLiveLocation``, unpacking the PostGIS point.

        Geography is (longitude, latitude); the wire format is latitude first.
        Done here, at the schema boundary, the same way the geo module does it —
        a second conversion convention is how the two drift apart.
        """
        out = cls.model_validate(row)
        point = getattr(row, "coordinates", None)
        if point is not None:
            from geoalchemy2.shape import to_shape

            try:
                shape = to_shape(point)
                out.longitude, out.latitude = float(shape.x), float(shape.y)
            except Exception:  # pragma: no cover — unparseable geometry
                out.longitude = out.latitude = None
        return out
