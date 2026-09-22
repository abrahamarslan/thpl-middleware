"""Zoho engine CLI — see the engine work, from inside the backend container.

    docker compose exec backend python -m app.modules.zoho.cli check [--live]
    docker compose exec backend python -m app.modules.zoho.cli sync  [module ...] [--mode full|incremental|index]
    docker compose exec backend python -m app.modules.zoho.cli status
    docker compose exec backend python -m app.modules.zoho.cli runs  [--limit 20] [--module m]

``sync`` runs **leased** runs in-process (lane ``manual``, trigger ``cli``) —
the same code path Celery executes: switches, governor, breaker, token
manager, apply gate, sync events, per-page commits. Without module names it
syncs every registered module. It never bypasses a gate: a paused engine or
an exhausted quota shows up as ``yielded`` / ``suspended`` with the reason.

Docs: docs/zoho-sync-implementation/cli.md
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.database.db import async_session_factory


# ── output ──────────────────────────────────────────────────────────────────

def _table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    cells = [[_fmt(row.get(c)) for c in columns] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    line = "  ".join(c.ljust(w) for c, w in zip(columns, widths, strict=True))
    rule = "  ".join("─" * w for w in widths)
    body = ["  ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)) for r in cells]
    return "\n".join([line, rule, *body])


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _modules(names: list[str] | None):
    from app.modules.zoho.sync.registry import sync_registry

    if not names:
        return sync_registry.all()
    return [sync_registry.get(name) for name in names]


def _why(run) -> str | None:
    """Why a run stopped: the stop reason, or the error (category + first words)."""
    if run.stop_reason:
        return run.stop_reason
    if run.error_message:
        return f"{run.error_category}: {run.error_message[:90]}"
    return run.error_category


# ── commands ────────────────────────────────────────────────────────────────

async def cmd_check(live: bool) -> int:
    from app.modules.zoho.control.switches import zoho_switches
    from app.modules.zoho.core.auth import zoho_token_manager
    from app.modules.zoho.core.governor import zoho_governor
    from app.core.conf import settings
    from app.modules.zoho.sync.registry import sync_registry

    print("Registered modules :", ", ".join(sync_registry.names()), "(specs valid)")
    print("Organization id    :", settings.ZOHO_ORGANIZATION_ID or "(not set)")
    token = await zoho_token_manager.health()
    print("Token              :", token)
    gov = await zoho_governor.snapshot()
    print(f"Governor           : {gov['state']} · used {gov['used']}/{gov['daily_hard_limit']} "
          f"· remaining {gov['remaining']} · day {gov['day']} (resets {gov['resets_at']})")
    print("Switches           :", (await zoho_switches.snapshot()).as_dict())
    from app.modules.zoho.core.connection import connection_report

    report = await connection_report(probe="always" if live else "never")
    print(f"\nConnection         : {report['state'].upper()} — {report['summary']}")
    for check in report["checks"]:
        print(f"  [{check['status']:>4}] {check['name']:<17} {check['detail']}")
    if not live:
        print("\n(add --live to make ONE Zoho call — GET /organizations — and prove connectivity)")
        return 0 if report["can_sync"] else 1

    from app.modules.zoho.core.governor import Priority
    from app.modules.zoho.core.transport import ZohoClient

    client = ZohoClient(default_priority=Priority.INTERACTIVE, default_module="cli")
    try:
        response = await client.get("/organizations")
    except Exception as exc:  # noqa: BLE001 — report, don't trace
        print(f"Live call          : FAILED — {type(exc).__name__}: {exc}")
        return 1
    finally:
        await client.aclose()
    orgs = [o for o in (response.data if isinstance(response.data, list) else [response.data]) if isinstance(o, dict)]
    print(f"Live call          : OK — {len(orgs)} organization(s) visible to the connected Zoho user:")
    for org in orgs:
        print(f"                       {org.get('organization_id')}  {org.get('name')}")
    configured = settings.ZOHO_ORGANIZATION_ID
    if configured in {str(o.get("organization_id")) for o in orgs}:
        print(f"Organization id    : OK — ZOHO_ORGANIZATION_ID={configured} is one of them")
        return 0
    print(f"Organization id    : WRONG — ZOHO_ORGANIZATION_ID={configured} is not an organization of this user.\n"
          "                     Every other call fails with Zoho code 6041. Put one of the ids above in\n"
          "                     deployment/.env and recreate backend + celery-worker + celery-beat.")
    return 1


async def cmd_sync(names: list[str] | None, mode: str | None) -> int:
    from app.modules.zoho.control.planner import LANE_MANUAL, LANE_PRIORITY
    from app.modules.zoho.core.transport import ZohoClient
    from app.tasks.zoho_sync import execute_leased_run

    rows, failed = [], 0
    for defn in _modules(names):
        client = ZohoClient(default_priority=LANE_PRIORITY[LANE_MANUAL], default_module=defn.name)
        started = datetime.now(UTC)
        try:
            async with async_session_factory() as db:
                result = await execute_leased_run(
                    db, client, module_name=defn.name, lane=LANE_MANUAL, mode=mode, trigger="cli",
                )
        except Exception as exc:  # noqa: BLE001 — one module failing must not hide the others
            failed += 1
            result = {"status": "failed", "stop_reason": f"{type(exc).__name__}: {str(exc)[:80]}"}
        finally:
            await client.aclose()
        rows.append({"module": defn.name, **result,
                     "seconds": round((datetime.now(UTC) - started).total_seconds(), 1)})
        print(f"  {defn.name:<14} {result.get('status')}", flush=True)

    print()
    print(_table(rows, ["module", "status", "mode", "pages", "listed", "created", "updated", "unchanged",
                        "stale_ignored", "errors", "details_saved", "seconds", "stop_reason"]))
    return 1 if failed else 0


async def cmd_status() -> int:
    from app.modules.zoho.control.models import ZohoSyncRun

    rows = []
    async with async_session_factory() as db:
        for defn in _modules(None):
            model = defn.model
            live = await db.scalar(select(func.count()).select_from(model))
            last = await db.scalar(
                select(ZohoSyncRun).where(ZohoSyncRun.module == defn.name)
                .order_by(ZohoSyncRun.started_at.desc()).limit(1)
            )
            # Mirror tables carry `synced_at` (ZohoEntityMixin); the canonical
            # masters (currencies, tax_components, tax_exemptions) do not —
            # their freshness lives in the crosswalk (sync.sync_records), not on
            # the row. Report the run's own timestamps for those.
            synced_at = getattr(model, "synced_at", None)
            newest = await db.scalar(select(func.max(synced_at))) if synced_at is not None else None
            rows.append({
                "module": defn.name, "table": model.__tablename__, "rows": live,
                "last_synced_row": newest,
                "last_run": last.status if last else None,
                "lane": last.lane if last else None,
                "finished": last.finished_at if last else None,
                "created": last.created if last else None, "updated": last.updated if last else None,
                "unchanged": last.unchanged if last else None, "errors": last.errors if last else None,
                "every_min": defn.config.sync_interval_minutes,
                "why": _why(last) if last else None,
            })
    print(_table(rows, ["module", "table", "rows", "last_synced_row", "last_run", "lane", "finished",
                        "created", "updated", "unchanged", "errors", "every_min", "why"]))
    return 0


async def cmd_runs(limit: int, module: str | None) -> int:
    from app.modules.zoho.control.models import ZohoSyncRun

    async with async_session_factory() as db:
        stmt = select(ZohoSyncRun).order_by(ZohoSyncRun.started_at.desc()).limit(limit)
        if module:
            stmt = stmt.where(ZohoSyncRun.module == module)
        runs = (await db.scalars(stmt)).all()
    rows = [{
        "started": r.started_at, "module": r.module, "lane": r.lane, "trigger": r.trigger, "status": r.status,
        "pages": r.pages, "created": r.created, "updated": r.updated, "unchanged": r.unchanged,
        "errors": r.errors, "ms": r.duration_ms, "reason": _why(r),
    } for r in runs]
    print(_table(rows, ["started", "module", "lane", "trigger", "status", "pages", "created", "updated",
                        "unchanged", "errors", "ms", "reason"]))
    return 0


# ── entry point ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.zoho.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="token, governor, switches (and optionally one live call)")
    check.add_argument("--live", action="store_true")
    sync = sub.add_parser("sync", help="run leased syncs now, in this process")
    sync.add_argument("modules", nargs="*")
    sync.add_argument("--mode", choices=["full", "incremental", "index"])
    sub.add_parser("status", help="mirror rows and the last run per module")
    runs = sub.add_parser("runs", help="recent runs")
    runs.add_argument("--limit", type=int, default=20)
    runs.add_argument("--module")
    args = parser.parse_args(argv)

    async def _run() -> int:
        try:
            if args.command == "check":
                return await cmd_check(args.live)
            if args.command == "sync":
                return await cmd_sync(args.modules or None, args.mode)
            if args.command == "status":
                return await cmd_status()
            return await cmd_runs(args.limit, args.module)
        finally:
            from app.database.db import engine
            from app.database.redis import redis_client

            await redis_client.aclose()
            await engine.dispose()

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
