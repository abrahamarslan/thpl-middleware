"""Planner decisions — pure, no infrastructure."""

from datetime import UTC, datetime, timedelta

from app.modules.zoho.control.planner import (
    LANE_SCHEDULED,
    LANE_WEEKLY_FULL,
    ModuleView,
    plan,
)
from app.modules.zoho.control.switches import SwitchState
from app.modules.zoho.core.governor import GovernorState, Priority

# Wednesday 2026-09-16 10:00 IST
NOW = datetime(2026, 9, 16, 4, 30, tzinfo=UTC)


def mod(name="contacts", *, interval=15, strategy="incremental", enabled=True, pulls=True):
    return ModuleView(name=name, enabled=enabled, pulls=pulls, interval_minutes=interval, strategy=strategy)


def run_plan(modules, **kwargs):
    defaults = dict(
        last_started={}, running=set(), running_count=0, switches=SwitchState(),
        governor_state=GovernorState.OPEN, now=NOW, timezone="Asia/Kolkata",
        weekly_weekday=6, weekly_hour=3, max_concurrent_runs=10,
    )
    defaults.update(kwargs)
    return plan(modules, **defaults)


def lanes(result):
    return {(r.module, r.lane) for r in result.runs}


def skips(result):
    return {(s.module, s.lane): s.reason for s in result.skipped}


def test_never_run_module_is_due_on_both_lanes():
    result = run_plan([mod()])
    assert lanes(result) == {("contacts", LANE_SCHEDULED), ("contacts", LANE_WEEKLY_FULL)}


def test_scheduled_lane_respects_the_interval():
    recent = {("contacts", LANE_SCHEDULED): NOW - timedelta(minutes=5),
              ("contacts", LANE_WEEKLY_FULL): NOW}
    assert lanes(run_plan([mod()], last_started=recent)) == set()

    stale = {("contacts", LANE_SCHEDULED): NOW - timedelta(minutes=16),
             ("contacts", LANE_WEEKLY_FULL): NOW}
    assert lanes(run_plan([mod()], last_started=stale)) == {("contacts", LANE_SCHEDULED)}


def test_weekly_full_runs_once_per_slot_even_after_downtime():
    # Last full ran 3 weeks ago: exactly ONE catch-up, not three.
    history = {("contacts", LANE_SCHEDULED): NOW,
               ("contacts", LANE_WEEKLY_FULL): NOW - timedelta(days=21)}
    result = run_plan([mod()], last_started=history)
    assert [r.lane for r in result.runs] == [LANE_WEEKLY_FULL]
    assert result.runs[0].mode == "full"
    assert result.runs[0].priority is Priority.RECONCILE

    # After it ran (this week's slot was Sunday 03:00 IST), nothing more.
    history[("contacts", LANE_WEEKLY_FULL)] = NOW - timedelta(hours=1)
    assert lanes(run_plan([mod()], last_started=history)) == set()


def test_modules_already_on_full_strategy_get_no_weekly_lane():
    result = run_plan([mod("organizations", strategy="full")])
    assert lanes(result) == {("organizations", LANE_SCHEDULED)}


def test_disabled_and_outbound_only_modules_are_skipped():
    result = run_plan([mod("a", enabled=False), mod("b", pulls=False)])
    assert result.runs == []
    assert set(skips(result).values()) == {"module_disabled"}


def test_switches_stop_planning():
    assert all(r.startswith("switch:engine_paused")
               for r in skips(run_plan([mod()], switches=SwitchState(engine_paused=True))).values())
    assert all(r == "switch:auth_paused"
               for r in skips(run_plan([mod()], switches=SwitchState(auth_paused=True))).values())
    paused = run_plan([mod("contacts"), mod("items")],
                      switches=SwitchState(paused_modules=frozenset({"items"})))
    assert ("items", LANE_SCHEDULED) not in lanes(paused)
    assert ("contacts", LANE_SCHEDULED) in lanes(paused)


def test_governor_state_pauses_lanes_by_priority():
    conserve = run_plan([mod()], governor_state=GovernorState.CONSERVE)
    assert lanes(conserve) == {("contacts", LANE_SCHEDULED)}           # reconcile paused
    assert skips(conserve)[("contacts", LANE_WEEKLY_FULL)] == "governor:conserve"

    essential = run_plan([mod()], governor_state=GovernorState.ESSENTIAL)
    assert lanes(essential) == set()                                    # incremental paused too


def test_running_lane_is_not_enqueued_again():
    result = run_plan([mod()], running={("contacts", LANE_SCHEDULED)}, running_count=1)
    assert ("contacts", LANE_SCHEDULED) not in lanes(result)
    assert skips(result)[("contacts", LANE_SCHEDULED)] == "lane_running"


def test_concurrency_cap_prefers_freshness_then_most_overdue():
    modules = [mod("a"), mod("b"), mod("c")]
    history = {
        ("a", LANE_SCHEDULED): NOW - timedelta(minutes=20),
        ("b", LANE_SCHEDULED): NOW - timedelta(hours=5),      # most overdue
        ("c", LANE_SCHEDULED): NOW - timedelta(minutes=16),
        ("a", LANE_WEEKLY_FULL): NOW - timedelta(days=30),
        ("b", LANE_WEEKLY_FULL): NOW, ("c", LANE_WEEKLY_FULL): NOW,
    }
    result = run_plan(modules, last_started=history, max_concurrent_runs=2)
    assert [(r.module, r.lane) for r in result.runs] == [("b", LANE_SCHEDULED), ("a", LANE_SCHEDULED)]
    assert skips(result)[("c", LANE_SCHEDULED)] == "concurrency_cap"
    assert skips(result)[("a", LANE_WEEKLY_FULL)] == "concurrency_cap"


def test_existing_running_runs_count_against_the_cap():
    result = run_plan([mod("a"), mod("b")], running_count=2, max_concurrent_runs=2)
    assert result.runs == []


# ── continuations & write pressure ──────────────────────────────────────────

def test_a_budget_yield_continues_before_the_schedule_says_so():
    from app.modules.zoho.control.planner import LANE_MANUAL, Continuation

    history = {("contacts", LANE_SCHEDULED): NOW - timedelta(minutes=1),   # not due by interval
               ("contacts", LANE_WEEKLY_FULL): NOW - timedelta(minutes=5)}  # this week's slot done
    conts = {("contacts", LANE_WEEKLY_FULL): Continuation(mode="full", due_at=NOW, reason="budget:max_pages"),
             ("contacts", LANE_MANUAL): Continuation(mode="index", due_at=NOW - timedelta(seconds=1))}
    result = run_plan([mod()], last_started=history, continuations=conts)
    assert {(r.lane, r.mode) for r in result.runs} == {(LANE_WEEKLY_FULL, "full"), (LANE_MANUAL, "index")}


def test_a_refused_yield_waits_for_its_backoff():
    from app.modules.zoho.control.planner import Continuation

    history = {("contacts", LANE_SCHEDULED): NOW - timedelta(minutes=1), ("contacts", LANE_WEEKLY_FULL): NOW}
    later = {("contacts", LANE_SCHEDULED): Continuation(mode=None, due_at=NOW + timedelta(minutes=4))}
    assert lanes(run_plan([mod()], last_started=history, continuations=later)) == set()


def test_write_pressure_holds_background_lanes():
    result = run_plan([mod()], write_pressure="cdc_lag_900mb")
    assert result.runs == []
    assert set(skips(result).values()) == {"write_pressure:cdc_lag_900mb"}


def test_weekly_full_can_be_disabled_per_module():
    view = ModuleView(name="contacts", enabled=True, pulls=True, interval_minutes=15,
                      strategy="incremental", weekly_full_enabled=False)
    assert lanes(run_plan([view])) == {("contacts", LANE_SCHEDULED)}
