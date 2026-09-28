"""Route-table smoke tests (no external services required)."""

from fastapi.testclient import TestClient

from app.main import app


def _openapi_paths() -> set[str]:
    return set(app.openapi()["paths"])


def test_probe_routes_registered():
    # Probes are include_in_schema=False — hit them directly (no context
    # manager: lifespan/redis is not needed for /health).
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    api_response = client.get("/api/health")
    assert api_response.status_code == 200
    assert api_response.json()["status"] == "ok"


def test_module_routers_registered():
    paths = _openapi_paths()
    expected = {
        "/api/auth/login",
        "/api/auth/login-otp/request",
        "/api/auth/login-otp/verify",
        "/api/auth/logout",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/password-policy",
        "/api/users",
        "/api/users/{user_id}/ban",
        "/api/users/{user_id}/unban",
        "/api/users/{user_id}/throttle",
        "/api/users/{user_id}/unthrottle",
        "/api/users/{user_id}/moderation",
        # /api/zoho/items was removed on 2026-09-18 — no request path may call
        # Zoho synchronously (docs/zoho-sync-implementation/README.md, Phase 1).
        "/api/zoho/sync/{entity}",
        "/api/organizations",
        "/api/organizations/tree",
        "/api/tenants",
        "/api/tenants/current",
        "/api/roles",
        "/api/zoho/auth/connection",
        "/api/zoho/sync-engine/modules",
        "/api/zoho/auth/revoke",
        "/api/zoho/auth/status",
        "/api/documents/render",
        "/api/documents/attach",
        "/api/files",
        "/api/favorites/toggle",
        "/api/tags",
        "/api/tags/sync",
        "/api/emails/send",
        "/api/emails/send-template",
        "/api/emails/stats",
        "/api/me/avatar",
        "/public/m/{media_id}/{variant}",
        "/api/activity",
        "/api/search/indexes",
        "/api/search/{index_name}",
        "/api/me/profile",
        "/api/me/settings",
        "/api/auth/me/settings",
        "/api/countries",
        "/api/countries/{iso2}/timezones",
        "/api/brands",
        "/api/brands/{ref}",
        "/api/brands/{ref}/manufacturers",
        "/api/taxonomies",
        "/api/taxonomies/{ref}",
        "/api/taxonomies/{ref}/entity-types",
        "/api/categories",
        "/api/categories/{ref}",
        "/api/categories/{ref}/move",
        "/api/categorizables",
        "/api/categorizables/sync",
        "/api/categorizables/{ref}",
        "/api/manufacturers",
        "/api/manufacturers/{ref}",
        "/api/manufacturers/{ref}/identifiers",
        "/api/entities/types",
        "/api/entities/aliases",
        "/api/custom-fields/data-types",
        "/api/custom-fields/definitions",
        "/api/custom-fields/definitions/{ref}",
        "/api/custom-fields/values",
        "/api/custom-fields/values/sync",
        "/api/custom-fields/values/erase-pii",
        "/api/custom-fields/values/{ref}",
        # Field operations — the field app (/me) and the managers' side (/fieldops).
        "/api/me/devices",
        "/api/me/device-events",
        "/api/me/fieldops/policy",
        "/api/me/fieldops/current",
        "/api/me/shifts",
        "/api/me/shifts/{shift_uuid}/pause",
        "/api/me/shifts/{shift_uuid}/resume",
        "/api/me/shifts/{shift_uuid}/end",
        "/api/me/visits",
        "/api/me/visits/{visit_uuid}/end",
        "/api/me/visits/{visit_uuid}/cancel",
        "/api/me/visits/{visit_uuid}/join",
        "/api/me/visits/{visit_uuid}/tasks",
        "/api/me/visit-tasks/{task_uuid}/void",
        "/api/me/location-pings",
        "/api/me/location",
        "/api/auth/me/location",
        "/api/fieldops/shifts",
        "/api/fieldops/shifts/{ref}",
        "/api/fieldops/shifts/{ref}/track",
        "/api/fieldops/shifts/{ref}/metrics",
        "/api/fieldops/shifts/{ref}/metrics/recompute",
        "/api/fieldops/shifts/{ref}/review",
        "/api/fieldops/visits",
        "/api/fieldops/visits/{ref}",
        "/api/fieldops/visits/{ref}/review",
        "/api/fieldops/visits/{ref}/cancel",
        "/api/fieldops/live",
        "/api/fieldops/anomalies",
        "/api/fieldops/anomalies/{ref}/resolve",
        "/api/fieldops/review-queue",
        "/api/fieldops/policies",
        "/api/fieldops/policies/{ref}",
    }
    missing = expected - paths
    assert not missing, f"routes missing from the app: {sorted(missing)}"
