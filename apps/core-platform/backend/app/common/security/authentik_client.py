"""Authentik Admin API client — OUTBOUND user provisioning (app -> Authentik).

This is the mirror-image of app/common/security/authentik.py:

  authentik.py         validates INBOUND Authentik OIDC tokens (RS256/JWKS)
  authentik_client.py  performs OUTBOUND admin operations (this module)

The local Postgres ``users`` table is the source of truth for identity; this
client replicates the credential-bearing subset (username, name, email, phone,
password, active state) INTO Authentik so Authentik can serve as the central
SSO/admin directory. The orchestration (which fields, when, error handling)
lives in app/modules/users/authentik_sync.py.

Authentication
--------------
A long-lived API token belonging to an Authentik **service account**, sent as::

    Authorization: Bearer <AUTHENTIK_SERVICE_TOKEN>

The service account needs the ``authentik Core: Can create/change/delete User``
and ``Can reset User's password`` permissions. See docs/AUTHENTIK_SYNC.md.

Endpoints (Authentik REST API, ``/api/v3/core/users/``)
-------------------------------------------------------
  POST   /core/users/                  create user        -> 201 {pk, uuid, ...}
  PATCH  /core/users/{pk}/             partial update     -> 200
  POST   /core/users/{pk}/set_password/  set password     -> 204
  DELETE /core/users/{pk}/             delete user        -> 204
  GET    /core/users/?email=<email>    lookup by email    -> {results: [...]}

Concurrency model
-----------------
``AuthentikAdminClient`` is async (httpx.AsyncClient). The API request path uses
the module-level ``authentik_admin_client`` singleton. Celery retry tasks run in
synchronous workers with an asyncpg-only stack, so they construct a *fresh*
instance under ``asyncio.run`` and close it — never the singleton (whose
AsyncClient would be bound to a dead event loop). See app/tasks/authentik.py.
"""

from typing import Any

import httpx
import structlog

from app.common.exception.errors import UpstreamError
from app.core.conf import settings

logger = structlog.get_logger("app.security.authentik_client")


class AuthentikError(UpstreamError):
    """An Authentik admin API call failed. Subclasses UpstreamError so the
    global exception handlers render it as a 502 automatically."""

    code = "authentik_error"


class AuthentikAdminClient:
    """Thin async wrapper over the Authentik core/users admin API."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.AUTHENTIK_BASE_URL).rstrip("/")
        self._token = token or settings.AUTHENTIK_SERVICE_TOKEN
        self._timeout = timeout or settings.AUTHENTIK_TIMEOUT_SECONDS
        self._http = httpx.AsyncClient(
            base_url=f"{self._base_url}/api/v3",
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    # ── Guard ──────────────────────────────────────────────────────────────────

    def _require_config(self) -> None:
        if not self._base_url:
            raise AuthentikError("AUTHENTIK_BASE_URL is not configured")
        if not self._token:
            raise AuthentikError("AUTHENTIK_SERVICE_TOKEN is not configured")

    # ── Core request ───────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, *, json: dict | None = None,
                       params: dict | None = None, expect: tuple[int, ...] = (200, 201, 204)) -> httpx.Response:
        self._require_config()
        try:
            resp = await self._http.request(method, path, json=json, params=params)
        except httpx.TransportError as e:
            raise AuthentikError(f"Authentik transport error: {e}") from e

        if resp.status_code not in expect:
            body = resp.text[:500]
            logger.warning(
                "authentik_admin_error",
                method=method, path=path, status=resp.status_code, body=body,
            )
            raise AuthentikError(
                f"Authentik API {method} {path} returned {resp.status_code}",
                data={"status": resp.status_code, "body": body},
            )
        logger.info("authentik_admin_call", method=method, path=path, status=resp.status_code)
        return resp

    # ── User operations ────────────────────────────────────────────────────────

    async def create_user(
        self,
        *,
        username: str,
        name: str,
        email: str,
        is_active: bool = True,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a user. Returns the Authentik user dict (incl. ``pk``, ``uuid``)."""
        payload = {
            "username": username,
            "name": name,
            "email": email,
            "is_active": is_active,
            "path": settings.AUTHENTIK_USER_PATH,
            "type": settings.AUTHENTIK_USER_TYPE,
            "attributes": attributes or {},
        }
        resp = await self._request("POST", "/core/users/", json=payload, expect=(201,))
        return resp.json()

    async def update_user(self, authentik_pk: str, **fields: Any) -> dict[str, Any]:
        """PATCH a subset of fields. ``attributes`` is merged by Authentik."""
        resp = await self._request("PATCH", f"/core/users/{authentik_pk}/", json=fields, expect=(200,))
        return resp.json()

    async def set_active(self, authentik_pk: str, is_active: bool) -> dict[str, Any]:
        return await self.update_user(authentik_pk, is_active=is_active)

    async def set_password(self, authentik_pk: str, password: str) -> None:
        await self._request(
            "POST", f"/core/users/{authentik_pk}/set_password/",
            json={"password": password}, expect=(204, 200),
        )

    async def delete_user(self, authentik_pk: str) -> None:
        """Delete a user. A 404 is treated as success (already gone — idempotent)."""
        await self._request("DELETE", f"/core/users/{authentik_pk}/", expect=(204, 404))

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        resp = await self._request("GET", "/core/users/", params={"email": email}, expect=(200,))
        results = resp.json().get("results") or []
        return results[0] if results else None

    async def aclose(self) -> None:
        await self._http.aclose()


# Singleton for the API request path (one event loop). Celery tasks build their
# own short-lived instances instead — see module docstring.
authentik_admin_client = AuthentikAdminClient()
