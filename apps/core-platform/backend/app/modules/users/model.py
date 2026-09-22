"""Users module — model layer.

Full port of the Laravel users migrations (base table + extended profile).
Every column preserved. Sections mirror the original migration comments.

Laravel -> SQLAlchemy type mapping:
  string -> String(255) | text/longText -> Text | timestamp/dateTimeTz ->
  DateTime(timezone=True) | date -> Date | jsonb -> JSONB | tinyInteger ->
  SmallInteger | unsignedBigInteger -> BigInteger | decimal -> Numeric |
  geography(...) -> geoalchemy2 Geography (GIST spatial index auto-created) |
  ipAddress -> String(45) | softDeletes -> deleted_at

The Laravel `sessions` table is intentionally NOT ported: sessions are
stateless JWTs + Authentik; `current_sessions`/`has_active_session` columns
cover in-app presence. `password_reset_tokens` IS ported (first-party flow).
"""

import enum
from datetime import UTC, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    ForeignKeyConstraint,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    BigIntPKWithUUIDMixin,
    DeactivationMixin,
    IntPKMixin,
    LedgerMixin,
    MultiTenantMixin,
    RowVersionMixin,
    SoftDeleteMixin,
    TenantEntityMixin,
    TimestampMixin,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(MultiTenantMixin, RowVersionMixin, AppMetaMixin, DeactivationMixin, Base):
    """A person who signs in. Belongs to ONE tenant (``tenant_id``) AND one
    organization (``organization_id``, NOT NULL); holds a role OF THAT
    ORGANIZATION (composite FK ``(tenant_id, organization_id, role_id)`` →
    ``roles``). ``email`` stays globally unique so sign-in needs no tenant
    picker (docs/tenancy/README.md §6)."""

    __tablename__ = "users"

    # == Core (base migration) ==
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email_verified_at = mapped_column(DateTime(timezone=True), nullable=True)
    password: Mapped[str] = mapped_column(String(255))
    remember_token = mapped_column(String(100), nullable=True)

    # == Core User Identification & Authentication ==
    username = mapped_column(String(255), nullable=True, unique=True, comment="Unique username for login or display")
    salutation = mapped_column(String(255), nullable=True, comment="User's salutation (e.g., Mr., Ms., Dr.)")
    first_name = mapped_column(String(255), nullable=True, comment="User's first name")
    middle_name = mapped_column(String(255), nullable=True, comment="User's middle name")
    last_name = mapped_column(String(255), nullable=True, comment="User's last name")
    phone_verified_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when the user's phone number was verified")
    two_factor_secret = mapped_column(Text, nullable=True, comment="Encrypted secret key for TOTP-based two-factor authentication")
    two_factor_recovery_codes = mapped_column(Text, nullable=True, comment="Encrypted recovery codes for two-factor authentication")
    two_factor_confirmed_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when two-factor authentication was confirmed/enabled")
    api_token = mapped_column(String(80), nullable=True, unique=True, comment="Unique token for API authentication")

    # == Status, Roles & Type ==
    role_id = mapped_column(BigInteger, nullable=True, comment="roles.id of the user's tenant (composite FK)")
    user_type = mapped_column(String(50), nullable=True, comment="Broad classification of the user (e.g., Employee, Customer, Admin)")
    status = mapped_column(String(25), nullable=True, default="active", comment="General status indicator (e.g., active, inactive, pending)")
    user_status = mapped_column(String(255), nullable=True, default="active", comment="Detailed user status (e.g., active, suspended, onboarding)")
    status_reason = mapped_column(Text, nullable=True, comment="Reason for the current user_status")
    is_deactivated = mapped_column(Boolean, nullable=True, default=False, comment="Flag indicating if the user account is deactivated")
    deactivation_date = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when the user account was deactivated")
    deactivation_reason = mapped_column(Text, nullable=True, comment="Reason provided for account deactivation")
    deactivated_by = mapped_column(BigInteger, nullable=True, comment="users.id who deactivated the account")
    is_verified = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"),
                                comment="Identity verified (KYC / admin check)")
    confirmation_status = mapped_column(SmallInteger, nullable=True, default=0, comment="Confirmation status (0 = Not Confirmed, 1 = Confirmed)")

    # == Moderation: ban (hard) & throttle (soft) ==
    # `is_deactivated` is account lifecycle; these are policy/abuse controls.
    # `*_until = NULL` means the restriction is permanent until lifted by an admin.
    is_banned = mapped_column(Boolean, nullable=True, default=False, comment="Hard ban: cannot authenticate or use the API")
    ban_reason = mapped_column(Text, nullable=True, comment="Why the account was banned")
    banned_at = mapped_column(DateTime(timezone=True), nullable=True, comment="When the ban was applied")
    banned_until = mapped_column(DateTime(timezone=True), nullable=True, comment="Ban expiry (NULL = permanent)")
    banned_by = mapped_column(BigInteger, nullable=True, comment="Actor user id that applied the ban")
    is_throttled = mapped_column(Boolean, nullable=True, default=False, comment="Soft restriction: new auth attempts are rate-limited")
    throttle_reason = mapped_column(Text, nullable=True, comment="Why the account was throttled")
    throttled_at = mapped_column(DateTime(timezone=True), nullable=True, comment="When the throttle was applied")
    throttled_until = mapped_column(DateTime(timezone=True), nullable=True, comment="Throttle expiry (NULL = until lifted)")
    throttled_by = mapped_column(BigInteger, nullable=True, comment="Actor user id that applied the throttle")

    # == Contact Information ==
    phone = mapped_column(String(255), nullable=True, comment="Primary phone number of the user")
    contact = mapped_column(String(50), nullable=True, comment="Alternative or secondary contact number/method")

    # == Personal Information ==
    gender = mapped_column(String(50), nullable=True, comment="User's gender")
    date_of_birth = mapped_column(Date, nullable=True, comment="User's date of birth")
    is_married = mapped_column(Boolean, nullable=True, default=False, comment="Marital status flag")
    citizenship = mapped_column(String(255), nullable=True, comment="User's citizenship")
    blood_group = mapped_column(String(255), nullable=True, comment="User's blood group")
    pan = mapped_column(String(255), nullable=True, comment="User's Permanent Account Number (PAN)")
    gstin = mapped_column(String(255), nullable=True, comment="User's GST Identification Number (GSTIN)")
    tax_preference = mapped_column(String(255), nullable=True, comment="User's tax preference setting")
    gst_treatment = mapped_column(String(255), nullable=True, comment="User's GST treatment status")
    languages_known = mapped_column(JSONB, nullable=True, comment="JSON array of languages known by the user")
    social_links = mapped_column(JSONB, nullable=True, comment="JSON object containing links to social media profiles")
    emergency_contact = mapped_column(JSONB, nullable=True, comment="JSON object with emergency contact details")
    medical_history = mapped_column(JSONB, nullable=True, comment="JSON object containing relevant medical history")
    insurance_details = mapped_column(JSONB, nullable=True, comment="JSON object with insurance policy details")

    # == Parent / Family Information ==
    parent_one_gender = mapped_column(String(50), nullable=True, comment="Gender of the first parent/guardian")
    parent_two_gender = mapped_column(String(50), nullable=True, comment="Gender of the second parent/guardian")
    parent_one_contact = mapped_column(String(50), nullable=True, comment="Contact information for the first parent/guardian")
    parent_two_contact = mapped_column(String(50), nullable=True, comment="Contact information for the second parent/guardian")
    family_details = mapped_column(JSONB, nullable=True, comment="JSON object containing details about family members")

    # == Professional / Work / Education Information ==
    occupation = mapped_column(String(255), nullable=True, comment="User's primary occupation")
    designation = mapped_column(String(255), nullable=True, comment="User's job title or designation")
    department = mapped_column(String(255), nullable=True, comment="Department the user belongs to")
    education_qualification = mapped_column(Text, nullable=True, comment="Highest education qualification achieved")
    education_specialization = mapped_column(Text, nullable=True, comment="Specialization within the education qualification")
    education_history = mapped_column(JSONB, nullable=True, comment="JSON array detailing educational background")
    work_history = mapped_column(JSONB, nullable=True, comment="JSON array detailing previous work experience")
    reference_details = mapped_column(JSONB, nullable=True, comment="JSON object containing professional or personal references")
    referred_by_user_id = mapped_column(BigInteger, nullable=True, comment="User ID of the person who referred this user")
    communication_preferences = mapped_column(JSONB, nullable=True, comment="JSON object for communication channel preferences")

    # == Company Information (User's Employer/Affiliation) ==
    company_name = mapped_column(String(255), nullable=True, comment="Name of the company the user is associated with")
    company_address = mapped_column(Text, nullable=True, comment="Address of the associated company")
    company_email = mapped_column(String(255), nullable=True, comment="Email address of the associated company")
    company_phone = mapped_column(String(255), nullable=True, comment="Phone number of the associated company")
    company_website = mapped_column(String(255), nullable=True, comment="Website URL of the associated company")
    company_gstin = mapped_column(String(255), nullable=True, comment="GSTIN of the associated company")
    company_pan = mapped_column(String(255), nullable=True, comment="PAN of the associated company")
    company_cin = mapped_column(String(255), nullable=True, comment="CIN of the associated company")
    company_tan = mapped_column(String(255), nullable=True, comment="TAN of the associated company")
    date_of_joining = mapped_column(DateTime(timezone=True), nullable=True, comment="Date/time (with tz) when the user joined the company/platform")

    # == Membership & Session Information ==
    member_id = mapped_column(String(255), nullable=True, comment="Unique identifier for membership, if applicable")
    current_sessions = mapped_column(JSONB, nullable=True, comment="JSON data storing details about active user sessions")
    has_active_session = mapped_column(Boolean, nullable=True, default=False, comment="Flag indicating if the user currently has an active session")
    zoho_user_id = mapped_column(String(255), nullable=True, comment="Unique identifier for the user in Zoho, if applicable")
    onboarding_status = mapped_column(String(255), nullable=True, comment="Status of the user's onboarding process")

    # == Profile Customization ==
    image = mapped_column(String(255), nullable=True, default="default.png", comment="Filename of the main profile picture")
    avatar = mapped_column(String(255), nullable=True, default="avatar.png", comment="Filename of the avatar image")
    thumbnail = mapped_column(String(255), nullable=True, default="default.png", comment="Filename of the profile picture thumbnail")
    preview_image = mapped_column(String(255), nullable=True, default="default.png", comment="Filename of a preview-sized profile image")
    profile_completion_percentage = mapped_column(SmallInteger, nullable=True, default=0, comment="Profile completion percentage (0-100)")
    other_details = mapped_column(JSONB, nullable=True, comment="JSON object for miscellaneous user details")
    other_information = mapped_column(JSONB, nullable=True, comment="JSON object for other structured information")
    payment_details = mapped_column(JSONB, nullable=True, comment="JSON object storing preferred payment methods or details")
    bank_details = mapped_column(JSONB, nullable=True, comment="JSON object storing bank account details")
    billing_address = mapped_column(JSONB, nullable=True, comment="JSON object representing the default billing address")
    shipping_address = mapped_column(JSONB, nullable=True, comment="JSON object representing the default shipping address")

    # == Preferences ==
    language = mapped_column(String(255), nullable=True, default="en", comment="Preferred language code")
    timezone = mapped_column(
        String(64), nullable=True, default="Asia/Kolkata",
        comment="CACHE of user_profiles.timezone_name (auth emails read it without a join)",
    )
    date_format = mapped_column(String(255), nullable=True, default="d-m-Y", comment="Preferred date format")
    time_format = mapped_column(String(255), nullable=True, default="H:i", comment="Preferred time format")
    currency = mapped_column(String(255), nullable=True, default="INR", comment="Preferred currency code")
    currency_symbol = mapped_column(String(255), nullable=True, default="₹", comment="Preferred currency symbol")
    thousand_separator = mapped_column(String(255), nullable=True, default=",", comment="Preferred thousand separator")
    decimal_separator = mapped_column(String(255), nullable=True, default=".", comment="Preferred decimal separator")
    locale_settings = mapped_column(JSONB, nullable=True, comment="JSON object for detailed locale preferences")
    online_status_preference = mapped_column(SmallInteger, nullable=True, default=0, comment="Online status display preference")
    is_location_set = mapped_column(Boolean, nullable=True, default=False, comment="Whether the user explicitly set a primary location")
    application_settings = mapped_column(JSONB, nullable=True, comment="JSON object for user-specific application settings")
    default_language = mapped_column(String(10), nullable=True, default="en", comment="Fallback or default language preference")

    # == Location ==
    # Addresses and coordinates live in the location hub (geo.place_links →
    # geo.places); live position lives in `user_live_locations`. The two columns
    # kept here are caches/pointers for cheap reads.
    country_code = mapped_column(
        String(2),
        nullable=True,
        comment="CACHE of user_profiles.country_iso2, for cheap list filtering",
    )
    primary_place_id = mapped_column(
        BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"), nullable=True,
        comment="CACHE of the primary address link's place (maintained by the address service)",
    )

    # == Device metadata (auth/device binding) ==
    device_id = mapped_column(String(255), nullable=True, comment="Identifier of the device last used to sign in")
    device_type = mapped_column(String(255), nullable=True, comment="Type of the device (mobile, web, sensor)")

    # == Integration IDs ==
    external_id = mapped_column(String(255), nullable=True, unique=True, comment="Unique identifier for linking to an external system (Authentik sub / uuid)")
    # Outbound Authentik mirror (app -> Authentik). authentik_pk is the Authentik
    # admin-API user id used to address all update/password/delete calls.
    # See app/modules/users/authentik_sync.py + docs/AUTHENTIK_SYNC.md.
    authentik_pk = mapped_column(String(36), nullable=True, unique=True, comment="Authentik admin-API user id (pk) for outbound sync")
    authentik_sync_status = mapped_column(String(50), nullable=True, default="pending", comment="pending | synced | failed | password_drift | skipped")
    authentik_sync_error = mapped_column(Text, nullable=True, comment="Last Authentik sync error (truncated)")
    authentik_synced_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp of the last successful Authentik sync")
    zoho_id = mapped_column(String(255), nullable=True, comment="Generic Zoho ID, if applicable")
    zoho_customer_id = mapped_column(String(255), nullable=True, comment="Zoho CRM Customer ID")
    zoho_contact_id = mapped_column(String(255), nullable=True, comment="Zoho CRM Contact ID")

    # == Target tracking ==
    targets = mapped_column(JSONB, nullable=True, comment="JSON object for tracking user targets or goals")
    target_history = mapped_column(JSONB, nullable=True, comment="JSON object for tracking historical target data")
    target_progress = mapped_column(JSONB, nullable=True, comment="JSON object for tracking progress against targets")
    target_achievements = mapped_column(JSONB, nullable=True, comment="JSON object for tracking achievements against targets")
    target_achievements_history = mapped_column(JSONB, nullable=True, comment="JSON object for historical achievements against targets")

    # == Synchronization & Login Tracking ==
    last_sync_time = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp of the last data synchronization")
    last_login = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp of the last successful login")
    last_password_change_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when the password was last changed")
    failed_login_attempts = mapped_column(Integer, nullable=True, default=0, comment="Count of consecutive failed login attempts")
    locked_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when the account was locked due to failed attempts")

    # == Audit & Timestamps ==
    created_by = mapped_column(BigInteger, nullable=True, comment="ID of the user who created this record")
    created_by_name = mapped_column(String(255), nullable=True, comment="Creator display name at the time")
    updated_by = mapped_column(BigInteger, nullable=True, comment="ID of the user who last updated this record")
    updated_by_name = mapped_column(String(255), nullable=True, comment="Last updater display name at the time")
    deleted_by = mapped_column(BigInteger, nullable=True, comment="ID of the user who soft-deleted this record")
    created_at = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    deleted_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp")
    deleted_reason = mapped_column(Text, nullable=True, comment="Why the account was deleted")

    __table_args__ = (
        # Target of children's composite FKs (user_live_locations, telemetry, …).
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
        Index("users_first_last_name_index", "first_name", "last_name"),
        Index("users_phone_index", "phone"),
        Index("users_status_index", "status"),
        Index("users_role_id_index", "role_id"),
        Index("users_user_type_index", "user_type"),
        Index("users_member_id_index", "member_id"),
        Index("users_company_name_index", "company_name"),
        Index("ix_users_country_code", "country_code"),
        Index("users_last_login_index", "last_login"),
        Index("users_device_id_index", "device_id"),
        Index("users_authentik_sync_status_index", "authentik_sync_status"),
        # Zoho crosswalk: unique among live rows (matches every Zoho mirror).
        Index("uq_users_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("users_zoho_customer_id_index", "zoho_customer_id"),
        Index("users_zoho_contact_id_index", "zoho_contact_id"),
        Index("users_created_by_index", "created_by"),
        Index("users_updated_by_index", "updated_by"),
        Index("users_deleted_by_index", "deleted_by"),
        Index("users_deleted_at_index", "deleted_at"),
        Index("ix_users_is_banned", "is_banned"),
        Index("ix_users_is_throttled", "is_throttled"),
        Index("ix_users_primary_place", "primary_place_id",
              postgresql_where=text("primary_place_id IS NOT NULL")),
        # A user's role must belong to the user's own organization.
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "role_id"],
            ["roles.tenant_id", "roles.organization_id", "roles.id"],
            name="fk_users_tenant_org_role", ondelete="RESTRICT",
        ),
    )

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None and not self.is_deactivated and not self.is_banned

    def deactivate(self, *, reason: str | None = None, by: int | None = None) -> None:
        super().deactivate(reason=reason, by=by)
        self.is_deactivated = True

    def reactivate(self) -> None:
        super().reactivate()
        self.is_deactivated = False


class PasswordResetToken(LedgerMixin, Base):
    """Port of Laravel's password_reset_tokens table, hardened for OTP resets.

    One *active* reset per email (email is the PK). The one-time code is stored
    only as a keyed HMAC (``code_hash``); the high-entropy ``token`` backs the
    link flow. Expiry, attempt cap, resend cooldown and send-count are all on
    the row so brute-forcing a 4-digit code is bounded by data, not by luck.
    """

    __tablename__ = "password_reset_tokens"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    token: Mapped[str] = mapped_column(String(255), comment="High-entropy token for the link flow")
    reset_type: Mapped[str] = mapped_column(String(255), default="code", comment="'link' or 'code'")
    code_hash: Mapped[str | None] = mapped_column(String(255), comment="HMAC-SHA256 of the one-time code")
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False, server_default="5")
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_ip: Mapped[str | None] = mapped_column(String(45))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at = mapped_column(DateTime(timezone=True), nullable=True, default=_utcnow)


class LoginOtpToken(LedgerMixin, Base):
    """One-time login code challenge (passwordless email OTP).

    One active challenge per email. The code is stored only as a keyed HMAC;
    expiry, attempt cap, resend cooldown and send-count live on the row so a
    6-digit code is bounded by data, not by luck.
    """

    __tablename__ = "login_otp_tokens"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(255), comment="HMAC-SHA256 of the one-time code")
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False, server_default="5")
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_ip: Mapped[str | None] = mapped_column(String(45))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at = mapped_column(DateTime(timezone=True), nullable=True, default=_utcnow)


class TimezoneSource(str, enum.Enum):
    auto = "auto"
    manual = "manual"


class Country(TimestampMixin, Base):
    """ISO 3166-1 reference table of countries."""

    __tablename__ = "countries"

    iso2: Mapped[str] = mapped_column(String(2), primary_key=True)
    iso3: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    numeric_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    official_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    region: Mapped[str | None] = mapped_column(String(75), nullable=True)
    subregion: Mapped[str | None] = mapped_column(String(75), nullable=True)
    phone_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(5), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    timezones: Mapped[list["CountryTimezone"]] = relationship(
        "CountryTimezone", back_populates="country", cascade="all, delete-orphan", lazy="selectin"
    )


class Timezone(Base):
    """Reference table of IANA tz database timezone identifiers."""

    __tablename__ = "timezones"

    iana_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CountryTimezone(Base):
    """Mapping table: a country can have multiple timezones (e.g. US, RU, AU, BR, CA)."""

    __tablename__ = "country_timezones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_iso2: Mapped[str] = mapped_column(
        String(2), ForeignKey("countries.iso2", ondelete="CASCADE"), nullable=False
    )
    timezone_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("timezones.iana_name", ondelete="CASCADE"), nullable=False
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    country: Mapped["Country"] = relationship("Country", back_populates="timezones")
    timezone: Mapped["Timezone"] = relationship("Timezone")

    __table_args__ = (
        Index("uq_country_timezone", "country_iso2", "timezone_name", unique=True),
        Index(
            "uq_country_default_tz",
            "country_iso2",
            unique=True,
            postgresql_where=text("is_default = TRUE"),
        ),
    )


class UserProfile(BigIntPKWithUUIDMixin, TenantEntityMixin, SoftDeleteMixin, Base):
    """User profile localization preferences: auto-unless-overridden timezone logic."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    country_iso2: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("countries.iso2", ondelete="SET NULL"), nullable=True
    )
    timezone_name: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("timezones.iana_name", ondelete="SET NULL"), nullable=True
    )
    timezone_source: Mapped[TimezoneSource] = mapped_column(
        Enum(TimezoneSource, native_enum=False, length=10),
        default=TimezoneSource.auto,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", backref="profile")
    country: Mapped["Country | None"] = relationship("Country")
    timezone: Mapped["Timezone | None"] = relationship("Timezone")

    __table_args__ = (
        Index("idx_user_profiles_country", "country_iso2"),
        CheckConstraint("timezone_source IN ('auto', 'manual')", name="ck_user_profiles_tz_source"),
    )


# =============================================================================
# Live location telemetry — isolated from the users master row.
# =============================================================================
class UserLiveLocation(IntPKMixin, MultiTenantMixin, AppMetaMixin, TimestampMixin, Base):
    """One row per user — the last known position.

    Hot (upserted on every fix) but isolated from the ``users`` row, so GPS
    writes never contend with authentication/profile reads. Write path is a
    single ``INSERT ... ON CONFLICT (tenant_id, user_id) DO UPDATE``. This is
    what dispatch/beat-planning reads.
    """

    __tablename__ = "user_live_locations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_user_live_locations_user"),
        CheckConstraint("accuracy_m IS NULL OR accuracy_m >= 0", name="chk_user_live_accuracy"),
        CheckConstraint("heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)",
                        name="chk_user_live_heading"),
        CheckConstraint("speed_mps IS NULL OR speed_mps >= 0", name="chk_user_live_speed"),
        Index("ix_user_live_locations_recorded", "tenant_id", "recorded_at"),
        {"comment": "Last known position per user (hot but isolated from the users row)."},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    coordinates: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True,
        comment="WGS84 point (longitude, latitude)",
    )
    place_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"),
        comment="Nearest/resolved place, if any",
    )
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    altitude_accuracy_m: Mapped[float | None] = mapped_column(Float)
    heading_deg: Mapped[float | None] = mapped_column(Float)
    speed_mps: Mapped[float | None] = mapped_column(Float)
    location_source: Mapped[str | None] = mapped_column(String(20), comment="gps / network / manual")
    is_moving: Mapped[bool | None] = mapped_column(Boolean)
    tracking_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    background_tracking_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    device_id: Mapped[str | None] = mapped_column(String(255))
    device_type: Mapped[str | None] = mapped_column(String(50))
    network_type: Mapped[str | None] = mapped_column(String(50))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="Device clock")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<UserLiveLocation user={self.user_id} recorded_at={self.recorded_at}>"


class UserLocationPing(MultiTenantMixin, AppMetaMixin, Base):
    """Append-only location history; monthly RANGE partitions on ``recorded_at``.

    Partitions are managed by pg_partman; retention is a partition drop and the
    window is a ``data_retention_schedules`` row (``location_history``).
    """

    __tablename__ = "user_location_pings"
    __table_args__ = (
        # Partitioned by recorded_at, so the PK must include it.
        PrimaryKeyConstraint("recorded_at", "id", name="pk_user_location_pings"),
        Index("ix_user_location_pings_user_time", "tenant_id", "user_id", text("recorded_at DESC")),
        Index("ix_user_location_pings_time", "tenant_id", text("recorded_at DESC")),
        {"postgresql_partition_by": "RANGE (recorded_at)",
         "comment": "Append-only location history; monthly partitions via pg_partman."},
    )

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    coordinates: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True,
    )
    place_id: Mapped[int | None] = mapped_column(BigInteger)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    heading_deg: Mapped[float | None] = mapped_column(Float)
    speed_mps: Mapped[float | None] = mapped_column(Float)
    location_source: Mapped[str | None] = mapped_column(String(20))
    device_id: Mapped[str | None] = mapped_column(String(255))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<UserLocationPing user={self.user_id} recorded_at={self.recorded_at}>"
