"""Static audit of the whole API surface (docs/rbac-module.md §4.7).

There is ONE way to protect a route — ``Perm(code[, target=…])`` — so this test can prove, without
running a request, that no mutating route was left open and that the routes acting on a row name the
row's organization. A new route that forgets its guard fails HERE, in CI, not in production.
"""

import re

from fastapi.routing import APIRoute

from app.main import app
from app.modules.rbac.deps import MARKER

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

#: Mutating routes that legitimately carry no ``Perm`` — each with the reason.
UNGUARDED = [
    (r"^/api/auth/(register|login|login-otp/request|login-otp/verify|refresh|forgot-password|reset-password|dev-token)$",
     "authentication entry points (nobody is signed in yet)"),
    (r"^/api/auth/(logout|change-password)$", "acts on the caller's own session and credentials"),
    (r"^/api/(auth/)?me(/.*)?$", "self-service: acts on the caller's own record"),
    (r"^/api/favorites(/.*)?$", "a user's own favourites"),
    (r"^/api/emails/webhooks/resend$", "provider webhook, verified by signature"),
    (r"^/api/zoho/auth/.*$", "the Zoho OAuth handshake carries its own state check"),
    (r"^/api/tenants(/.*)?$", "platform administrators — outside every tenant's RBAC (PlatformAdmin)"),
]

#: Mutating routes acting on ONE row of these resources must judge the action at that row's organization.
RESOURCE_PREFIXES = (
    "/api/departments/{", "/api/job-titles/{", "/api/team-types/{", "/api/team-roles/{", "/api/teams/{",
    "/api/roles/{", "/api/organizations/{", "/api/users/{user_id}", "/api/hr/employment/{",
    "/api/locations/{", "/api/addresses/{", "/api/geofences/{", "/api/brands/{", "/api/manufacturers/{",
    "/api/hubs/{", "/api/vehicles/{", "/api/fleet-partners/{", "/api/currencies/{", "/api/documents/{",
)
#: Handled by the service's own guardrails (escalation, level, last owner), not by a row target.
NO_TARGET_NEEDED = re.compile(r"^/api/users/\{user_id\}/(roles|base-role)")

#: Sensitive READS — gated too, not only writes.
GATED_READS = ("/api/users", "/api/activity", "/api/emails", "/api/hr/employment", "/api/hr/org-chart",
               "/api/zoho/admin/health", "/api/documents/{document_id}", "/api/permissions")


def _walk(routes, prefix=""):
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
        elif type(r).__name__ == "_IncludedRouter":
            yield from _walk(r.original_router.routes, prefix + (getattr(r.include_context, "prefix", "") or ""))


def _markers(dependant):
    found = []
    for dep in dependant.dependencies:
        marker = getattr(dep.call, MARKER, None)
        if marker:
            found.append(marker)
        found.extend(_markers(dep))
    return found


def _is_platform_admin_guarded(dependant) -> bool:
    return any(getattr(d.call, "__name__", "") == "require_platform_admin" or _is_platform_admin_guarded(d)
               for d in dependant.dependencies)


def _routes():
    return [(path, route) for path, route in _walk(app.routes) if path.startswith("/api/")]


def test_every_mutating_route_declares_a_permission():
    open_routes = []
    for path, route in _routes():
        if not (route.methods & MUTATING):
            continue
        if _markers(route.dependant) or _is_platform_admin_guarded(route.dependant):
            continue
        if any(re.match(pattern, path) for pattern, _ in UNGUARDED):
            continue
        open_routes.append(f"{sorted(route.methods & MUTATING)} {path}")
    assert not open_routes, "mutating routes with no Perm(...) (and not on the allow-list):\n" + "\n".join(open_routes)


def test_routes_acting_on_a_row_judge_it_at_the_rows_organization():
    missing = []
    for path, route in _routes():
        if not (route.methods & MUTATING) or "{" not in path or NO_TARGET_NEEDED.match(path):
            continue
        if not path.startswith(RESOURCE_PREFIXES):
            continue
        marks = _markers(route.dependant)
        if marks and not any(m["has_target"] for m in marks):
            missing.append(f"{sorted(route.methods & MUTATING)} {path} -> {[m['code'] for m in marks]}")
    assert not missing, "row-level routes without target=…:\n" + "\n".join(missing)


def test_sensitive_reads_are_gated():
    gated = {path for path, route in _routes() if "GET" in route.methods and _markers(route.dependant)}
    for path in GATED_READS:
        assert path in gated, f"GET {path} should require a permission"
