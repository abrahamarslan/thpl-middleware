# Things to fix when the frontend is ready

Backend fixes that are blocked on frontend decisions (routes, origins, redirect
targets). Each item states the current backend behaviour, the risk, and what we
need from the frontend to finish it.

---

## 1. Zoho OAuth `return_url` — open redirect + wrong default

Endpoints: `GET /api/zoho/auth/initiate`, `GET /api/zoho/auth/callback`
(`backend/app/modules/zoho/auth/`).

### Current behaviour

1. `GET /api/zoho/auth/initiate?return_url=<anything>` accepts an **arbitrary,
   unvalidated** URL and stores it in Redis with the OAuth `state`
   (`service.py::get_authorization_url`, `STATE_TTL = 600s`).
2. After Zoho calls back, `GET /api/zoho/auth/callback` redirects the browser to
   that stored value: `RedirectResponse(url=return_url)`
   (`api.py::zoho_auth_callback`).
3. If no `return_url` was supplied, the fallback is
   `settings.ZOHO_REDIRECT_URL` (`service.py::handle_callback`) — the value also
   used as the OAuth `redirect_uri`, i.e. normally the **backend callback URL**,
   not a frontend route. So the default lands the user on an API endpoint
   instead of the app.

### Risks

- **Open redirect (security).** An attacker can share
  `/api/zoho/auth/initiate?return_url=https://evil.example` — after the user
  authorizes Zoho, the browser is bounced to the attacker's site, which is a
  phishing / token-leak pivot. Any authenticated user can trigger this today
  (`ZOHO_AUTH_REQUIRE_USER` defaults to `true`, so an account is required, but
  that is not a real restriction for a public SaaS).
- **Bad default UX.** Users who don't pass `return_url` end up on the API
  redirect URI rather than back in the app.

### What we need from the frontend

- The **canonical post-connect route(s)** in the app (e.g.
  `/settings/integrations/zoho?status=connected`) that should receive the user
  after a successful or failed connection.
- Whether `return_url` should be a full URL or a **relative app path**. Relative
  paths are strongly preferred — they make the open redirect trivially
  impossible.
- The list of **allowed origins** if full URLs must be accepted (staging +
  production app origins).

### Planned backend fix (once the above is known)

- Accept only a relative path **or** validate the absolute URL's scheme + host
  against an allowlist (`FRONTEND_URL`, default `http://localhost:5173`, plus any
  explicitly configured origins). Reject everything else with `400`.
- Change the no-`return_url` default from `ZOHO_REDIRECT_URL` to the configured
  frontend integration route.
- Add a test that a foreign origin is rejected.

### Related (needs a frontend decision too)

- The callback is reached by a **browser redirect**, so it cannot carry an
  `Authorization` header (`ZOHO_CALLBACK_REQUIRE_USER` defaults to `false`).
  Identity/provenance is currently verified only by the CSRF `state`, which
  stores just `return_url` — it is **not bound to the initiating user**
  (`service.py::get_authorization_url`). The Zoho connection is global
  (single refresh token), so this is acceptable for now, but if the product
  wants per-user Zoho connections, the `state` must also persist the initiator's
  user id and the callback must verify it. Decide whether Zoho stays org-global
  or becomes per-user.