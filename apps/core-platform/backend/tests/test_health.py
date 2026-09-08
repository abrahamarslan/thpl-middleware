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
        "/api/users",
        "/api/zoho/items",
        "/api/zoho/organizations",
        "/api/zoho/sync-engine/modules",
        "/api/documents/render",
        "/api/documents/attach",
        "/api/files",
        "/api/favorites/toggle",
        "/api/tags",
        "/api/tags/sync",
        "/api/emails/send",
        "/api/media/upload",
        "/api/activity",
        "/api/search/indexes",
        "/api/search/{index_name}",
    }
    missing = expected - paths
    assert not missing, f"routes missing from the app: {sorted(missing)}"
