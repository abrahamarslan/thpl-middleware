"""Field operations through the real API — shifts, pauses, visits, tasks, the stream, verification,
auto-close, metrics, idempotency and the manager side (integration: scratch Postgres + Redis).

The ``worlds`` fixture gives two tenants (ACME, GLOBEX) with an admin and a member each; members
hold ``fieldops.field_work:use`` through the ``member`` template, admins hold everything.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import event, func, select

from app.database.tenancy import system_actor, tenant_scope
from app.modules.compliance.model import ConsentRecord
from app.modules.fieldops.model import (
    Anomaly,
    LocationCheck,
    LocationPing,
    PingBatch,
    Shift,
    ShiftPause,
    StateTransition,
    Visit,
    VisitTask,
)
from app.modules.fieldops.service import metrics, shifts
from app.modules.geo.model import Place
from app.modules.users.model import UserLiveLocation

GODHRA = (22.7772, 73.6203)
FAR = (22.7900, 73.6400)          # ~2.5 km away


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def headers(world, user, *, session: uuid.UUID | None = None, key: uuid.UUID | None = None) -> dict:
    h = world.auth(user, **{"X-Device-Sent-At": now().isoformat()})
    if session is not None:
        h["X-Device-Session"] = str(session)
    if key is not None:
        h["X-Idempotency-Key"] = str(key)
    return h


def fix(point=GODHRA, *, at: dt.datetime | None = None, accuracy: float = 10.0, **extra) -> dict:
    return {"uuid": str(uuid.uuid4()), "latitude": point[0], "longitude": point[1], "accuracy_m": accuracy,
            "provider": "gps", "client_timestamp": (at or now()).isoformat(), **extra}


def clock(at: dt.datetime) -> dict:
    return {"client_timestamp": at.isoformat()}


async def consent(db, world, user) -> None:
    with tenant_scope(world.tenant.id, world.organization.id):
        db.add(ConsentRecord(user_id=user.id, consent_type="location_tracking", consent_given=True,
                             consent_channel="mobile_app", consented_at=now(), organization_id=world.organization.id))
        await db.flush()


async def place(db, world, point=GODHRA, *, verification: str = "field_verified") -> Place:
    with tenant_scope(world.tenant.id, world.organization.id):
        row = Place(kind="customer_site", location_name="Shree Medical Stores",
                    coordinates=WKTElement(f"POINT({point[1]} {point[0]})", srid=4326),
                    verification_status=verification, is_verified=verification == "field_verified",
                    organization_id=world.organization.id)
        db.add(row)
        await db.flush()
    return row


async def start_shift(client, world, user, *, at=None, session=None, **body) -> dict:
    at = at or now() - dt.timedelta(hours=2)
    response = await client.post("/api/me/shifts", headers=headers(world, user, session=session),
                                 json={"uuid": str(uuid.uuid4()), "occurred": clock(at), "fix": fix(at=at), **body})
    assert response.status_code == 201, response.text
    return response.json()["data"]


# ── shifts, pauses ─────────────────────────────────────────────────────────────

async def test_a_shift_starts_pauses_resumes_and_ends_with_paid_time(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    t0 = now() - dt.timedelta(hours=3)
    body = {"uuid": str(uuid.uuid4()), "occurred": clock(t0), "fix": fix(at=t0), "travel_mode": "two_wheeler"}
    first = await client.post("/api/me/shifts", headers=headers(acme, acme.member), json=body)
    assert first.status_code == 201, first.text
    shift = first.json()["data"]
    assert shift["status"] == "active" and shift["start_time_basis"] == "wall_clock_corrected"
    assert abs(dt.datetime.fromisoformat(shift["started_at"]) - t0) < dt.timedelta(seconds=5)   # not the sync time

    replay = await client.post("/api/me/shifts", headers=headers(acme, acme.member), json=body)
    assert replay.status_code == 200 and replay.json()["data"]["uuid"] == shift["uuid"]

    meal = t0 + dt.timedelta(hours=1)
    paused = await client.post(f"/api/me/shifts/{shift['uuid']}/pause", headers=headers(acme, acme.member),
                               json={"uuid": str(uuid.uuid4()), "pause_type": "meal", "occurred": clock(meal)})
    assert paused.status_code == 201, paused.text
    assert paused.json()["data"]["is_paid"] is False and paused.json()["data"]["tracking_suspended"] is True

    place_row = await place(db, acme)
    blocked = await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "place_uuid": str(place_row.uuid), "fix": fix()})
    assert blocked.status_code == 409 and blocked.json()["code"] == "shift_paused"

    again = await client.post(f"/api/me/shifts/{shift['uuid']}/pause", headers=headers(acme, acme.member),
                              json={"uuid": str(uuid.uuid4()), "pause_type": "rest", "occurred": clock(meal)})
    assert again.status_code == 409 and again.json()["code"] == "shift_already_paused"

    resumed = await client.post(f"/api/me/shifts/{shift['uuid']}/resume", headers=headers(acme, acme.member),
                                json={"occurred": clock(meal + dt.timedelta(minutes=30))})
    assert resumed.status_code == 200, resumed.text

    end_at = t0 + dt.timedelta(hours=2, minutes=50)
    ended = await client.post(f"/api/me/shifts/{shift['uuid']}/end", headers=headers(acme, acme.member),
                              json={"occurred": clock(end_at), "fix": fix(at=end_at)})
    assert ended.status_code == 200, ended.text
    data = ended.json()["data"]
    assert data["status"] == "completed" and data["duration_basis"] == "device_reported"
    assert float(data["wall_clock_minutes"]) == pytest.approx(170, abs=0.2)
    assert float(data["unpaid_pause_minutes"]) == pytest.approx(30, abs=0.2)
    assert float(data["paid_minutes"]) == pytest.approx(140, abs=0.2)

    # Every lifecycle step left a history row, and the checkpoints are stream rows.
    shift_id = (await db.scalar(select(Shift.id).where(Shift.uuid == uuid.UUID(shift["uuid"]))))
    moves = (await db.scalars(select(StateTransition.to_state).where(StateTransition.subject_type == "shift",
                                                                     StateTransition.subject_id == shift_id)
                              .order_by(StateTransition.id))).all()
    assert moves == ["active", "paused", "active", "completed"]
    labels = set((await db.scalars(select(LocationPing.checkpoint_label).where(LocationPing.shift_id == shift_id))).all())
    assert {"shift_start", "shift_end"} <= labels


async def test_one_open_shift_per_user_and_consent_first(worlds, db):
    client, acme, _ = worlds
    refused = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                json={"uuid": str(uuid.uuid4()), "fix": fix()})
    assert refused.status_code == 422 and refused.json()["code"] == "location_consent_required"

    await consent(db, acme, acme.member)
    no_location = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                    json={"uuid": str(uuid.uuid4())})
    assert no_location.status_code == 422 and no_location.json()["code"] == "location_required"

    await start_shift(client, acme, acme.member)
    second = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                               json={"uuid": str(uuid.uuid4()), "fix": fix()})
    assert second.status_code == 409 and second.json()["code"] == "shift_already_active"
    assert second.json()["data"]["active_shift"]["status"] == "active"


async def test_a_stale_shift_on_the_same_device_is_superseded_not_a_dead_end(worlds, db):
    """An offline replay cannot act on a 409: a new start from the same device after the old shift has been
    idle past the policy's stale window closes the old one (review pending) instead."""
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    device = await client.post("/api/me/devices", headers=headers(acme, acme.member), json={
        "installation_id": "inst-00000001", "platform": "android",
        "session": {"uuid": str(uuid.uuid4()), "location_permission": "while_in_use", "precise_location": False}})
    assert device.status_code == 200, device.text
    assert {"background_location_not_granted", "approximate_location_only"} <= set(device.json()["data"]["warnings"])
    session = uuid.UUID(device.json()["data"]["session"]["uuid"])

    old = await start_shift(client, acme, acme.member, at=now() - dt.timedelta(hours=10), session=session)
    new = await start_shift(client, acme, acme.member, at=now(), session=session)
    assert new["uuid"] != old["uuid"]
    stale = await db.scalar(select(Shift).where(Shift.uuid == uuid.UUID(old["uuid"])))
    await db.refresh(stale)
    assert (stale.status, stale.end_reason, stale.review_status) == ("auto_closed", "superseded", "pending")
    assert await db.scalar(select(func.count()).select_from(Anomaly)
                           .where(Anomaly.anomaly_type == "superseded_shift")) == 1


# ── visits ──────────────────────────────────────────────────────────────────────

async def test_visits_need_a_shift_and_only_one_runs_at_a_time(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    shop = await place(db, acme)
    body = {"uuid": str(uuid.uuid4()), "place_uuid": str(shop.uuid), "fix": fix()}
    no_shift = await client.post("/api/me/visits", headers=headers(acme, acme.member), json=body)
    assert no_shift.status_code == 422 and no_shift.json()["code"] == "shift_required"

    await start_shift(client, acme, acme.member)
    started = await client.post("/api/me/visits", headers=headers(acme, acme.member), json=body)
    assert started.status_code == 201, started.text
    assert started.json()["data"]["start_check"] == "inside"

    other = await place(db, acme, FAR)
    second = await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "place_uuid": str(other.uuid), "fix": fix(FAR)})
    assert second.status_code == 409 and second.json()["code"] == "visit_in_progress"

    phone = await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "channel": "telephonic"})
    assert phone.status_code == 403                                   # member role: no telephonic permission


async def test_soft_block_needs_a_justification_and_records_why(worlds, db):
    client, acme, _ = worlds
    created = await client.post("/api/fieldops/policies", headers=acme.auth(acme.admin),
                                json={"name": "ACME default", "geofence_enforcement": "soft_block"})
    assert created.status_code == 201, created.text
    await consent(db, acme, acme.member)
    shop = await place(db, acme)
    await start_shift(client, acme, acme.member)

    body = {"uuid": str(uuid.uuid4()), "place_uuid": str(shop.uuid), "fix": fix(FAR, accuracy=15)}
    refused = await client.post("/api/me/visits", headers=headers(acme, acme.member), json=body)
    assert refused.status_code == 422 and refused.json()["code"] == "justification_required"
    assert refused.json()["data"]["result"] == "outside" and refused.json()["data"]["distance_m"] > 2000
    assert await db.scalar(select(func.count()).select_from(Visit)) == 0          # nothing left behind

    body["justification"] = {"code": "met_outside", "note": "Owner met me at the depot"}
    accepted = await client.post("/api/me/visits", headers=headers(acme, acme.member), json=body)
    assert accepted.status_code == 201, accepted.text
    visit = accepted.json()["data"]
    assert (visit["start_check"], visit["review_status"], visit["start_justification_code"]) == \
        ("outside", "pending", "met_outside")
    check = await db.scalar(select(LocationCheck).where(LocationCheck.phase == "start"))
    assert (check.target_kind, check.action_taken, check.enforcement) == ("place_default", "justified", "soft_block")
    assert await db.scalar(select(Anomaly.anomaly_type).where(Anomaly.subject_type == "visit")) == "justified_outside"


async def test_an_offline_start_is_never_blocked_even_under_hard_block(worlds, db):
    client, acme, _ = worlds
    await client.post("/api/fieldops/policies", headers=acme.auth(acme.admin),
                      json={"name": "strict", "geofence_enforcement": "hard_block"})
    await consent(db, acme, acme.member)
    shop = await place(db, acme)
    await start_shift(client, acme, acme.member, at=now() - dt.timedelta(hours=5))

    online = await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "place_uuid": str(shop.uuid), "fix": fix(FAR)})
    assert online.status_code == 422 and online.json()["code"] == "outside_geofence"

    happened = now() - dt.timedelta(hours=1)                      # recorded offline an hour ago, synced now
    offline = await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "place_uuid": str(shop.uuid), "occurred": clock(happened),
        "fix": fix(FAR, at=happened)})
    assert offline.status_code == 201, offline.text
    assert offline.json()["data"]["review_status"] == "pending"
    assert await db.scalar(select(Anomaly.severity).where(
        Anomaly.anomaly_type == "hard_block_bypassed_offline")) == "critical"


async def test_no_place_coordinates_never_blocks(worlds, db):
    client, acme, _ = worlds
    await client.post("/api/fieldops/policies", headers=acme.auth(acme.admin),
                      json={"name": "strict", "geofence_enforcement": "hard_block"})
    await consent(db, acme, acme.member)
    unmapped = await place(db, acme, verification="unverified")
    await start_shift(client, acme, acme.member)
    started = await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "place_uuid": str(unmapped.uuid), "fix": fix(FAR)})
    assert started.status_code == 201 and started.json()["data"]["start_check"] == "not_configured"


# ── tasks ───────────────────────────────────────────────────────────────────────

async def test_a_payment_after_the_visit_ended_is_recorded_not_rejected(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    shop = await place(db, acme)
    await start_shift(client, acme, acme.member, at=now() - dt.timedelta(hours=4))
    visit = (await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "place_uuid": str(shop.uuid), "occurred": clock(now() - dt.timedelta(hours=3)),
        "fix": fix(at=now() - dt.timedelta(hours=3))})).json()["data"]
    ended = await client.post(f"/api/me/visits/{visit['uuid']}/end", headers=headers(acme, acme.member),
                              json={"occurred": clock(now() - dt.timedelta(hours=2)), "outcome": "collection_only"})
    assert ended.status_code == 200, ended.text

    bad = await client.post(f"/api/me/visits/{visit['uuid']}/tasks", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "task_type": "collect_payment", "payload": {"mode": "barter"},
        "amount": "500.00", "currency_code": "INR"})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_task_payload"

    task_body = {"uuid": str(uuid.uuid4()), "task_type": "collect_payment", "payload": {"mode": "upi"},
                 "amount": "1250.50", "currency_code": "INR", "occurred": clock(now() - dt.timedelta(minutes=30))}
    late = await client.post(f"/api/me/visits/{visit['uuid']}/tasks", headers=headers(acme, acme.member),
                             json=task_body)
    assert late.status_code == 201, late.text
    assert late.json()["data"]["after_visit_end"] is True
    replay = await client.post(f"/api/me/visits/{visit['uuid']}/tasks", headers=headers(acme, acme.member),
                               json=task_body)
    assert replay.status_code == 200
    assert await db.scalar(select(func.count()).select_from(VisitTask)) == 1
    assert await db.scalar(select(Anomaly.anomaly_type).where(Anomaly.subject_type == "visit_task")) == "late_task"


# ── the stream ──────────────────────────────────────────────────────────────────

async def test_a_ping_batch_is_accepted_per_item_and_replays_are_no_ops(worlds, db):
    client, acme, _ = worlds
    good = [fix(at=now() - dt.timedelta(minutes=m)) for m in (6, 4)]
    batch = {"uuid": str(uuid.uuid4()), "pings": [*good, {"uuid": str(uuid.uuid4()), "latitude": 95, "longitude": 0}]}
    first = await client.post("/api/me/location-pings", headers=headers(acme, acme.member), json=batch)
    assert first.status_code == 200, first.text
    result = first.json()["data"]
    assert (result["accepted"], result["duplicates"], result["rejected"]) == (2, 0, 1)
    assert result["results"][0]["status"] == "rejected" and "latitude" in result["results"][0]["reason"]

    again = await client.post("/api/me/location-pings", headers=headers(acme, acme.member), json=batch)
    assert again.json()["data"]["replayed"] is True

    resent = await client.post("/api/me/location-pings", headers=headers(acme, acme.member),
                               json={"uuid": str(uuid.uuid4()), "pings": good})
    assert (resent.json()["data"]["accepted"], resent.json()["data"]["duplicates"]) == (0, 2)
    assert await db.scalar(select(func.count()).select_from(LocationPing)) == 2
    assert await db.scalar(select(func.count()).select_from(PingBatch)) == 2

    live = await db.scalar(select(UserLiveLocation).where(UserLiveLocation.user_id == acme.member.id))
    newest = dt.datetime.fromisoformat(good[1]["client_timestamp"])
    assert abs(live.recorded_at - newest) < dt.timedelta(seconds=5)
    # An older fix replayed later never moves the live position backwards.
    await client.post("/api/me/location-pings", headers=headers(acme, acme.member),
                      json={"uuid": str(uuid.uuid4()), "pings": [fix(FAR, at=now() - dt.timedelta(hours=3))]})
    await db.refresh(live)
    assert abs(live.recorded_at - newest) < dt.timedelta(seconds=5)


async def test_a_far_future_device_clock_is_clamped_and_flagged(worlds, db):
    client, acme, _ = worlds
    wild = fix(at=now() + dt.timedelta(days=700))
    response = await client.post("/api/me/location-pings", headers=headers(acme, acme.member),
                                 json={"uuid": str(uuid.uuid4()), "pings": [wild]})
    assert response.json()["data"]["accepted"] == 1
    row = await db.scalar(select(LocationPing).where(LocationPing.uuid == uuid.UUID(wild["uuid"])))
    assert row.quality_flags & 32 and row.recorded_at <= now() + dt.timedelta(minutes=1)
    assert row.client_timestamp > now() + dt.timedelta(days=600)                 # the raw value is kept


async def test_ingest_does_not_grow_its_query_count_with_the_batch(worlds, db):
    client, acme, _ = worlds
    # Warm-up: the first request of a session pays one-time costs (grant load, live row creation).
    await client.post("/api/me/location-pings", headers=headers(acme, acme.member),
                      json={"uuid": str(uuid.uuid4()), "pings": [fix(at=now() - dt.timedelta(hours=1))]})
    counts = []
    for size in (2, 40):
        statements = []

        def count(*_args, **_kw):
            statements.append(1)

        engine = db.bind.sync_engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            response = await client.post("/api/me/location-pings", headers=headers(acme, acme.member), json={
                "uuid": str(uuid.uuid4()),
                "pings": [fix((22.77 + i * 0.0005, 73.62), at=now() - dt.timedelta(seconds=30 * (size - i)))
                          for i in range(size)]})
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert response.json()["data"]["accepted"] == size
        counts.append(len(statements))
    assert counts[0] == counts[1], counts


# ── auto-close ──────────────────────────────────────────────────────────────────

async def test_auto_close_never_invents_a_long_shift(worlds, db):
    """App killed right after shift start: the shift closes AT its start (0 min), flagged as a ghost, and
    its in-progress visit is cancelled so it cannot block tomorrow."""
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    shop = await place(db, acme)
    started = now() - dt.timedelta(hours=20)
    shift = await start_shift(client, acme, acme.member, at=started)
    visit = await client.post("/api/me/visits", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "place_uuid": str(shop.uuid), "occurred": clock(started),
        "fix": fix(at=started)})
    assert visit.status_code == 201, visit.text

    with tenant_scope(None, None, system_actor("fieldops-autoclose")):
        closed = await shifts.auto_close_due(db)
    row = await db.scalar(select(Shift).where(Shift.uuid == uuid.UUID(shift["uuid"])))
    assert row.id in closed
    await db.refresh(row)
    assert (row.status, row.duration_basis, row.review_status) == ("auto_closed", "system_estimated", "pending")
    assert float(row.wall_clock_minutes) == pytest.approx(0, abs=0.1)
    kinds = set((await db.scalars(select(Anomaly.anomaly_type).where(Anomaly.shift_id == row.id))).all())
    assert {"auto_closed", "ghost_shift"} <= kinds
    stuck = await db.scalar(select(Visit).where(Visit.shift_id == row.id))
    await db.refresh(stuck)
    assert (stuck.status, stuck.cancellation_reason) == ("cancelled", "shift_auto_closed")

    fresh = await start_shift(client, acme, acme.member)            # tomorrow starts cleanly
    assert fresh["status"] == "active"


# ── idempotency ─────────────────────────────────────────────────────────────────

async def test_an_idempotency_key_replays_the_stored_response(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    shift = await start_shift(client, acme, acme.member)
    key = uuid.uuid4()
    body = {"occurred": clock(now()), "fix": fix()}
    first = await client.post(f"/api/me/shifts/{shift['uuid']}/end", headers=headers(acme, acme.member, key=key),
                              json=body)
    assert first.status_code == 200, first.text
    replay = await client.post(f"/api/me/shifts/{shift['uuid']}/end", headers=headers(acme, acme.member, key=key),
                               json=body)
    assert replay.status_code == 200 and replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json() == first.json()
    reused = await client.post(f"/api/me/shifts/{shift['uuid']}/end", headers=headers(acme, acme.member, key=key),
                               json={**body, "notes": "different"})
    assert reused.status_code == 409 and reused.json()["code"] == "idempotency_key_reused"
    without_key = await client.post(f"/api/me/shifts/{shift['uuid']}/end", headers=headers(acme, acme.member),
                                    json=body)
    assert without_key.status_code == 409 and without_key.json()["code"] == "shift_not_active"


# ── metrics ─────────────────────────────────────────────────────────────────────

async def test_metrics_keep_field_and_telephonic_apart(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.admin)                          # admins hold the telephonic permission
    shop = await place(db, acme)
    t0 = now() - dt.timedelta(hours=3)
    shift = await start_shift(client, acme, acme.admin, at=t0)

    async def visit(channel: str, at: dt.datetime, **extra) -> dict:
        body = {"uuid": str(uuid.uuid4()), "channel": channel, "occurred": clock(at), **extra}
        response = await client.post("/api/me/visits", headers=headers(acme, acme.admin), json=body)
        assert response.status_code == 201, response.text
        created = response.json()["data"]
        order = await client.post(f"/api/me/visits/{created['uuid']}/tasks", headers=headers(acme, acme.admin), json={
            "uuid": str(uuid.uuid4()), "task_type": "take_order", "occurred": clock(at + dt.timedelta(minutes=5)),
            "payload": {"lines": [{"item_ref": "PCM-650", "quantity": 10}]}, "amount": "900", "currency_code": "INR"})
        assert order.status_code == 201, order.text
        await client.post(f"/api/me/visits/{created['uuid']}/end", headers=headers(acme, acme.admin), json={
            "occurred": clock(at + dt.timedelta(minutes=20)), "outcome": "order_taken"})
        return created

    await visit("field", t0 + dt.timedelta(minutes=30), place_uuid=str(shop.uuid),
                fix=fix(at=t0 + dt.timedelta(minutes=30)))
    await visit("telephonic", t0 + dt.timedelta(minutes=90))
    await client.post(f"/api/me/shifts/{shift['uuid']}/end", headers=headers(acme, acme.admin),
                      json={"occurred": clock(t0 + dt.timedelta(hours=2)), "fix": fix(at=t0 + dt.timedelta(hours=2))})

    row = await metrics.compute_shift_metrics(db, (await db.scalar(select(Shift.id).where(
        Shift.uuid == uuid.UUID(shift["uuid"])))))
    assert (row.field_visits, row.telephonic_visits, row.orders_field, row.orders_telephonic) == (1, 1, 1, 1)
    assert (row.order_value_field, row.order_value_telephonic, row.currency_code) == (900, 900, "INR")
    assert (row.visits_checked, row.visits_inside) == (1, 1) and float(row.geofence_compliance_pct) == 100
    assert float(row.visit_minutes) == pytest.approx(20, abs=0.5)          # the phone call is not field time
    again = await metrics.compute_shift_metrics(db, row.shift_id)
    assert again.computed_at == row.computed_at                            # unchanged inputs: no write


# ── the manager side ────────────────────────────────────────────────────────────

async def test_managers_read_what_they_may_and_other_tenants_nothing(worlds, db):
    client, acme, globex = worlds
    await consent(db, acme, acme.member)
    shift = await start_shift(client, acme, acme.member)

    member = await client.get("/api/fieldops/shifts", headers=acme.auth(acme.member))
    assert member.status_code == 403
    admin = await client.get("/api/fieldops/shifts", headers=acme.auth(acme.admin))
    assert admin.status_code == 200 and [s["uuid"] for s in admin.json()["data"]["items"]] == [shift["uuid"]]
    detail = await client.get(f"/api/fieldops/shifts/{shift['uuid']}", headers=acme.auth(acme.admin))
    assert detail.status_code == 200 and detail.json()["data"]["shift"]["status"] == "active"
    track = await client.get(f"/api/fieldops/shifts/{shift['uuid']}/track", headers=acme.auth(acme.admin))
    assert track.status_code == 200 and track.json()["data"]["points"][0]["checkpoint_label"] == "shift_start"
    live = await client.get("/api/fieldops/live", headers=acme.auth(acme.admin))
    assert [u["user_id"] for u in live.json()["data"]] == [acme.member.id]

    foreign = await client.get(f"/api/fieldops/shifts/{shift['uuid']}", headers=globex.auth(globex.admin))
    assert foreign.status_code == 404
    assert (await client.get("/api/fieldops/live", headers=globex.auth(globex.admin))).json()["data"] == []


async def test_a_manager_correction_is_recorded_and_recomputes_paid_time(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    t0 = now() - dt.timedelta(hours=5)
    shift = await start_shift(client, acme, acme.member, at=t0)
    await client.post(f"/api/me/shifts/{shift['uuid']}/end", headers=headers(acme, acme.member),
                      json={"occurred": clock(t0 + dt.timedelta(hours=4)), "fix": fix()})
    row = await db.scalar(select(Shift).where(Shift.uuid == uuid.UUID(shift["uuid"])))
    await db.refresh(row)
    seen = row.row_version                    # what the manager's screen loaded
    fixed = await client.patch(f"/api/fieldops/shifts/{shift['uuid']}", headers=acme.auth(acme.admin), json={
        "row_version": seen, "reason": "Forgot to end on time",
        "ended_at": (t0 + dt.timedelta(hours=3)).isoformat()})
    assert fixed.status_code == 200, fixed.text
    data = fixed.json()["data"]
    assert (data["review_status"], data["duration_basis"]) == ("corrected", "manager_adjusted")
    assert float(data["paid_minutes"]) == pytest.approx(180, abs=0.2)
    stale = await client.patch(f"/api/fieldops/shifts/{shift['uuid']}", headers=acme.auth(acme.admin), json={
        "row_version": seen, "reason": "again", "ended_at": (t0 + dt.timedelta(hours=2)).isoformat()})
    assert stale.status_code == 409
    changes = await db.scalar(select(StateTransition.changes).where(StateTransition.to_state == "corrected"))
    assert "ended_at" in changes


async def test_legacy_location_endpoint_feeds_the_stream(worlds, db):
    client, acme, _ = worlds
    response = await client.patch("/api/me/location", headers=acme.auth(acme.member),
                                   json={"latitude": GODHRA[0], "longitude": GODHRA[1], "accuracy_m": 8,
                                         "location_source": "gps"})
    assert response.status_code == 200, response.text
    assert await db.scalar(select(func.count()).select_from(LocationPing)) == 1
    assert (await client.get("/api/auth/me/location", headers=acme.auth(acme.member))).json()["data"] is not None
    assert await db.scalar(select(func.count()).select_from(ShiftPause)) == 0
