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

from datetime import UTC, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
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
    role_id = mapped_column(Integer, nullable=True, default=-1, comment="Foreign key referencing the roles table")
    user_type = mapped_column(String(50), nullable=True, comment="Broad classification of the user (e.g., Employee, Customer, Admin)")
    status = mapped_column(String(25), nullable=True, default="active", comment="General status indicator (e.g., active, inactive, pending)")
    user_status = mapped_column(String(255), nullable=True, default="active", comment="Detailed user status (e.g., active, suspended, onboarding)")
    status_reason = mapped_column(Text, nullable=True, comment="Reason for the current user_status")
    is_deactivated = mapped_column(Boolean, nullable=True, default=False, comment="Flag indicating if the user account is deactivated")
    deactivation_date = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when the user account was deactivated")
    deactivation_reason = mapped_column(Text, nullable=True, comment="Reason provided for account deactivation")
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
    timezone = mapped_column(String(255), nullable=True, default="Asia/Kolkata", comment="Preferred timezone")
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

    # == Location Information (Textual / Administrative) ==
    constituency = mapped_column(String(255), nullable=True, comment="Name of the political constituency")
    sub_constituency = mapped_column(String(255), nullable=True, comment="Name of the sub-constituency")
    assembly_constituency = mapped_column(String(255), nullable=True, comment="Name of the assembly constituency")
    parliamentary_constituency = mapped_column(String(255), nullable=True, comment="Name of the parliamentary constituency")
    pincode = mapped_column(String(255), nullable=True, comment="Postal Index Number (PIN) code")
    street_address = mapped_column(Text, nullable=True, comment="User's street address")
    landmark = mapped_column(String(255), nullable=True, comment="Nearby landmark for the address")
    village_town = mapped_column(String(255), nullable=True, comment="Name of the village or town")
    taluka = mapped_column(String(255), nullable=True, comment="Name of the taluka or sub-district")
    district = mapped_column(String(255), nullable=True, comment="Name of the district")
    city = mapped_column(String(255), nullable=True, comment="Name of the city")
    state = mapped_column(String(255), nullable=True, comment="Name of the state or province")
    postal_code = mapped_column(String(255), nullable=True, comment="Postal code")
    country = mapped_column(String(255), nullable=True, comment="Name of the country")

    # == Location Information (Geospatial — PostGIS Geography, SRID 4326) ==
    # geoalchemy2 creates GIST spatial indexes automatically for these columns
    location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True, comment="Primary geographic location (Point: lng, lat)")
    current_location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True, comment="Last known current geographic location")
    route_points = mapped_column(Geography(geometry_type="LINESTRING", srid=4326), nullable=True, comment="Series of geographic points representing a route")
    constituency_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the constituency")
    sub_constituency_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the sub-constituency")
    assembly_constituency_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the assembly constituency")
    parliamentary_constituency_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the parliamentary constituency")
    pincode_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary corresponding to the pincode")
    taluka_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the taluka")
    district_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the district")
    city_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the city")
    state_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the state")
    country_geometry = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True, comment="Geographic boundary of the country")

    # == Location Information (Coordinates & IDs) ==
    latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Latitude coordinate")
    longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Longitude coordinate")
    coordinates = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True, comment="Alternative storage for geographic coordinates")
    current_pincode = mapped_column(String(20), nullable=True, comment="Pincode associated with the current location")
    current_location_latitude = mapped_column(String(255), nullable=True, comment="Latitude of the current location")
    current_location_longitude = mapped_column(String(255), nullable=True, comment="Longitude of the current location")
    constituency_latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Representative latitude for the constituency")
    constituency_longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Representative longitude for the constituency")
    district_latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Representative latitude for the district")
    district_longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Representative longitude for the district")
    taluka_latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Representative latitude for the taluka")
    taluka_longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Representative longitude for the taluka")
    city_latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Representative latitude for the city")
    city_longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Representative longitude for the city")
    state_latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Representative latitude for the state")
    state_longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Representative longitude for the state")
    country_latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Representative latitude for the country")
    country_longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Representative longitude for the country")
    postal_code_latitude = mapped_column(Numeric(10, 8), nullable=True, comment="Representative latitude for the postal code area")
    postal_code_longitude = mapped_column(Numeric(11, 8), nullable=True, comment="Representative longitude for the postal code area")
    constituency_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the constituency")
    sub_constituency_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the sub-constituency")
    assembly_constituency_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the assembly constituency")
    parliamentary_constituency_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the parliamentary constituency")
    pincode_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the pincode area")
    taluka_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the taluka")
    district_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the district")
    city_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the city")
    state_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the state")
    country_geonameId = mapped_column(String(255), nullable=True, comment="GeoNames ID for the country")

    # == Location Tracking & Metadata ==
    altitude = mapped_column(Numeric(10, 8), nullable=True, comment="Altitude in meters above sea level")
    altitude_accuracy = mapped_column(Float, nullable=True, comment="Accuracy of the altitude measurement in meters")
    heading = mapped_column(Float, nullable=True, comment="Direction of travel in degrees (0-359.9)")
    speed = mapped_column(Float, nullable=True, comment="Speed of travel in meters per second")
    location_accuracy = mapped_column(String(255), nullable=True, comment="Accuracy of the location measurement in meters")
    location_source = mapped_column(String(255), nullable=True, comment="Source of the location data (gps, network, manual)")
    location_timestamp = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when the location was recorded by the source")
    location_timezone = mapped_column(String(255), nullable=True, comment="Timezone detected at the location")
    location_ip = mapped_column(String(45), nullable=True, comment="IP address associated with the location capture event")
    geocode = mapped_column(JSONB, nullable=True, comment="JSON object containing reverse geocoding results")
    recorded_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp when the location record was saved")
    last_tracked_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp of the very last tracking update received")
    device_id = mapped_column(String(255), nullable=True, comment="Identifier of the device providing tracking data")
    device_type = mapped_column(String(255), nullable=True, comment="Type of the device (mobile, web, sensor)")
    network_type = mapped_column(String(255), nullable=True, comment="Network type used during tracking (wifi, cellular)")
    is_tracking_active = mapped_column(Boolean, nullable=True, default=False, comment="Whether location tracking is currently active")
    background_tracking_enabled = mapped_column(Boolean, nullable=True, default=False, comment="Whether background location tracking is enabled")

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
    updated_by = mapped_column(BigInteger, nullable=True, comment="ID of the user who last updated this record")
    deleted_by = mapped_column(BigInteger, nullable=True, comment="ID of the user who soft-deleted this record")
    created_at = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    deleted_at = mapped_column(DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp")

    __table_args__ = (
        Index("users_first_last_name_index", "first_name", "last_name"),
        Index("users_phone_index", "phone"),
        Index("users_status_index", "status"),
        Index("users_role_id_index", "role_id"),
        Index("users_user_type_index", "user_type"),
        Index("users_member_id_index", "member_id"),
        Index("users_company_name_index", "company_name"),
        Index("users_pincode_index", "pincode"),
        Index("users_city_index", "city"),
        Index("users_state_index", "state"),
        Index("users_country_index", "country"),
        Index("users_last_login_index", "last_login"),
        Index("users_last_tracked_at_index", "last_tracked_at"),
        Index("users_device_id_index", "device_id"),
        Index("users_authentik_sync_status_index", "authentik_sync_status"),
        Index("users_zoho_id_index", "zoho_id"),
        Index("users_zoho_customer_id_index", "zoho_customer_id"),
        Index("users_zoho_contact_id_index", "zoho_contact_id"),
        Index("users_created_by_index", "created_by"),
        Index("users_updated_by_index", "updated_by"),
        Index("users_deleted_by_index", "deleted_by"),
        Index("users_deleted_at_index", "deleted_at"),
        Index("ix_users_is_banned", "is_banned"),
        Index("ix_users_is_throttled", "is_throttled"),
    )

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None and not self.is_deactivated and not self.is_banned


class PasswordResetToken(Base):
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


class LoginOtpToken(Base):
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
