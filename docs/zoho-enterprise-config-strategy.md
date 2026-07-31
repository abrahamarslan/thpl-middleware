# Enterprise Modular Zoho Configuration Strategy (Revised)

After a deep review of the project architecture, specifically the doctrines in `docs/architecture-prompts/master-prompt.md` and the existing implementations in `app/modules/zoho/sync/config.py` and `docs/hierarchical-settings-implementation.md`, the initial strategy of creating a separate `BaseSettings` class has been **rejected**.

## 1. Why the Initial Strategy was Wrong (What We Were Re-Doing)

The previous strategy proposed creating a new `pydantic_settings.BaseSettings` class that parses the `.env` file directly (e.g., `model_config = SettingsConfigDict(env_file=".env")`). 

**This is a direct violation of Prime Directive 2 in the Master Prompt ("a parallel config system is a bug").**
- `app/core/conf.py` is deliberately designed as the single, global registry for all 12-factor environment variables. 
- Creating a second `.env` parser fragments the configuration lifecycle, creates a competing pattern, and leads to race conditions when testing or mocking environment variables.

## 2. The Correct "Enterprise Grade" Strategy

We must follow the precedent already established in `app/modules/zoho/sync/config.py`: **The Facade / Explicit Mapping Pattern.**

Instead of parsing `.env` again, the Zoho module should define a strongly-typed Pydantic `BaseModel` that is populated by explicitly mapping values from the global `settings` object at module initialization.

### A. The Configuration Model (`app/modules/zoho/core/config.py`)

We will create a pure Pydantic `BaseModel` (not `BaseSettings`). This model will contain the logic for dynamic URLs (mimicking Laravel's `sprintf`) and will be instantiated once.

```python
from typing import Optional
from pydantic import BaseModel, model_validator
from app.core.conf import settings

class ZohoCoreConfig(BaseModel):
    """
    Enterprise Facade for Zoho Core Configuration.
    Decouples the Zoho module from global settings while respecting the single-env-parser doctrine.
    """
    # --- Regional Settings ---
    region: str
    organization_id: str

    # --- OAuth2 Authentication ---
    client_id: str
    client_secret: str
    redirect_url: str
    access_type: str = "offline"
    prompt: str = "Consent"
    auth_require_user: bool = True

    # --- Computed OAuth & API Endpoints ---
    oauth_url: Optional[str] = None
    access_token_url: Optional[str] = None
    books_api_url: Optional[str] = None
    inventory_api_url: Optional[str] = None
    
    api_version_books: str = "v3"
    api_version_inventory: str = "v1"

    # --- Rate Limiting & Circuit Breaker ---
    timeout_seconds: float
    rate_limit_per_minute: int
    max_concurrent_requests: int
    token_refresh_margin: int

    cb_window_seconds: int
    cb_min_calls: int
    cb_failure_rate: float
    cb_slow_rate: float
    cb_slow_seconds: float
    cb_recovery_seconds: int

    @model_validator(mode="after")
    def populate_dynamic_urls(self) -> "ZohoCoreConfig":
        """
        Mimics Laravel's sprintf logic: computes URLs based on region,
        but respects explicit `.env` overrides if provided in the global settings.
        """
        if not self.oauth_url:
            self.oauth_url = f"https://accounts.zoho.{self.region}/oauth/v2/auth"
        
        if not self.access_token_url:
            self.access_token_url = f"https://accounts.zoho.{self.region}/oauth/v2/token"
            
        if not self.books_api_url:
            self.books_api_url = f"https://www.zohoapis.{self.region}/books/{self.api_version_books}"
            
        if not self.inventory_api_url:
            self.inventory_api_url = f"https://www.zohoapis.{self.region}/inventory/{self.api_version_inventory}"

        return self


def _load_zoho_config() -> ZohoCoreConfig:
    """
    Layer 2 mapping: Maps global environment settings into the strongly-typed Zoho module config.
    This exactly copies the pattern established in app/modules/zoho/sync/config.py.
    """
    return ZohoCoreConfig(
        region=settings.ZOHO_REGION,
        organization_id=settings.ZOHO_ORGANIZATION_ID,
        client_id=settings.ZOHO_CLIENT_ID,
        client_secret=settings.ZOHO_CLIENT_SECRET,
        redirect_url=settings.ZOHO_REDIRECT_URL,
        access_type=settings.ZOHO_ACCESS_TYPE,
        prompt=settings.ZOHO_PROMPT,
        auth_require_user=settings.ZOHO_AUTH_REQUIRE_USER,
        
        # Explicit overrides from .env, if any
        oauth_url=settings.ZOHO_OAUTH_URL,
        access_token_url=settings.ZOHO_ACCESS_TOKEN_URL,
        books_api_url=settings.ZOHO_BOOKS_API_URL,
        inventory_api_url=settings.ZOHO_INVENTORY_API_URL,
        api_version_books=settings.ZOHO_API_VERSION_BOOKS,
        api_version_inventory=settings.ZOHO_API_VERSION_INVENTORY,
        
        # Circuit Breaker & Limits
        timeout_seconds=settings.ZOHO_TIMEOUT_SECONDS,
        rate_limit_per_minute=settings.ZOHO_RATE_LIMIT_PER_MINUTE,
        max_concurrent_requests=settings.ZOHO_MAX_CONCURRENT_REQUESTS,
        token_refresh_margin=settings.ZOHO_TOKEN_REFRESH_MARGIN,
        cb_window_seconds=settings.ZOHO_CB_WINDOW_SECONDS,
        cb_min_calls=settings.ZOHO_CB_MIN_CALLS,
        cb_failure_rate=settings.ZOHO_CB_FAILURE_RATE,
        cb_slow_rate=settings.ZOHO_CB_SLOW_RATE,
        cb_slow_seconds=settings.ZOHO_CB_SLOW_SECONDS,
        cb_recovery_seconds=settings.ZOHO_CB_RECOVERY_SECONDS,
    )

# The exported configuration object for the @zoho module
zoho_config = _load_zoho_config()
```

### B. Integration with DB-Backed Hierarchical Settings

According to `docs/hierarchical-settings-implementation.md`, runtime variables like `refresh_token` and `access_token` must **never** be treated as static environment variables. 

The Zoho configuration strategy must split responsibilities cleanly:
1. **Infrastructure/Static Config (`zoho_config` above):** Client ID, Base URLs, Circuit Breaker thresholds. These belong in `.env` and are loaded on boot.
2. **Runtime/State Config (`system_settings_service`):** Refresh tokens, manual sync toggles, and user-specific overrides. These belong in the PostgreSQL `SettingValue` table. 

`token_manager.py` already correctly fetches the `refresh_token` from the database. We must ensure no static config object attempts to cache or manage these runtime variables.

## 3. Implementation Steps

1. **Create `app/modules/zoho/core/config.py`** implementing the `ZohoCoreConfig` model and `_load_zoho_config()` factory.
2. **Refactor Dependents:** 
   Update existing files to import `zoho_config` from `app.modules.zoho.core.config` instead of accessing `settings.ZOHO_*` directly.
   - `app/modules/zoho/core/token_manager.py`
   - `app/modules/zoho/auth/service.py`
   - `app/modules/zoho/auth/api.py`
3. **Leave `app/core/conf.py` Alone:** The `ZOHO_` settings remain in `app/core/conf.py` as they are the formal declarations of what the `.env` file accepts. We do not remove them. They just stop being used directly by the application code, funneling through `zoho_config` instead.

## 4. Why This is "Enterprise Grade"

1. **Architectural Consistency:** We are reusing the exact pattern built in `app/modules/zoho/sync/config.py` rather than inventing a new one.
2. **No Competing Systems:** We respect `app/core/conf.py` as the single 12-factor `.env` registry.
3. **Type Safety & Intellisense:** Inside the `zoho` module, developers interact with a clean `zoho_config.client_id` (lowercase, properly typed) rather than a bloated global `settings.ZOHO_CLIENT_ID`.
4. **Dynamic Defaults:** We perfectly replicate the Laravel `sprintf` behavior securely and predictably using Pydantic `@model_validator`.
