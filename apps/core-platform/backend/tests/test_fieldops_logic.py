"""Field operations — the pure rules, no database (docs/fieldops/implementation-of-shift-visits-system.md).

clock          business time from three clocks; the partition-key clamp; the business day
verification   accuracy-aware classification (circle + polygon), radius from provenance,
               the enforcement matrix (incl. the offline rule)
trackmath      impossible hops, movement, distance without jitter, coverage and gaps, dwell
state          which transitions exist
task_types     every task type has a registry entry; payload validation
policy         snapshot round trip
"""

import datetime as dt
import json
import uuid
from pathlib import Path

import pytest

from app.modules.fieldops import clock, state, trackmath
from app.modules.fieldops.enums import (
    AnomalyType,
    CheckAction,
    CheckResult,
    Enforcement,
    QualityFlag,
    TaskType,
    TimeBasis,
)
from app.modules.fieldops.task_types import REGISTRY, spec_for
from app.modules.fieldops.verification import classify, classify_polygon, decide, target_radius

T0 = dt.datetime(2026, 9, 28, 9, 0, tzinfo=dt.UTC)


# ── clock ───────────────────────────────────────────────────────────────────────

def test_monotonic_clock_wins_and_ignores_a_wrong_wall_clock():
    """Same boot: the event happened (sent_elapsed − event_elapsed) before receipt — the device's
    wall clock (set a day wrong here) does not matter."""
    send = clock.SendContext(received_at=T0 + dt.timedelta(hours=9), sent_at=T0 + dt.timedelta(days=1),
                             sent_elapsed_ms=50_000_000, boot_count=7)
    event = clock.EventClock(client_timestamp=T0 - dt.timedelta(days=3), elapsed_realtime_ms=50_000_000 - 3_600_000,
                             boot_count=7)
    derived = clock.derive(send, event)
    assert derived.time_basis is TimeBasis.MONOTONIC
    assert derived.occurred_at == T0 + dt.timedelta(hours=8)


def test_a_reboot_falls_back_to_the_skew_corrected_wall_clock():
    """Offline 09:02 → synced 18:40 with a device clock 5 minutes fast: the start is 09:02, not 18:40."""
    fast = dt.timedelta(minutes=5)
    received = T0 + dt.timedelta(hours=9, minutes=40)
    send = clock.SendContext(received_at=received, sent_at=received + fast, sent_elapsed_ms=10_000, boot_count=8)
    event = clock.EventClock(client_timestamp=T0 + dt.timedelta(minutes=2) + fast, elapsed_realtime_ms=99_999_999,
                             boot_count=7)
    derived = clock.derive(send, event)
    assert derived.time_basis is TimeBasis.WALL_CLOCK_CORRECTED
    assert derived.occurred_at == T0 + dt.timedelta(minutes=2)
    assert derived.clock_skew_ms == -5 * 60 * 1000


def test_a_legacy_client_without_send_headers_gets_its_raw_wall_clock():
    derived = clock.derive(clock.SendContext(received_at=T0), clock.EventClock(client_timestamp=T0 - dt.timedelta(hours=1)))
    assert derived.time_basis is TimeBasis.DEVICE_WALL_CLOCK
    assert derived.occurred_at == T0 - dt.timedelta(hours=1)


def test_nothing_happens_in_the_future_or_implausibly_long_ago():
    future = clock.derive(clock.SendContext(received_at=T0), clock.EventClock(client_timestamp=T0 + dt.timedelta(days=2)))
    assert future.occurred_at == T0
    ancient = clock.derive(clock.SendContext(received_at=T0),
                           clock.EventClock(client_timestamp=T0 - dt.timedelta(days=400)))
    assert ancient.time_basis is TimeBasis.SERVER_RECEIPT and ancient.occurred_at == T0
    assert clock.derive(clock.SendContext(received_at=T0), None).time_basis is TimeBasis.SERVER_RECEIPT


def test_the_partition_key_is_the_device_time_unless_absurd():
    assert clock.partition_key(T0 - dt.timedelta(days=3), T0) == (T0 - dt.timedelta(days=3), False)
    assert clock.partition_key(T0 + dt.timedelta(days=900), T0) == (T0, True)     # a phone set to 2029
    assert clock.partition_key(T0 - dt.timedelta(days=60), T0) == (T0, True)
    assert clock.partition_key(None, T0) == (T0, True)


def test_the_business_day_is_the_organizations_not_the_devices():
    late_evening_utc = dt.datetime(2026, 9, 28, 19, 0, tzinfo=dt.UTC)     # 00:30 IST on the 29th
    assert clock.business_date(late_evening_utc, "Asia/Kolkata") == dt.date(2026, 9, 29)
    assert clock.business_date(late_evening_utc, "Europe/London") == dt.date(2026, 9, 28)
    assert clock.business_date(late_evening_utc, "Not/AZone") == dt.date(2026, 9, 29)   # falls back to IST


# ── verification ──────────────────────────────────────────────────────────────

_CASES = json.loads((Path(__file__).parent / "fixtures" / "fieldops_classify_cases.json").read_text())


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_classify_shared_cases(case):
    """The shared table the mobile app's port is tested against too."""
    assert classify(case["distance_m"], case["radius_m"], case["accuracy_m"], channel=case.get("channel", "field"),
                    max_accuracy_m=case.get("max_accuracy_m", 100)).value == case["expected"]


def test_a_polygon_needs_the_accuracy_circle_to_clear_the_edge():
    assert classify_polygon(True, 40, 20) is CheckResult.INSIDE
    assert classify_polygon(True, 10, 20) is CheckResult.UNCERTAIN
    assert classify_polygon(False, 50, 20) is CheckResult.OUTSIDE
    assert classify_polygon(False, 5, 20) is CheckResult.UNCERTAIN
    assert classify_polygon(None, None, None) is CheckResult.NO_FIX
    assert classify_polygon(True, 40, 20, channel="telephonic") is CheckResult.NOT_APPLICABLE


def test_the_fallback_radius_follows_the_places_provenance():
    assert target_radius("field_verified", base_m=100, geocoded_factor=2.5) == 100
    assert target_radius("geocoded_only", base_m=100, geocoded_factor=2.5) == 250
    assert target_radius("unverified", base_m=100, geocoded_factor=2.5) is None
    assert target_radius("disputed", base_m=100, geocoded_factor=2.5) is None


@pytest.mark.parametrize(("result", "mode", "offline", "justified", "action", "block", "anomaly"), [
    (CheckResult.INSIDE, Enforcement.HARD_BLOCK, False, False, CheckAction.RECORDED, None, None),
    (CheckResult.UNCERTAIN, Enforcement.HARD_BLOCK, False, False, CheckAction.RECORDED, None, None),
    (CheckResult.NO_FIX, Enforcement.SOFT_BLOCK, False, False, CheckAction.RECORDED, None, None),
    (CheckResult.NOT_CONFIGURED, Enforcement.HARD_BLOCK, False, False, CheckAction.RECORDED, None, None),
    (CheckResult.OUTSIDE, Enforcement.ADVISORY, False, False, CheckAction.RECORDED, None, AnomalyType.OUTSIDE_GEOFENCE),
    (CheckResult.OUTSIDE, Enforcement.SOFT_BLOCK, False, False, CheckAction.JUSTIFICATION_REQUIRED,
     "justification_required", None),
    (CheckResult.OUTSIDE, Enforcement.SOFT_BLOCK, False, True, CheckAction.JUSTIFIED, None,
     AnomalyType.JUSTIFIED_OUTSIDE),
    (CheckResult.OUTSIDE, Enforcement.SOFT_BLOCK, True, False, CheckAction.BYPASSED_OFFLINE, None,
     AnomalyType.OUTSIDE_GEOFENCE),
    (CheckResult.OUTSIDE, Enforcement.HARD_BLOCK, False, True, CheckAction.BLOCKED, "outside_geofence", None),
    (CheckResult.OUTSIDE, Enforcement.HARD_BLOCK, True, False, CheckAction.BYPASSED_OFFLINE, None,
     AnomalyType.HARD_BLOCK_BYPASSED_OFFLINE),
])
def test_the_enforcement_matrix(result, mode, offline, justified, action, block, anomaly):
    decision = decide(result, mode, offline=offline, justified=justified)
    assert (decision.action, decision.block_code, decision.anomaly) == (action, block, anomaly)
    if offline and result is CheckResult.OUTSIDE and mode is not Enforcement.ADVISORY:
        assert decision.review_pending and decision.block_code is None     # what happened offline is never refused


# ── trackmath ──────────────────────────────────────────────────────────────────

def _fix(minutes: float, lat: float, lng: float, accuracy: float = 10, **kw) -> trackmath.Fix:
    return trackmath.Fix(T0 + dt.timedelta(minutes=minutes), lat, lng, accuracy, **kw)


def test_an_impossible_hop_is_detected_but_accuracy_is_forgiven():
    a = _fix(0, 22.7772, 73.6203)
    assert trackmath.is_impossible_hop(a, _fix(1, 23.0225, 72.5714))            # Godhra → Ahmedabad in a minute
    assert not trackmath.is_impossible_hop(a, _fix(60, 22.80, 73.62))           # 2.5 km in an hour
    near = trackmath.Fix(T0 + dt.timedelta(seconds=1), 22.7775, 73.6203, 50)    # 33 m in 1 s, inside ±60 m
    assert not trackmath.is_impossible_hop(trackmath.Fix(T0, 22.7772, 73.6203, 10), near)


def test_standing_still_with_jitter_is_not_travel():
    jitter = [_fix(i, 22.7772 + (0.0001 if i % 2 else 0), 73.6203, accuracy=30) for i in range(30)]
    assert trackmath.distance_km(jitter) == 0
    assert trackmath.moving_intervals(jitter, max_gap=dt.timedelta(minutes=10)) == []
    road = [_fix(i, 22.7772 + i * 0.002, 73.6203, accuracy=10) for i in range(10)]     # ~220 m a minute
    assert trackmath.distance_km(road) == pytest.approx(2.0, rel=0.05)
    assert trackmath.minutes(trackmath.moving_intervals(road, max_gap=dt.timedelta(minutes=10))) == pytest.approx(9)


def test_coverage_and_the_longest_gap_include_window_edges():
    window = [(T0, T0 + dt.timedelta(minutes=60))]
    fixes = [T0 + dt.timedelta(minutes=m) for m in range(0, 30)]          # the app died at minute 30
    pct, gap = trackmath.coverage(fixes, window, bucket=dt.timedelta(minutes=2))
    assert pct == pytest.approx(50, abs=4)
    assert gap == pytest.approx(31, abs=1)


def test_intervals_merge_and_subtract():
    a = [(T0, T0 + dt.timedelta(minutes=30)), (T0 + dt.timedelta(minutes=20), T0 + dt.timedelta(minutes=40))]
    assert trackmath.merge(a) == [(T0, T0 + dt.timedelta(minutes=40))]
    holes = [(T0 + dt.timedelta(minutes=10), T0 + dt.timedelta(minutes=15))]
    assert trackmath.minutes(trackmath.subtract(a, holes)) == 35


def test_dwell_ignores_a_single_bounce():
    samples = [(T0 + dt.timedelta(seconds=30 * i), inside, 10.0) for i, inside in enumerate(
        [False, True, False, False, True, True, True, True, False, False, False, False])]
    found = trackmath.dwell(samples, dwell_s=60)
    assert found.entry_at == T0 + dt.timedelta(seconds=120)             # the lone fix at 30 s did not count
    assert found.exit_at == T0 + dt.timedelta(seconds=240)
    assert trackmath.dwell([(T0, True, 10.0)], dwell_s=60).entry_at is None


def test_untrusted_fixes_are_not_evidence():
    assert not trackmath.trusted(_fix(0, 22.7, 73.6, is_mock=True), max_accuracy_m=100)
    assert not trackmath.trusted(_fix(0, 22.7, 73.6, flags=int(QualityFlag.IMPOSSIBLE_SPEED)), max_accuracy_m=100)
    assert not trackmath.trusted(_fix(0, 22.7, 73.6, accuracy=250), max_accuracy_m=100)
    assert trackmath.trusted(_fix(0, 22.7, 73.6, flags=int(QualityFlag.CLOCK_SKEW)), max_accuracy_m=100)


# ── state ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("subject", "frm", "to", "ok"), [
    ("shift", "active", "paused", True),
    ("shift", "paused", "active", True),
    ("shift", "paused", "completed", True),
    ("shift", "paused", "paused", False),
    ("shift", "completed", "active", False),
    ("shift", "auto_closed", "completed", False),
    ("visit", "planned", "missed", True),
    ("visit", "in_progress", "missed", False),
    ("visit", "completed", "in_progress", False),
])
def test_lifecycle_tables(subject, frm, to, ok):
    assert state.allowed(subject, "lifecycle", frm, to) is ok


def test_review_can_be_reopened_and_re_decided():
    assert state.allowed("shift", "review", "approved", "pending")
    assert state.allowed("visit", "review", "pending", "rejected")
    assert not state.allowed("shift", "review", "pending", "not_required")
    with pytest.raises(state.InvalidTransition):
        state.assert_allowed("shift", "lifecycle", "completed", "paused")


# ── task registry ───────────────────────────────────────────────────────────────

def test_every_task_type_has_a_spec_and_payload_model():
    assert set(REGISTRY) == {t.value for t in TaskType}


def test_payloads_are_validated_but_unknown_keys_survive():
    spec = spec_for("distribute_sample")
    ok = spec.payload_model.model_validate({"product_ref": "AMOX-500", "batch_no": "B12", "quantity": 2,
                                            "newer_app_field": "kept"})
    assert ok.model_dump()["newer_app_field"] == "kept"
    with pytest.raises(ValueError):
        spec.payload_model.model_validate({"product_ref": "AMOX-500", "quantity": 2})        # no batch_no
    assert "telephonic" not in spec_for("deliver").channels
    assert spec_for("take_order").is_order and spec_for("collect_payment").is_collection


# ── policy snapshot ────────────────────────────────────────────────────────────

def test_a_policy_snapshot_round_trips():
    from app.modules.fieldops.service.policy import CODE_DEFAULTS, EffectivePolicy

    policy = EffectivePolicy({"max_shift_hours": 9, "earliest_start_local": dt.time(8, 30)}, policy_id=5,
                             policy_uuid=uuid.uuid4())
    again = EffectivePolicy.from_snapshot(json.loads(json.dumps(policy.snapshot())))
    assert again.policy_id == 5 and again.number("max_shift_hours") == 9
    assert again.earliest_start_local == dt.time(8, 30)
    assert again.geofence_enforcement == CODE_DEFAULTS["geofence_enforcement"] == "advisory"
    assert set(again.paid_pause_types) == {"rest", "meeting", "training"}
