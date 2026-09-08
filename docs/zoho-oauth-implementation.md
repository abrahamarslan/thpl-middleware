# Zoho OAuth 2.0 Flow Implementation Plan

## Goal Description
Build a FastAPI-native, enterprise-grade architecture that adheres strictly to the `th-middleware` FBA 5-layer pattern and core doctrines. This implementation will transition the application from using a static `.env` based refresh token to a dynamic, browser-initiated OAuth 2.0 flow.

## Architecture Decisions (Based on your feedback)

1. **Security / Route Protection**: 
   The endpoints `/initiate` and `/revoke` are protected by the internal `CurrentUser` dependency (JWT). This ensures that only authorized internal users/admins can initiate the connection to Zoho or revoke it. The `/callback` endpoint is **NOT** JWT-protected: Zoho redirects the browser straight back to it, and a browser cannot attach an `Authorization` header on a top-level navigation. Instead, `/callback` provenance is verified via the one-time CSRF `state` value stored in Redis. (Controlled by `ZOHO_AUTH_REQUIRE_USER` for initiate/revoke and `ZOHO_CALLBACK_REQUIRE_USER`, default `False`, for callback.)

2. **Persistent Storage (Configurable)**: 
   Redis will be the primary, fast cache for the access and refresh tokens. We will add a configurable option (`ZOHO_TOKEN_PERSISTENCE_ENABLED`) in `conf.py`. If enabled, the service will also save the refresh token to a persistent storage medium (the `SettingValue` table, tied to the `zoho_refresh_token` definition in the Hierarchical System Settings module) as a fallback in case Redis is flushed.

3. **State Management**: 
   Since FastAPI is stateless, we will use Redis to store the CSRF `state` and the `return_url` generated during the `/initiate` request. The key will be `zoho:oauth:state:<uuid>` with a 10-minute TTL.

4. **Automatic Flow Omitted**: 
   Standard Zoho Books APIs for user resources use Authorization Code grants or Self-Client tokens. The `client_credentials` flow (which was the `automatic` flow in PHP) doesn't apply to standard Zoho Books integrations. We will omit it to keep the scope clean and enterprise-focused.

## Proposed Changes

### 1. New Module: `app/modules/zoho/auth`

#### `app/modules/zoho/auth/schema.py`
- Pydantic models for request bodies and typed responses (e.g., `OAuthInitiateRequest`, `OAuthTokenResponse`).

#### `app/modules/zoho/auth/service.py`
- `ZohoAuthService`: Implements the core logic without HTTP coupling.
  - `get_authorization_url(return_url: str | None)`: Generates a UUID `state`, stores it and the `return_url` in Redis, and constructs the Zoho authorization URL.
  - `handle_callback(code: str, state: str)`: Validates the `state` against Redis. If valid, calls Zoho's `/oauth/v2/token` endpoint to exchange the `code` for an access and refresh token. Updates Redis (and optionally the DB), and logs the activity via the `activity` module.
  - `revoke_token()`: Reads the current token from Redis, calls Zoho's `/oauth/v2/token/revoke`, and purges local Redis caches.

#### `app/modules/zoho/auth/api.py`
- `/initiate` and `/revoke` protected by `Depends(get_current_user)` (subject to `ZOHO_AUTH_REQUIRE_USER`).
- `GET /initiate`: Calls service to get URL, returns `RedirectResponse`.
- `GET /callback`: NOT protected by JWT (browser redirect — cannot attach a token). Extracts `code` and `state`, validates `state` in Redis, calls the service. Returns a JSON `ResponseModel` or a `RedirectResponse` back to the frontend based on the `return_url`.
- `POST /revoke`: Calls service to revoke the token.

### 2. Core Modifications

#### `app/modules/zoho/core/token_manager.py`
- Update `_refresh()` to first attempt fetching the refresh token from Redis (`zoho:refresh_token`). 
- If missing from Redis, and if `ZOHO_TOKEN_PERSISTENCE_ENABLED` is true, try fetching from the DB.
- Finally, fallback to `settings.ZOHO_REFRESH_TOKEN` (for backwards compatibility/bootstrap).
- Add methods `store_tokens(access_token: str, refresh_token: str, expires_in: int)` to encapsulate cache writing logic.

#### `app/core/conf.py`
- Add `ZOHO_TOKEN_PERSISTENCE_ENABLED: bool = False`.
- Ensure variables like `ZOHO_OAUTH_URL`, `ZOHO_ACCESS_TOKEN_URL`, `ZOHO_REDIRECT_URL`, `ZOHO_SCOPE`, `ZOHO_ACCESS_TYPE`, and `ZOHO_PROMPT` are fully defined.

#### `app/router.py`
- Wire in `zoho_auth_router` to the main FastAPI router.

## Verification Plan

### Automated Tests
- Unit test `handle_callback` by mocking the HTTPX call to Zoho and ensuring Redis sets the correct keys.
- Unit test `get_authorization_url` to ensure state is generated and stored correctly.
- Test CSRF protection: simulate a callback with a missing or invalid `state` and assert it raises an `AuthError`.

### Manual Verification
- Navigate to `/api/zoho/auth/initiate` using a valid JWT, complete the consent screen, and ensure the callback returns successfully.
- Verify `zoho:refresh_token` and `zoho:access_token` are populated in Redis DB 0.
- Execute a Zoho outbox task to guarantee the `TokenManager` correctly uses the new dynamically fetched token.
