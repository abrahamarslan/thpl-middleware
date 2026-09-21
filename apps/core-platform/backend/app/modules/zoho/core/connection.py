"""Can we sync with Zoho right now? — the connection readiness report.

A bare "sample request" answers the wrong question: it spends quota on every
call, cannot say WHY syncing would not happen (paused switch, spent quota,
open breaker, revoked token), and ``GET /organizations`` succeeds even with a
wrong ``ZOHO_ORGANIZATION_ID`` (ERRORS E35). This report combines:

| Evidence | Cost | Checks |
|---|---|---|
| configuration & local state | free | client credentials, org id, redirect URL, stored refresh token, cached access token, switches, governor state, circuit breakers |
| real traffic | free | the last successful and the last failed Zoho call, recorded by the transport (``record_outcome``) |
| live probe | 1 call, INTERACTIVE | ``GET /organizations/{ZOHO_ORGANIZATION_ID}`` — org-scoped: proves token, data centre AND org membership |

The probe runs only when needed — ``probe=auto`` (default) when no call
succeeded within ``ZOHO_CONNECTION_PROBE_AFTER_SECONDS``, ``always`` on
demand, ``never`` for dashboards — and is single-flighted and cached for
``ZOHO_CONNECTION_PROBE_CACHE_SECONDS`` so a refreshing UI cannot burn quota.

Verdict: ``can_sync`` is true when no check FAILs; ``state`` is one of
``connected`` · ``degraded`` (warnings) · ``not_connected`` (no credential) ·
``misconfigured`` · ``blocked`` (a switch or the quota stops syncing).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from redis.exceptions import RedisError

from app.core.conf import settings
from app.database.redis import redis_client

logger = structlog.get_logger("app.zoho.connection")

_LAST_OK = "zoho:conn:last_ok"
_LAST_ERROR = "zoho:conn:last_error"
_PROBE = "zoho:conn:probe"
_PROBE_LOCK = "zoho:conn:probe:lock"
_RECORD_EVERY_S = 5.0
_last_write = {"ok": 0.0}

Probe = Literal["auto", "always", "never"]


# ── evidence from real traffic (called by the transport) ────────────────────

async def record_outcome(*, ok: bool, path: str, module: str | None, zoho_code: int | None = None,
                         category: str | None = None, message: str | None = None) -> None:
    """Best-effort; never raises. Successes are written at most every 5 s per process."""
    now = time.monotonic()
    if ok and now - _last_write["ok"] < _RECORD_EVERY_S:
        return
    payload = {"at": datetime.now(UTC).isoformat(), "path": path, "module": module}
    if not ok:
        payload.update(zoho_code=zoho_code, category=category, message=(message or "")[:300])
    try:
        await redis_client.set(_LAST_OK if ok else _LAST_ERROR, json.dumps(payload), ex=7 * 86400)
        if ok:
            _last_write["ok"] = now
    except (RedisError, RuntimeError, OSError):
        pass


async def _read(key: str) -> dict | None:
    try:
        raw = await redis_client.get(key)
    except (RedisError, RuntimeError, OSError):
        return None
    return json.loads(raw) if raw else None


def _age_seconds(event: dict | None) -> float | None:
    if not event:
        return None
    return (datetime.now(UTC) - datetime.fromisoformat(event["at"])).total_seconds()


# ── the report ──────────────────────────────────────────────────────────────

def _check(name: str, status: str, detail: str, **data: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, **({"data": data} if data else {})}


async def connection_report(probe: Probe = "auto") -> dict[str, Any]:
    from app.modules.zoho.control.switches import zoho_switches
    from app.modules.zoho.core.auth import CredentialUnavailable, zoho_token_manager
    from app.modules.zoho.core.breaker import zoho_breaker
    from app.modules.zoho.core.governor import GovernorState, zoho_governor

    checks: list[dict[str, Any]] = []

    # 1. configuration
    missing = [name for name, value in (
        ("ZOHO_CLIENT_ID", settings.ZOHO_CLIENT_ID), ("ZOHO_CLIENT_SECRET", settings.ZOHO_CLIENT_SECRET),
        ("ZOHO_ORGANIZATION_ID", settings.ZOHO_ORGANIZATION_ID), ("ZOHO_REDIRECT_URL", settings.ZOHO_REDIRECT_URL),
    ) if not value]
    checks.append(_check("configuration", "fail" if missing else "ok",
                         f"missing: {', '.join(missing)}" if missing else "client, organization and redirect configured",
                         organization_id=settings.ZOHO_ORGANIZATION_ID or None))

    # 2. stored credential
    credential_ok = False
    try:
        credential = await zoho_token_manager.store.load()
        credential_ok = True
        if credential.source == "database":
            checks.append(_check("credential", "ok", "refresh token stored encrypted in Postgres",
                                 version=credential.version))
        else:
            checks.append(_check("credential", "warn",
                                 "refresh token comes from ZOHO_REFRESH_TOKEN (env), not the encrypted store"))
    except CredentialUnavailable:
        checks.append(_check("credential", "fail", "not connected — open /api/zoho/auth/initiate and consent"))

    # 3. access token
    health = await zoho_token_manager.health()
    if health["has_token"]:
        checks.append(_check("access_token", "ok", f"cached, {health['token_ttl_seconds']} s left"))
    else:
        checks.append(_check("access_token", "ok" if credential_ok else "warn",
                             "none cached — the next call refreshes it" if credential_ok else "none"))

    # 4. switches
    switches = await zoho_switches.snapshot()
    if switches.auth_paused:
        checks.append(_check("switches", "fail", f"engine auth-paused: {switches.auth_paused_reason} — reconnect"))
    elif switches.engine_paused or not switches.pull_enabled:
        checks.append(_check("switches", "fail",
                             "engine paused by an operator" if switches.engine_paused else "pull disabled by an operator"))
    elif switches.paused_modules:
        checks.append(_check("switches", "warn", f"paused modules: {', '.join(sorted(switches.paused_modules))}"))
    else:
        checks.append(_check("switches", "ok", "engine running"))

    # 5. quota
    gov = await zoho_governor.snapshot()
    state = GovernorState(gov["state"])
    quota_detail = f"{gov['used']}/{gov['daily_hard_limit']} calls used today, state {gov['state']}"
    if state is GovernorState.EXHAUSTED:
        checks.append(_check("quota", "fail", f"{quota_detail} — resumes {gov['resets_at']}"))
    elif state is GovernorState.OPEN:
        checks.append(_check("quota", "ok", quota_detail))
    else:
        checks.append(_check("quota", "warn", f"{quota_detail} — background lanes are being throttled"))

    # 6. circuit breakers
    open_groups = []
    try:
        async for key in redis_client.scan_iter(match="zoho:cb:*:meta", count=200):
            group = key.split(":", 2)[2].rsplit(":", 1)[0]
            if (await zoho_breaker.snapshot(group)).get("state") == "open":
                open_groups.append(group)
    except (RedisError, RuntimeError, OSError):
        pass
    checks.append(_check("circuit_breakers", "warn" if open_groups else "ok",
                         f"open: {', '.join(sorted(open_groups))}" if open_groups else "all closed"))

    # 7. evidence from real traffic
    last_ok, last_error = await _read(_LAST_OK), await _read(_LAST_ERROR)
    ok_age, error_age = _age_seconds(last_ok), _age_seconds(last_error)
    recent_error = last_error is not None and (ok_age is None or (error_age is not None and error_age < ok_age))

    # 8. live probe (only when it adds information)
    probe_result = None
    should_probe = probe == "always" or (
        probe == "auto" and credential_ok and not missing
        and (ok_age is None or ok_age > settings.ZOHO_CONNECTION_PROBE_AFTER_SECONDS or recent_error)
    )
    if should_probe and credential_ok and not missing:
        probe_result = await _probe()
        checks.append(_check("live_probe", "ok" if probe_result["ok"] else "fail", probe_result["detail"],
                             cached=probe_result.get("cached", False), at=probe_result.get("at")))
        last_ok, last_error = await _read(_LAST_OK), await _read(_LAST_ERROR)   # the probe is evidence too
    elif last_ok and not recent_error:
        checks.append(_check("recent_traffic", "ok", f"last successful Zoho call {int(ok_age)} s ago",
                             path=last_ok.get("path")))
    elif recent_error:
        checks.append(_check("recent_traffic", "warn",
                             f"last Zoho call failed {int(error_age)} s ago: {last_error.get('message')}",
                             zoho_code=last_error.get("zoho_code"), category=last_error.get("category")))

    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    names = {c["name"] for c in failed}
    if "credential" in names:
        verdict = "not_connected"
    elif "configuration" in names or (probe_result and probe_result.get("category") == "forbidden"):
        verdict = "misconfigured"
    elif names & {"switches", "quota"}:
        verdict = "blocked"
    elif failed:
        verdict = "not_connected"
    else:
        verdict = "degraded" if warned else "connected"

    return {
        "can_sync": not failed,
        "state": verdict,
        "summary": _summary(verdict, failed, warned),
        "organization": probe_result.get("organization") if probe_result else None,
        "checks": checks,
        "last_success": last_ok,
        "last_error": last_error,
        "probed": probe_result is not None,
    }


def _summary(verdict: str, failed: list[dict], warned: list[dict]) -> str:
    if failed:
        return f"Cannot sync: {failed[0]['detail']}"
    if warned:
        return f"Can sync, with warnings: {warned[0]['detail']}"
    return "Connected — Zoho syncs can run"


async def _probe() -> dict[str, Any]:
    cached = await _read(_PROBE)
    if cached:
        return {**cached, "cached": True}
    try:
        got_lock = await redis_client.set(_PROBE_LOCK, "1", nx=True, ex=30)
    except (RedisError, RuntimeError, OSError):
        got_lock = True
    if not got_lock:                                   # another request is probing right now
        import asyncio

        for _ in range(20):
            await asyncio.sleep(0.25)
            cached = await _read(_PROBE)
            if cached:
                return {**cached, "cached": True}
        return {"ok": False, "detail": "a probe is already running; retry in a moment", "category": "busy"}

    from app.modules.zoho.core.errors import ZohoError
    from app.modules.zoho.core.governor import Priority
    from app.modules.zoho.core.transport import ZohoClient

    org_id = settings.ZOHO_ORGANIZATION_ID
    client = ZohoClient(default_priority=Priority.INTERACTIVE, default_module="connection")
    result: dict[str, Any]
    try:
        response = await client.get(f"/organizations/{org_id}")
        org = response.data if isinstance(response.data, dict) else {}
        result = {"ok": True, "detail": f"Zoho answered for organization {org_id} ({org.get('name')})",
                  "organization": {"id": org_id, "name": org.get("name"), "currency_code": org.get("currency_code")}}
    except ZohoError as exc:
        result = {"ok": False, "detail": f"{type(exc).__name__}: {exc.msg}", "category": str(exc.category),
                  "zoho_code": exc.zoho_code}
    finally:
        await client.aclose()
    result["at"] = datetime.now(UTC).isoformat()
    try:
        await redis_client.set(_PROBE, json.dumps(result), ex=settings.ZOHO_CONNECTION_PROBE_CACHE_SECONDS)
        await redis_client.delete(_PROBE_LOCK)
    except (RedisError, RuntimeError, OSError):
        pass
    logger.info("zoho.connection.probed", ok=result["ok"], detail=result["detail"])
    return result


__all__ = ["connection_report", "record_outcome"]
