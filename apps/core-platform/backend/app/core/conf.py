"""Central application settings.

Every tunable lives here, loaded from environment variables (12-factor).
Docker injects env vars via docker-compose; local dev falls back to .env.
"""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application ---
    APP_NAME: str = "core-platform"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"  # development | staging | production
    DEBUG: bool = False
    API_PREFIX: str = "/api"
    # Swagger UI / OpenAPI schema. Always on outside production; in production it
    # is off unless this is set true (the schema exposes the whole API surface —
    # keep the route behind auth and disable it again afterwards).
    DOCS_ENABLED: bool = False

    # --- Logging (see app/core/logging/ + config/logging/*.yaml) ---
    # Directory holding logging.yaml + environments/ + modules/ (relative to
    # the backend root, or an absolute path). The active ENVIRONMENT selects
    # the profile under environments/.
    LOG_CONFIG_DIR: str = "config/logging"
    # Optional ops overrides — when set, these win over the YAML files.
    # LOG_LEVEL also keeps backward compatibility with existing tooling/compose.
    LOG_LEVEL: str | None = None      # CRITICAL|ERROR|WARNING|INFO|DEBUG
    LOG_FORMAT: str | None = None     # json | console
    LOG_ENABLED: bool | None = None   # master switch override

    # Compose passes optional overrides as `${VAR:-}` → an EMPTY STRING, not an
    # absent var. Treat empty/whitespace as "unset" so the value falls back to
    # the YAML logging profile instead of failing bool/enum parsing.
    @field_validator("LOG_LEVEL", "LOG_FORMAT", "LOG_ENABLED", mode="before")
    @classmethod
    def _blank_env_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # Typst list options arrive as JSON arrays; compose passes `${VAR:-}` → ""
    # when unset. These fields are annotated `NoDecode` so pydantic-settings
    # hands us the raw env string instead of JSON-parsing it at the source —
    # source-level decoding runs before validators and blows up on "". We do
    # the parsing here: blank → [], a JSON array string → the list, otherwise
    # a comma-separated fallback.
    @field_validator("TYPST_FONT_PATHS", "TYPST_PDF_STANDARDS", mode="before")
    @classmethod
    def _blank_env_to_empty_list(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                return []
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return [item.strip() for item in s.split(",") if item.strip()]
        return v

    # --- Tenancy (docs/tenancy/README.md) ---
    # Rows written outside any tenant context (seeders, system tasks, the
    # single-tenant default) belong to this tenant. Created by the migration.
    DEFAULT_TENANT_CODE: str = "default"
    # Organization new rows belong to when no organization context is set.
    # Matched by org_code WITHIN the row's tenant. Empty = tenant-wide rows
    # (organization_id stays NULL). Point this at the seeded root organization
    # (scripts/seed.py / app/modules/tenants/seed.py) for a single-org setup.
    DEFAULT_ORGANIZATION_CODE: str = ""
    # Platform administrators (manage tenants): comma-separated emails.
    # Empty = nobody in production, any authenticated user when DEBUG=true.
    PLATFORM_ADMIN_EMAILS: str = ""

    # --- Seeded tenant + root organization (app/modules/tenants/seed.py) ---
    # `scripts/seed.py` creates this tenant and its root organization
    # idempotently from the values below. Point DEFAULT_TENANT_CODE /
    # DEFAULT_ORGANIZATION_CODE at COMPANY_TENANT_CODE / COMPANY_ORGANIZATION_CODE
    # so every row written without a context is scoped to them.
    COMPANY_TENANT_CODE: str = "THPL"
    COMPANY_TENANT_NAME: str = "Tarrina Health Private Limited"
    COMPANY_TIMEZONE: str = "Asia/Kolkata"
    COMPANY_LOCALE: str = "en-IN"
    COMPANY_ORGANIZATION_CODE: str = "THPL"
    COMPANY_LEGAL_NAME: str = "Tarrina Health Private Limited"
    # Trading / display name (defaults to COMPANY_LEGAL_NAME when empty).
    COMPANY_TRADING_NAME: str = "Tarrina Health"
    COMPANY_NAME: str = "Tarrina Health Private Limited"
    COMPANY_ADDRESS_LINE_ONE: str = ""
    COMPANY_ADDRESS_LINE_TWO: str = ""
    COMPANY_COUNTRY: str = "India"
    COMPANY_GSTIN: str = ""
    COMPANY_PHONE_ONE: str = ""
    COMPANY_PHONE_TWO: str = ""
    COMPANY_BANK_NAME: str = ""
    COMPANY_ACCOUNT_NUMBER: str = ""
    COMPANY_IFSC_CODE: str = ""
    COMPANY_PHONE: str = ""
    COMPANY_EMAIL: str = ""
    COMPANY_WEBSITE: str = ""
    # Seeded admin user for the root organization (idempotent). It is bound to
    # the system role COMPANY_ADMIN_ROLE (owner | admin | member). Empty
    # COMPANY_ADMIN_PASSWORD = skip the user (the tenant/organization still seed).
    # Empty COMPANY_ADMIN_EMAIL = COMPANY_EMAIL.
    COMPANY_ADMIN_NAME: str = "Tarrina Health Admin"
    COMPANY_ADMIN_EMAIL: str = ""
    COMPANY_ADMIN_USERNAME: str = ""
    COMPANY_ADMIN_PASSWORD: str = ""
    COMPANY_ADMIN_ROLE: str = "owner"

    # --- Documents (docs/documents/README.md) ---
    # pgcrypto passphrase for documents.document_number_full_encrypted (only
    # for types with allows_full_number_storage). Empty = FAIL CLOSED: the full
    # number is never stored, only the masked form. Generate: openssl rand -base64 48
    DOCUMENT_NUMBER_ENCRYPTION_KEY: str = ""

    # --- CORS ---
    CORS_ORIGINS: list[str] = []
    CORS_CREDENTIALS: bool = True

    # --- PostgreSQL ---
    DATABASE_URL: str = "postgresql+asyncpg://app:app_password@localhost:5432/app_db"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_ECHO: bool = False

    # --- Redis ---
    # DB allocation: 0=app cache, 1=authentik, 2=celery broker, 3=celery results
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50

    # --- Celery ---
    CELERY_BROKER_URL: str = "redis://localhost:6379/2"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/3"

    # --- Kafka (domain events -> ClickHouse analytics pipeline) ---
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:19092"
    KAFKA_EVENTS_TOPIC: str = "domain-events"

    # --- JWT (first-party tokens; Authentik OIDC is the IdP for humans) ---
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    JWT_REFRESH_EXPIRATION_DAYS: int = 30

    # --- Authentik OIDC (SSO; users are JIT-provisioned into the users table) ---
    AUTHENTIK_ENABLED: bool = False
    AUTHENTIK_ISSUER: str = ""        # e.g. https://auth.app.local/application/o/core-platform/
    AUTHENTIK_JWKS_URL: str = ""      # defaults to <issuer>jwks/ when empty
    AUTHENTIK_AUDIENCE: str = ""      # the Authentik provider's client_id

    # --- Authentik Admin API (OUTBOUND user sync: app -> Authentik) ---
    # Mirrors local users into Authentik via a service-account token. Distinct
    # from the OIDC settings above (which only VALIDATE inbound tokens).
    # See app/common/security/authentik_client.py + docs/AUTHENTIK_SYNC.md.
    AUTHENTIK_SYNC_ENABLED: bool = False
    AUTHENTIK_BASE_URL: str = ""              # internal root, e.g. http://authentik-server:9000
    AUTHENTIK_SERVICE_TOKEN: str = ""         # long-lived API token of an Authentik service account
    AUTHENTIK_TIMEOUT_SECONDS: float = 10.0
    AUTHENTIK_USER_PATH: str = "users"        # Authentik directory path for created users
    AUTHENTIK_USER_TYPE: str = "internal"     # internal | external (Authentik user type)

    # --- Account lockout (first-party logins) ---
    AUTH_MAX_FAILED_LOGINS: int = 5
    AUTH_LOCKOUT_MINUTES: int = 15

    # --- Rate limiting ---
    RATE_LIMIT_PER_MINUTE: int = 60

    # --- Geocoding & routing (app/modules/geo/geocoding, docs/geo/geocoding.md) ---
    # Off by default: no deployment should start making paid third-party calls
    # because a key happened to be present in the environment.
    GEOCODING_ENABLED: bool = False
    GEOCODING_PROVIDER: str = ""              # google | mapbox | nominatim | pelias
    GEOCODING_FALLBACK_PROVIDERS: str = ""    # comma-separated, tried in order
    GEOCODING_DEFAULT_COUNTRY: str = "IN"     # ISO alpha-2 bias; "" = worldwide
    GEOCODING_DEFAULT_LANGUAGE: str = "en"
    # Licence ceiling for cached payloads. Google permits 30 days for geocodes
    # (place_id indefinitely); self-hosted instances impose no limit.
    GEOCODING_CACHE_DAYS: int = 30
    GEOCODING_ROUTING_CACHE_DAYS: int = 1     # roads are slow to change, traffic is not
    GEOCODING_TIMEOUT_SECONDS: float = 8.0
    GEOCODING_CONNECT_TIMEOUT_SECONDS: float = 3.0
    GEOCODING_MAX_ATTEMPTS: int = 3
    GEOCODING_RETRY_BACKOFF_SECONDS: float = 0.5
    # Local spend guard. A provider's own published policy is a ceiling this
    # cannot raise (public Nominatim allows ~1 req/s).
    GEOCODING_MAX_CALLS_PER_MINUTE: int = 60
    # Circuit breaker: N consecutive transient failures within the window open
    # the circuit for the recovery period. Fails OPEN when Redis is down.
    GEOCODING_CB_FAILURES: int = 5
    GEOCODING_CB_WINDOW_SECONDS: int = 120
    GEOCODING_CB_RECOVERY_SECONDS: int = 60
    # Provider credentials and endpoints
    GOOGLE_MAPS_API_KEY: str = ""
    MAPBOX_ACCESS_TOKEN: str = ""
    GEOCODING_MAPBOX_BASE_URL: str = ""       # "" = Mapbox Geocoding v6
    GEOCODING_NOMINATIM_BASE_URL: str = ""    # "" = the public OSM instance
    # Nominatim rejects anonymous traffic; its policy asks for contact details.
    GEOCODING_NOMINATIM_USER_AGENT: str = ""
    GEOCODING_PELIAS_BASE_URL: str = ""
    GEOCODING_PELIAS_API_KEY: str = ""
    # Routing. "" = straight-line distances computed locally, no durations.
    # Valhalla is a ROUTING engine and cannot geocode; pair it with Pelias.
    ROUTING_PROVIDER: str = ""                # valhalla | google | mapbox | haversine
    ROUTING_VALHALLA_BASE_URL: str = ""

    # --- Zoho Books ---
    ZOHO_CLIENT_ID: str = ""
    ZOHO_CLIENT_SECRET: str = ""
    ZOHO_REFRESH_TOKEN: str = ""
    ZOHO_ACCOUNTS_URL: str = "https://accounts.zoho.in"
    ZOHO_API_BASE_URL: str = "https://www.zohoapis.in/books/v3"
    ZOHO_ORGANIZATION_ID: str = ""
    # Tenant that owns this deployment's Zoho connection (empty = DEFAULT_TENANT_CODE).
    # Mirror rows are written into it, attached to the organization node whose
    # zoho_id = ZOHO_ORGANIZATION_ID.
    ZOHO_TENANT_CODE: str = ""
    # Connection readiness (GET /api/zoho/auth/connection): with no successful
    # Zoho call for this long, ?probe=auto makes ONE live org-scoped call.
    ZOHO_CONNECTION_PROBE_AFTER_SECONDS: int = 900
    ZOHO_CONNECTION_PROBE_CACHE_SECONDS: int = 60
    ZOHO_TIMEOUT_SECONDS: float = 30.0      # read timeout per attempt
    # Debug: log every Zoho request/response (URL, query, bodies — truncated) as
    # `zoho.transport.http_exchange`. Bodies carry business and personal data:
    # dev or short diagnoses only. The OAuth token is a header and never logged.
    ZOHO_HTTP_LOG_BODIES: bool = False
    ZOHO_HTTP_LOG_BODY_MAX: int = 2000
    ZOHO_CONNECT_TIMEOUT_SECONDS: float = 5.0  # fail fast when Zoho is unreachable
    # Zoho guard rails (see app/modules/zoho/core/)
    # Both are enforced org-wide by the governor (app/modules/zoho/core/governor.py);
    # exceeding Zoho's 100/min returns code 44 and BLOCKS the organization, so the
    # defaults keep headroom. Bounds are validated in GovernorConfig.
    ZOHO_RATE_LIMIT_PER_MINUTE: int = 80      # Zoho Books/Inventory allow 100/min/org
    ZOHO_RATE_BURST: int = 10                 # token-bucket capacity (short bursts)
    ZOHO_MAX_CONCURRENT_REQUESTS: int = 6     # Zoho allows ~10 concurrent (soft)
    ZOHO_TOKEN_REFRESH_MARGIN: int = 120      # refresh this many secs early
    # Circuit breaker — time-based sliding window (ZSET); see
    # app/modules/zoho/core/circuit_breaker.py
    ZOHO_CB_WINDOW_SECONDS: int = 60          # look-back window for rates
    ZOHO_CB_MIN_CALLS: int = 10               # min calls in window before evaluating
    ZOHO_CB_FAILURE_RATE: float = 0.5         # trip when >=50% of calls fail
    ZOHO_CB_SLOW_RATE: float = 0.5            # trip when >=50% of calls are slow
    ZOHO_CB_SLOW_SECONDS: float = 8.0         # a call slower than this is "slow"
    ZOHO_CB_RECOVERY_SECONDS: int = 30        # first open-circuit cool-down
    ZOHO_CB_RECOVERY_MAX_SECONDS: int = 300   # cap after repeated trips (doubling)
    ZOHO_CB_FAILURE_THRESHOLD: int = 5        # DEPRECATED (count-based breaker); kept for env compat

    # --- Zoho core — OAuth + Inventory endpoints (not yet wired into client.py/token_manager.py) ---
    ZOHO_REGION: str = "in"
    ZOHO_BOOKS_API_URL: str = "https://www.zohoapis.in/books/v3"
    ZOHO_INVENTORY_API_URL: str = "https://www.zohoapis.in/inventory/v1"
    ZOHO_API_VERSION_BOOKS: str = "v3"
    ZOHO_API_VERSION_INVENTORY: str = "v1"
    ZOHO_OAUTH_URL: str = "https://accounts.zoho.in/oauth/v2/auth"
    ZOHO_ACCESS_TOKEN_URL: str = "https://accounts.zoho.in/oauth/v2/token"
    # Zoho's OAuth redirect_uri — OUR callback endpoint (/api/zoho/auth/callback).
    # Must match the redirect URI registered in the Zoho API console exactly.
    ZOHO_REDIRECT_URL: str = ""
    # Where the BROWSER lands after a successful connect (a frontend page).
    # Not the callback above — redirecting there loops (ERRORS E31). Empty =
    # the callback answers with JSON. ``?return_url=`` on /initiate overrides it.
    ZOHO_AUTH_RETURN_URL: str = ""
    # Extra hosts a ``?return_url=`` may point at (comma-separated). The hosts of
    # FRONTEND_URL, ZOHO_AUTH_RETURN_URL and ZOHO_REDIRECT_URL are always allowed;
    # anything else is refused (open-redirect protection).
    ZOHO_AUTH_RETURN_HOSTS: str = ""
    ZOHO_SCOPE: str = "ZohoBooks.fullaccess.all,ZohoInventory.FullAccess.all"
    ZOHO_ACCESS_TYPE: str = "offline"
    ZOHO_PROMPT: str = "Consent"
    ZOHO_RATE_DECAY: int = 60
    ZOHO_WEBHOOK_KEY_INCOMING: str = ""
    # Persist the refresh token in zoho_oauth_credentials (encrypted with
    # pgcrypto). Requires ZOHO_TOKEN_ENCRYPTION_KEY — without it the manager
    # refuses to write and falls back to ZOHO_REFRESH_TOKEN (never plaintext
    # in the database). See docs/zoho-sync-implementation/auth.md.
    ZOHO_TOKEN_PERSISTENCE_ENABLED: bool = False
    ZOHO_TOKEN_ENCRYPTION_KEY: str = ""
    ZOHO_AUTH_REQUIRE_USER: bool = True
    # /callback is hit by a browser redirect from Zoho, which cannot attach an
    # Authorization header. It must therefore be JWT-free by default; provenance
    # is verified via the one-time CSRF `state` stored in Redis instead. Flip
    # this on only if /callback is reached from a client that can send a token.
    ZOHO_CALLBACK_REQUIRE_USER: bool = False

    # --- Zoho governor (daily quota + rate + concurrency; ONE gate) ---
    # docs/zoho-sync-implementation/governor.md. The daily ceiling is the
    # binding constraint (Zoho plans cap calls per DAY, not per minute); when it
    # is reached the engine suspends and resumes at the next quota day.
    ZOHO_GOVERNOR_ENABLED: bool = True
    # The contracted limit. No runtime override may raise the ceiling above it.
    ZOHO_CONTRACT_DAILY_LIMIT: int = 45_000
    ZOHO_DAILY_HARD_LIMIT: int = 45_000       # engine ceiling (≤ contract limit)
    ZOHO_QUOTA_SOFT_PCT: float = 0.80         # → CONSERVE: reconcile/reports stop
    ZOHO_QUOTA_ESSENTIAL_PCT: float = 0.93    # → ESSENTIAL: change feeds stop
    ZOHO_QUOTA_HARD_PCT: float = 0.978        # → RESERVED_ONLY: interactive/critical only
    ZOHO_QUOTA_RESERVE_CALLS: int = 1_000     # reserve above the hard threshold
    # Zoho's own reset schedule is unverified; correct these once observed.
    ZOHO_QUOTA_DAY_TIMEZONE: str = "Asia/Kolkata"
    ZOHO_QUOTA_DAY_START: str = "00:00"
    ZOHO_QUOTA_SAFETY_LAG_MINUTES: int = 30   # delay resume past the boundary
    # Background pacing so a morning backfill cannot starve the evening.
    ZOHO_PACING_CURVE: str = "business"       # none | linear | business
    ZOHO_BUSINESS_HOURS: str = "07:00-21:00"
    ZOHO_PACING_BUSINESS_SHARE: float = 0.7
    ZOHO_PACING_CARRY_PCT: float = 0.05
    ZOHO_GOVERNOR_LEASE_TTL_SECONDS: float = 40.0   # > read timeout; crashed holders expire
    ZOHO_GOVERNOR_EXPECTED_PROCESSES: int = 8       # degraded (Redis-down) fallback divisor

    # --- Zoho Sync Engine (fleet-wide defaults; modules override per-module —
    #     see app/modules/zoho/sync/config.py) ---
    ZOHO_SYNC_BATCH_SIZE: int = 200           # Zoho page cap
    ZOHO_SYNC_FULL_THRESHOLD: int = 25000     # incremental escalation hint
    ZOHO_SYNC_INTERVAL_MINUTES: int = 15      # default per-module cadence
    ZOHO_SYNC_WAIT_BETWEEN_CALLS: float = 0.0 # pacing for inline N+1 detail calls
    ZOHO_SYNC_RETRY_LIMIT: int = 5
    # Deleting local rows because they were absent from one list scan is unsafe:
    # Zoho's default item list omits INACTIVE items, a partial scan looks like a
    # mass deletion, and v1 built a NOT IN with every id (asyncpg's 32,767
    # bind-parameter limit). Off by default; when on, a mass-delete guard applies.
    # docs/zoho-sync-implementation/control-plane.md §6
    ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING: bool = False
    ZOHO_SYNC_MASS_DELETE_MIN: int = 50         # absolute floor for the guard
    ZOHO_SYNC_MASS_DELETE_PCT: float = 0.02     # …or this share of live rows
    # "When to stop": every run is a bounded slice that resumes from its cursor.
    # MAX_RUN_SECONDS must stay well below Celery's task_soft_time_limit (540 s)
    # or a long scan is killed mid-page. 0 = no limit for pages/records.
    ZOHO_SYNC_MAX_RUN_SECONDS: int = 240
    ZOHO_SYNC_MAX_PAGES_PER_RUN: int = 0
    ZOHO_SYNC_MAX_RECORDS_PER_RUN: int = 0
    # Apply gate: payload keys ignored when hashing for the no-op check
    # (glob patterns, any depth). Modules can add their own.
    ZOHO_SYNC_HASH_VOLATILE_KEYS: str = "*_formatted,page_context,instrumentation"

    # --- Zoho control plane (planner, leases, events, retention, operator API) ---
    # docs/zoho-sync-implementation/control-plane.md
    ZOHO_PLANNER_ENABLED: bool = True
    ZOHO_PLANNER_MAX_CONCURRENT_RUNS: int = 2   # running pull runs across all modules
    ZOHO_RUN_LEASE_SECONDS: int = 720           # > Celery task_time_limit (600 s)
    ZOHO_WEEKLY_FULL_WEEKDAY: int = 6           # 0=Mon … 6=Sun (org timezone)
    ZOHO_WEEKLY_FULL_HOUR: int = 3
    ZOHO_SYNC_EVENTS_ENABLED: bool = True
    ZOHO_SYNC_EVENTS_SAMPLE_UNCHANGED: float = 0.0   # share of no-op applies to log
    ZOHO_SYNC_EVENTS_PARTITION_DAYS_AHEAD: int = 7
    ZOHO_SWITCH_CACHE_SECONDS: float = 5.0
    ZOHO_CONFIG_CACHE_SECONDS: float = 10.0     # runtime module-config overrides
    # A yielded slice (budget hit) is resumed on the next tick; one refused by
    # the governor or a switch waits this long before the planner retries it.
    ZOHO_CONTINUATION_BACKOFF_SECONDS: int = 300
    # Write-pressure gate: background lanes yield while CDC or the broker lag.
    # 0 disables a check.
    ZOHO_WRITE_PRESSURE_MAX_SLOT_LAG_MB: int = 512
    ZOHO_WRITE_PRESSURE_MAX_QUEUE_DEPTH: int = 5000
    # Interim operator authorisation until RBAC exists: comma-separated emails
    # allowed to use /api/zoho/admin. Empty = nobody in production, any
    # authenticated user when DEBUG=true.
    ZOHO_OPERATOR_EMAILS: str = ""

    # --- Email (Resend) — the reusable transactional-email layer ---
    # Provider adapters live in app/modules/emails/provider.py (registry key =
    # EMAIL_PROVIDER); templates in app/modules/emails/templates.py + templates/.
    EMAIL_PROVIDER: str = "resend"             # adapter registry key
    EMAIL_ENABLED: bool = True                 # master outbound switch (off => "suppressed" rows)
    EMAIL_LOG_ONLY: bool = False               # dev: persist + mark sent WITHOUT calling the provider
    RESEND_API_KEY: str = ""
    RESEND_API_URL: str = "https://api.resend.com/emails"
    RESEND_DEFAULT_FROM: str = "Core Platform <noreply@example.com>"
    RESEND_DEFAULT_REPLY_TO: str = ""
    RESEND_WEBHOOK_SECRET: str = ""           # svix signing secret (empty = skip verification, dev only)
    EMAIL_MAX_ATTEMPTS: int = 3
    EMAIL_RETRY_BASE_SECONDS: int = 60        # exponential backoff base (1m, 2m, 4m …)
    EMAIL_RETRY_MAX_BACKOFF_SECONDS: int = 900
    EMAIL_TIMEOUT_SECONDS: float = 30.0       # per-request provider HTTP timeout
    EMAIL_TEMPLATE_DIR: str = "app/modules/emails/templates"
    EMAIL_DEFAULT_LOCALE: str = "en"
    EMAIL_COMPANY_NAME: str = "Tarrina Health"
    EMAIL_SUPPORT_EMAIL: str = "tech@tarrinahealth.com"
    EMAIL_SITE_URL: str = "https://tarrinahealth.com"
    EMAIL_COMPANY_ADDRESS: str = (
        "iHub, Gujarat Knowledge Consortium, Navrangpura — 380009, Ahmedabad, Gujarat, India"
    )
    # Base URL the SPA is served from — used to build action links in emails.
    FRONTEND_URL: str = "http://localhost:5173"

    # --- GeoIP (MaxMind GeoLite2) — request audit info for auth emails/logs ---
    # Disabled by default: no DB is bundled (MaxMind licensing). Mount the .mmdb
    # read-only and point GEOIP_CITY_DB_PATH / GEOIP_COUNTRY_DB_PATH at it.
    GEOIP_ENABLED: bool = False
    GEOIP_CITY_DB_PATH: str = ""       # e.g. /app/geoip/GeoLite2-City.mmdb
    GEOIP_COUNTRY_DB_PATH: str = ""    # e.g. /app/geoip/GeoLite2-Country.mmdb

    # --- Password policy (app/modules/users/password_policy.py) ---
    # One validator, reused by register / admin-create / change-password /
    # reset-password; flipping a flag here changes all four together.
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_MAX_LENGTH: int = 128
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = False
    # Explicit accepted special-char set; empty means "any non-alphanumeric".
    # If set via .env, single-quote it (shell sources that file).
    PASSWORD_SPECIAL_CHARS: str = ""
    PASSWORD_MIN_UNIQUE_CHARS: int = 4
    PASSWORD_DISALLOW_COMMON: bool = True
    PASSWORD_DISALLOW_USER_INFO: bool = True
    PASSWORD_BCRYPT_ROUNDS: int = 12

    # --- Password reset (4-digit code by default; see users/password_reset.py) ---
    PASSWORD_RESET_CODE_LENGTH: int = 4
    PASSWORD_RESET_CODE_TTL_MINUTES: int = 10   # short — a 4-digit code is low entropy
    PASSWORD_RESET_LINK_TTL_MINUTES: int = 60
    PASSWORD_RESET_MAX_ATTEMPTS: int = 3
    PASSWORD_RESET_RESEND_COOLDOWN_SECONDS: int = 60
    PASSWORD_RESET_MAX_PER_HOUR: int = 5
    # Keyed hash for one-time codes at rest; falls back to JWT_SECRET_KEY.
    PASSWORD_RESET_HMAC_KEY: str = ""

    # --- Login OTP (passwordless email OTP; users/login_otp.py) ---
    LOGIN_OTP_CODE_LENGTH: int = 6
    LOGIN_OTP_TTL_MINUTES: int = 15
    LOGIN_OTP_MAX_ATTEMPTS: int = 5
    LOGIN_OTP_RESEND_COOLDOWN_SECONDS: int = 60
    LOGIN_OTP_MAX_PER_HOUR: int = 5

    # --- MeiliSearch (queries from the API; indexing via the CDC indexer) ---
    MEILISEARCH_URL: str = "http://meilisearch:7700"
    MEILISEARCH_MASTER_KEY: str = ""
    # Debezium CDC topics consumed by the search indexer (comma-separated).
    SEARCH_CDC_TOPICS: str = ""               # e.g. "zoho-mirror.org_management.organizations"
    SEARCH_CDC_GROUP_ID: str = "meilisearch-indexer"
    SEARCH_INDEX_BATCH_SIZE: int = 500

    # --- Media library (storage strategy; see app/modules/media/storage.py) ---
    MEDIA_STORAGE_DRIVER: str = "local"       # local | s3
    MEDIA_LOCAL_BASE_PATH: str = "/app/media/library"
    MEDIA_PUBLIC_BASE_URL: str = "/media/library"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = ""
    MEDIA_S3_BUCKET: str = ""

    # --- Document rendering (Typst, in-process via typst-py — no service) ---
    # Slim images ship almost no fonts: bundle brand fonts and point
    # TYPST_FONT_PATHS at them (e.g. ["app/assets/fonts"]). Empty = system fonts.
    TYPST_FONT_PATHS: Annotated[list[str], NoDecode] = []
    # Named PDF targets understood by typst-py, e.g. ["a-2b"] for archival
    # invoicing. Empty = default PDF output.
    TYPST_PDF_STANDARDS: Annotated[list[str], NoDecode] = []
    MEDIA_DIR: str = "/app/media"

    # --- Observability ---
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://alloy:4318"  # Alloy OTLP/HTTP receiver
    OTEL_SERVICE_NAME: str = "core-platform-backend"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
