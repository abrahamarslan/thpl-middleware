"""Shift planning: templates (materialized at start, virtual entries), scheduled shifts, route endpoints with
geofence enforcement, the hub of the day, stops, auto-close caps, missed shifts, the mock policy, the silence
detector and the company seed (docs/fieldops/shift-templates.md). Integration: scratch Postgres + Redis."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.database.tenancy import tenant_scope
from app.modules.fieldops.model import Anomaly, LocationCheck, PolicyLayer, Shift, ShiftTemplate
from app.modules.fieldops.service import shifts as shift_service
from app.modules.fieldops.service import templates
from tests.test_fieldops_api import FAR, GODHRA, clock, consent, fix, headers, now, place

IST = "Asia/Kolkata"


# ── pure ────────────────────────────────────────────────────────────────────────

def tpl(start=dt.time(9), end=dt.time(21), offset=0, days=(1, 2, 3, 4, 5, 6, 7), tz=IST):
    return SimpleNamespace(start_local_time=start, end_local_time=end, end_day_offset=offset, days_of_week=list(days),
                           timezone=tz, status="active", valid_from=None, valid_until=None, name="Work Shift",
                           title_pattern=None)


def ist(y, mo, d, h, mi=0) -> dt.datetime:
    from zoneinfo import ZoneInfo

    return dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(IST)).astimezone(dt.UTC)


def test_the_work_shift_occurrence_in_ist():
    occ = templates.occurrence(tpl(), ist(2026, 10, 6, 8, 15), None)          # early: before 09:00
    assert occ.day == dt.date(2026, 10, 6)
    assert occ.planned_start_at == ist(2026, 10, 6, 9) and occ.planned_end_at == ist(2026, 10, 6, 21)
    assert occ.planned_start_at.isoformat() == "2026-10-06T03:30:00+00:00"
    assert templates.occurrence(tpl(), ist(2026, 10, 6, 21, 30), None) is None    # the window is over
    # 00:30 IST is still the previous UTC date: the business day is the TEMPLATE's
    assert templates.occurrence(tpl(), ist(2026, 10, 7, 0, 30), None).day == dt.date(2026, 10, 7)


def test_an_overnight_occurrence_belongs_to_the_day_it_started():
    night = tpl(dt.time(22), dt.time(6), offset=1)
    occ = templates.occurrence(night, ist(2026, 10, 7, 1), None)
    assert occ.day == dt.date(2026, 10, 6) and occ.planned_end_at == ist(2026, 10, 7, 6)


def test_days_of_week_gate_the_occurrence():
    weekdays = tpl(days=(1, 2, 3, 4, 5))
    assert templates.occurrence(weekdays, ist(2026, 10, 4, 10), None) is None        # a Sunday
    assert templates.occurrence(weekdays, ist(2026, 10, 5, 10), None) is not None    # a Monday


def test_the_auto_close_cap_is_bounded_by_both_plan_and_policy():
    from app.modules.fieldops.service.policy import EffectivePolicy

    policy = EffectivePolicy({"max_shift_hours": 12, "overtime_minutes": 0, "auto_close_grace_minutes": 60})
    start = ist(2026, 10, 6, 9)
    planned = SimpleNamespace(started_at=start, planned_end_at=ist(2026, 10, 6, 21), auto_close_at=None)
    assert shift_service.compute_auto_close(planned, policy) == ist(2026, 10, 6, 22)    # 21:00 + 60 min grace
    early = SimpleNamespace(started_at=ist(2026, 10, 6, 6), planned_end_at=ist(2026, 10, 6, 21), auto_close_at=None)
    assert shift_service.compute_auto_close(early, policy) == ist(2026, 10, 6, 19)      # 06:00 + 12 h + grace
    ad_hoc = SimpleNamespace(started_at=start, planned_end_at=None, auto_close_at=None)
    assert shift_service.compute_auto_close(ad_hoc, policy) == ist(2026, 10, 6, 22)
    overtime = EffectivePolicy({"max_shift_hours": 14, "overtime_minutes": 60, "auto_close_grace_minutes": 30})
    assert shift_service.compute_auto_close(planned, overtime) == ist(2026, 10, 6, 22, 30)


# ── helpers ─────────────────────────────────────────────────────────────────────

async def member_role(db, world) -> int:
    from app.modules.roles.model import Role

    return await db.scalar(select(Role.id).where(Role.organization_id == world.organization.id, Role.code == "member"))


async def all_day_template(client, world, *, code="ALLDAY", start=None, end=None) -> dict:
    """A template covering the whole UTC day, so tests do not depend on the clock."""
    body = {"code": code, "name": "All Day", "work_type": "delivery", "start_local_time": "00:00:00",
            "end_local_time": "23:59:00", "timezone": "UTC"}
    if start is not None:
        body["start"] = start
    if end is not None:
        body["end"] = end
    response = await client.post("/api/fieldops/shift-templates", headers=world.auth(world.admin), json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def assign_template(client, db, world, code: str, **extra_settings) -> None:
    response = await client.post("/api/fieldops/policy-layers", headers=world.auth(world.admin), json={
        "name": "members", "scope_type": "role", "scope_id": await member_role(db, world),
        "settings": {"shift.template": code, **extra_settings}})
    assert response.status_code == 201, response.text


async def hub_at(client, db, world, point=GODHRA, code="HUB-GDR") -> dict:
    shop = await place(db, world, point)
    response = await client.post("/api/hubs", headers=world.auth(world.admin),
                                 json={"code": code, "name": f"{code} Hub", "place_id": shop.id})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def started(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()["data"]


# ── templates ───────────────────────────────────────────────────────────────────

async def test_a_template_is_listed_as_a_virtual_shift_then_materialized_at_start(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    await all_day_template(client, acme)
    await assign_template(client, db, acme, "ALLDAY")

    listed = await client.get("/api/me/shifts", headers=headers(acme, acme.member))
    assert listed.status_code == 200, listed.text
    virtual = [s for s in listed.json()["data"] if s["uuid"] is None]
    assert virtual and virtual[0]["source"] == "template" and virtual[0]["title"] == "All Day"
    assert virtual[0]["template"]["code"] == "ALLDAY" and virtual[0]["work_type"] == "delivery"

    at = now() - dt.timedelta(minutes=20)
    shift = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "occurred": clock(at), "fix": fix(at=at)}))
    assert (shift["source"], shift["title"], shift["work_type"]) == ("template", "All Day", "delivery")
    assert shift["shift_code"].startswith("SH-") and shift["template"]["code"] == "ALLDAY"
    assert shift["planned_end_at"] and shift["auto_close_at"]
    assert shift["start_location"] == {"mode": "anywhere", "hub_id": None, "hub_code": None, "place_uuid": None,
                                       "name": None, "address": None, "latitude": None, "longitude": None,
                                       "radius_m": None, "geofence_uuid": None, "geofence_enforcement": None}
    assert shift["captured_start"]["latitude"] == pytest.approx(GODHRA[0])

    again = await client.get("/api/me/shifts", headers=headers(acme, acme.member))
    assert not [s for s in again.json()["data"] if s["uuid"] is None], "a started occurrence is no longer virtual"


async def test_no_template_and_no_ad_hoc_shifts_is_a_clear_409(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    await client.post("/api/fieldops/policy-layers", headers=acme.auth(acme.admin), json={
        "name": "strict", "settings": {"shift.requirements": {"allow_unscheduled_shifts": False}}})
    refused = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                json={"uuid": str(uuid.uuid4()), "fix": fix()})
    assert refused.status_code == 409 and refused.json()["code"] == "no_shift_available"


async def test_a_template_endpoint_with_enforcement_checks_the_start(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    hub = await hub_at(client, db, acme)
    await all_day_template(client, acme, start={"mode": "hub", "hub_id": hub["id"], "enforcement": "hard_block",
                                                "radius_m": 150})
    await assign_template(client, db, acme, "ALLDAY")
    refused = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                json={"uuid": str(uuid.uuid4()), "fix": fix(FAR)})
    assert refused.status_code == 422 and refused.json()["code"] == "outside_geofence"
    assert await db.scalar(select(func.count()).select_from(Shift)) == 0, "a refused start leaves nothing behind"
    inside = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                       json={"uuid": str(uuid.uuid4()), "fix": fix()}))
    assert inside["start_check"] == "inside" and inside["start_location"]["mode"] == "hub"
    assert inside["start_location"]["radius_m"] == 150 and inside["start_location"]["hub_code"] == "HUB-GDR"


# ── scheduled shifts ────────────────────────────────────────────────────────────

async def test_a_scheduled_shift_with_a_soft_blocked_start_place(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    planned_start = now() - dt.timedelta(minutes=30)
    scheduled = await client.post("/api/fieldops/shifts", headers=acme.auth(acme.admin), json={
        "user_id": acme.member.id, "planned_start_at": planned_start.isoformat(),
        "planned_end_at": (planned_start + dt.timedelta(hours=8)).isoformat(), "title": "Halol route 3",
        "work_type": "delivery",
        "start": {"mode": "place", "latitude": GODHRA[0], "longitude": GODHRA[1], "address": "GIDC Godhra",
                  "name": "Godhra depot", "enforcement": "soft_block", "radius_m": 200},
        "end": {"mode": "place", "latitude": GODHRA[0], "longitude": GODHRA[1]}})
    assert scheduled.status_code == 201, scheduled.text
    plan = scheduled.json()["data"]
    assert (plan["status"], plan["source"], plan["title"]) == ("scheduled", "scheduled", "Halol route 3")
    assert plan["start_location"]["name"] == "Godhra depot" and plan["start_location"]["address"] == "GIDC Godhra"
    assert plan["start_location"]["latitude"] == pytest.approx(GODHRA[0])

    mine = await client.get("/api/me/shifts?upcoming=true", headers=headers(acme, acme.member))
    assert [s["uuid"] for s in mine.json()["data"]] == [plan["uuid"]]

    other = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                              json={"uuid": str(uuid.uuid4()), "fix": fix()})
    assert other.status_code == 409 and other.json()["code"] == "scheduled_shift_exists"
    assert other.json()["data"]["shift_uuid"] == plan["uuid"]

    far = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                            json={"uuid": plan["uuid"], "fix": fix(FAR)})
    assert far.status_code == 422 and far.json()["code"] == "justification_required"
    justified = await client.post("/api/me/shifts", headers=headers(acme, acme.member), json={
        "uuid": plan["uuid"], "fix": fix(FAR), "justification": {"code": "gps_poor", "note": "fog"}})
    assert justified.status_code == 201, justified.text
    shift = justified.json()["data"]
    assert (shift["status"], shift["start_check"], shift["review_status"]) == ("active", "outside", "pending")
    assert shift["start_distance_m"] > 2000
    check = await db.scalar(select(LocationCheck).where(LocationCheck.subject_type == "shift"))
    assert (check.action_taken, check.enforcement) == ("justified", "soft_block")

    ended = await client.post(f"/api/me/shifts/{plan['uuid']}/end", headers=headers(acme, acme.member),
                              json={"fix": fix()})
    assert ended.status_code == 200 and ended.json()["data"]["end_check"] == "inside"


async def test_tomorrows_scheduled_shift_cannot_be_started_today(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    start = now() + dt.timedelta(days=1)
    plan = (await client.post("/api/fieldops/shifts", headers=acme.auth(acme.admin), json={
        "user_id": acme.member.id, "planned_start_at": start.isoformat(),
        "planned_end_at": (start + dt.timedelta(hours=8)).isoformat()})).json()["data"]
    early = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                              json={"uuid": plan["uuid"], "fix": fix()})
    assert early.status_code == 409 and early.json()["code"] == "shift_not_yet_startable"


async def test_overlapping_schedules_are_refused_and_cancel_works(worlds, db):
    client, acme, _ = worlds
    start = now() + dt.timedelta(days=1)
    body = {"user_id": acme.member.id, "planned_start_at": start.isoformat(),
            "planned_end_at": (start + dt.timedelta(hours=8)).isoformat()}
    first = await client.post("/api/fieldops/shifts", headers=acme.auth(acme.admin), json=body)
    assert first.status_code == 201, first.text
    clash = await client.post("/api/fieldops/shifts", headers=acme.auth(acme.admin), json={
        **body, "planned_start_at": (start + dt.timedelta(hours=2)).isoformat()})
    assert clash.status_code == 409 and clash.json()["code"] == "shift_overlaps"
    moved = await client.patch(f"/api/fieldops/shifts/{first.json()['data']['uuid']}/plan",
                               headers=acme.auth(acme.admin), json={"row_version": 1, "title": "Moved"})
    assert moved.status_code == 200 and moved.json()["data"]["title"] == "Moved"
    cancelled = await client.post(f"/api/fieldops/shifts/{first.json()['data']['uuid']}/cancel?reason=holiday",
                                  headers=acme.auth(acme.admin))
    assert cancelled.status_code == 200 and cancelled.json()["data"]["status"] == "cancelled"


async def test_a_member_cannot_schedule_and_another_tenant_is_invisible(worlds):
    client, acme, globex = worlds
    start = now() + dt.timedelta(days=1)
    body = {"user_id": acme.member.id, "planned_start_at": start.isoformat(),
            "planned_end_at": (start + dt.timedelta(hours=8)).isoformat()}
    assert (await client.post("/api/fieldops/shifts", headers=acme.auth(acme.member), json=body)).status_code == 403
    cross = await client.post("/api/fieldops/shifts", headers=globex.auth(globex.admin), json=body)
    assert cross.status_code == 404


async def test_bulk_scheduling_from_a_template_on_a_date(worlds, db):
    client, acme, _ = worlds
    await all_day_template(client, acme, code="DAY")
    tomorrow = (now() + dt.timedelta(days=1)).date()
    response = await client.post("/api/fieldops/shifts/bulk", headers=acme.auth(acme.admin), json={"shifts": [
        {"user_id": acme.member.id, "template": "DAY", "date": tomorrow.isoformat()},
        {"user_id": acme.admin.id, "template": "DAY", "date": tomorrow.isoformat(), "title": "Admin cover"}]})
    assert response.status_code == 201, response.text
    rows = response.json()["data"]
    assert [r["title"] for r in rows] == ["All Day", "Admin cover"] and {r["shift_date"] for r in rows} == {str(tomorrow)}


async def test_a_scheduled_shift_never_started_goes_missed(worlds, db):
    client, acme, _ = worlds
    past = now() - dt.timedelta(hours=10)
    response = await client.post("/api/fieldops/shifts", headers=acme.auth(acme.admin), json={
        "user_id": acme.member.id, "planned_start_at": past.isoformat(),
        "planned_end_at": (past + dt.timedelta(hours=6)).isoformat()})
    assert response.status_code == 201, response.text
    with tenant_scope(acme.tenant.id):
        missed = await shift_service.mark_missed(db)
    assert len(missed) == 1
    row = await db.scalar(select(Shift).where(Shift.uuid == uuid.UUID(response.json()["data"]["uuid"])))
    await db.refresh(row)
    assert row.status == "missed"
    assert await db.scalar(select(Anomaly.anomaly_type).where(Anomaly.shift_id == row.id)) == "missed_shift"


async def test_auto_close_uses_the_stored_cap(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    t0 = now() - dt.timedelta(hours=5)
    shift = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "occurred": clock(t0), "fix": fix(at=t0),
        "planned_end_at": (t0 + dt.timedelta(hours=2)).isoformat()}))
    assert dt.datetime.fromisoformat(shift["auto_close_at"]) == pytest.approx(
        t0 + dt.timedelta(hours=3), abs=dt.timedelta(seconds=5))           # planned end + 60 min grace
    with tenant_scope(acme.tenant.id):
        closed = await shift_service.auto_close_due(db)
    assert len(closed) == 1
    row = await db.scalar(select(Shift).where(Shift.uuid == uuid.UUID(shift["uuid"])))
    await db.refresh(row)
    assert (row.status, row.end_reason) == ("auto_closed", "auto_closed")


# ── the hub of the day ─────────────────────────────────────────────────────────

async def test_hub_assignments_split_by_day_and_drive_assigned_hub(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    near = await hub_at(client, db, acme, GODHRA, code="HUB-NEAR")
    far = await hub_at(client, db, acme, FAR, code="HUB-FAR")
    today = now().date()
    for body in ({"user_id": acme.member.id, "hub_id": far["id"], "valid_from": str(today - dt.timedelta(days=3))},
                 {"user_id": acme.member.id, "hub_id": near["id"], "date": str(today)}):
        saved = await client.post("/api/hubs/assignments", headers=acme.auth(acme.admin), json={"assignments": [body]})
        assert saved.status_code == 201, saved.text
    rows = (await client.get(f"/api/hubs/assignments?user_id={acme.member.id}",
                             headers=acme.auth(acme.admin))).json()["data"]
    assert [(r["hub_id"], r["valid_from"], r["valid_to"]) for r in rows] == [
        (far["id"], str(today - dt.timedelta(days=3)), str(today - dt.timedelta(days=1))),
        (near["id"], str(today), str(today)),
        (far["id"], str(today + dt.timedelta(days=1)), None)]
    mine = await client.get("/api/hubs/me", headers=acme.auth(acme.member))
    assert mine.json()["data"]["hub_id"] == near["id"] and mine.json()["data"]["source"] == "assignment"

    await all_day_template(client, acme, start={"mode": "assigned_hub", "enforcement": "advisory"})
    await assign_template(client, db, acme, "ALLDAY")
    shift = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                      json={"uuid": str(uuid.uuid4()), "fix": fix()}))
    assert shift["hub"]["code"] == "HUB-NEAR" and shift["start_location"]["hub_code"] == "HUB-NEAR"
    assert shift["start_check"] == "inside"


async def test_assigned_hub_with_no_hub_that_day_is_anywhere_plus_an_anomaly(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    await all_day_template(client, acme, start={"mode": "assigned_hub", "enforcement": "hard_block"})
    await assign_template(client, db, acme, "ALLDAY")
    shift = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                      json={"uuid": str(uuid.uuid4()), "fix": fix(FAR)}))
    assert shift["start_location"]["mode"] == "anywhere" and shift["start_check"] == "not_configured"
    assert await db.scalar(select(Anomaly.anomaly_type).where(Anomaly.anomaly_type == "no_hub_assigned"))


# ── stops ───────────────────────────────────────────────────────────────────────

async def test_stops_fence_pack_and_a_planned_visit_start(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    planned_start = now() - dt.timedelta(minutes=10)
    plan = (await client.post("/api/fieldops/shifts", headers=acme.auth(acme.admin), json={
        "user_id": acme.member.id, "planned_start_at": planned_start.isoformat(),
        "planned_end_at": (planned_start + dt.timedelta(hours=8)).isoformat(), "work_type": "delivery"})).json()["data"]
    stops = await client.post(f"/api/fieldops/shifts/{plan['uuid']}/stops", headers=acme.auth(acme.admin), json={
        "stops": [{"latitude": GODHRA[0], "longitude": GODHRA[1], "name": "Shree Medical", "stop_code": "INV-001"},
                  {"latitude": FAR[0], "longitude": FAR[1], "name": "Far Pharmacy", "stop_code": "INV-002"}]})
    assert stops.status_code == 201, stops.text
    first_stop = stops.json()["data"][0]["uuid"]

    early = await client.post(f"/api/me/visits/{first_stop}/start", headers=headers(acme, acme.member),
                              json={"fix": fix()})
    assert early.status_code == 409 and early.json()["code"] == "shift_not_active"

    detail = await client.get(f"/api/me/shifts/{plan['uuid']}", headers=headers(acme, acme.member))
    assert detail.status_code == 200, detail.text
    body = detail.json()["data"]
    assert [s["stop_code"] for s in body["stops"]] == ["INV-001", "INV-002"]
    assert body["shift"]["stops_total"] == 2 and len(body["fences"]) == 2
    assert {f["kind"] for f in body["fences"]} == {"stop"}

    started(await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                              json={"uuid": plan["uuid"], "fix": fix()}))
    visit = await client.post(f"/api/me/visits/{first_stop}/start", headers=headers(acme, acme.member),
                              json={"fix": fix()})
    assert visit.status_code == 201, visit.text
    assert (visit.json()["data"]["status"], visit.json()["data"]["start_check"]) == ("in_progress", "inside")
    replay = await client.post(f"/api/me/visits/{first_stop}/start", headers=headers(acme, acme.member),
                               json={"fix": fix()})
    assert replay.status_code == 200
    ended = await client.post(f"/api/me/visits/{first_stop}/end", headers=headers(acme, acme.member),
                              json={"fix": fix(), "outcome": "delivered"})
    assert ended.status_code == 200, ended.text
    card = (await client.get(f"/api/me/shifts/{plan['uuid']}", headers=headers(acme, acme.member))).json()["data"]
    assert card["shift"]["stops_completed"] == 1


# ── mock policy, silence, handover ──────────────────────────────────────────────

async def test_mock_location_policy_on_actions_and_ambient_fixes(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    layer = await client.post("/api/fieldops/policy-layers", headers=acme.auth(acme.admin), json={
        "name": "strict mock", "settings": {"security.mock_location_action": "reject_and_alert"}})
    assert layer.status_code == 201, layer.text
    refused = await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                json={"uuid": str(uuid.uuid4()), "fix": fix(is_mock=True)})
    assert refused.status_code == 422 and refused.json()["code"] == "mock_location_rejected"

    await client.patch(f"/api/fieldops/policy-layers/{layer.json()['data']['layer']['uuid']}",
                       headers=acme.auth(acme.admin),
                       json={"row_version": 1, "settings": {"security.mock_location_action": "end_shift"}})
    shift = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member),
                                      json={"uuid": str(uuid.uuid4()), "fix": fix()}))
    pinged = await client.post("/api/me/location-pings", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "pings": [{**fix(is_mock=True), "shift_uuid": shift["uuid"]}]})
    assert pinged.status_code == 200 and pinged.json()["data"]["accepted"] == 1    # stored as evidence
    row = await db.scalar(select(Shift).where(Shift.uuid == uuid.UUID(shift["uuid"])))
    await db.refresh(row)
    assert (row.status, row.end_reason) == ("auto_closed", "policy_violation")
    assert await db.scalar(select(Anomaly.severity).where(Anomaly.anomaly_type == "mock_location")) == "critical"


async def test_a_silent_shift_raises_tracking_silent_once(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    t0 = now() - dt.timedelta(hours=2)
    shift = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "occurred": clock(t0), "fix": fix(at=t0)}))
    with tenant_scope(acme.tenant.id):
        assert await shift_service.detect_silent(db) == 1
        assert await shift_service.detect_silent(db) == 0                     # same silent stretch: once
    assert await db.scalar(select(Anomaly.anomaly_type).where(Anomaly.anomaly_type == "tracking_silent"))
    assert shift["uuid"]


async def test_handover_moves_the_open_shift_to_a_new_device(worlds, db):
    client, acme, _ = worlds
    await consent(db, acme, acme.member)

    async def device(installation: str) -> uuid.UUID:
        response = await client.post("/api/me/devices", headers=headers(acme, acme.member), json={
            "installation_id": installation, "platform": "android",
            "session": {"uuid": str(uuid.uuid4()), "location_permission": "always"}})
        assert response.status_code == 200, response.text
        return uuid.UUID(response.json()["data"]["session"]["uuid"])

    phone_a, phone_b = await device("install-AAAAAAAA"), await device("install-BBBBBBBB")
    shift = started(await client.post("/api/me/shifts", headers=headers(acme, acme.member, session=phone_a),
                                      json={"uuid": str(uuid.uuid4()), "fix": fix()}))
    moved = await client.post(f"/api/me/shifts/{shift['uuid']}/handover",
                              headers=headers(acme, acme.member, session=phone_b), json={})
    assert moved.status_code == 200, moved.text
    assert moved.json()["data"]["device_id"] != shift["device_id"]
    assert await db.scalar(select(Anomaly.anomaly_type).where(Anomaly.anomaly_type == "device_handover"))


# ── the company seed ────────────────────────────────────────────────────────────

async def test_the_seed_creates_the_work_shift_and_layers_once(worlds, db):
    from app.modules.fieldops.seed import seed_fieldops_defaults

    client, acme, _ = worlds
    first = await seed_fieldops_defaults(db, tenant_code="ACME", timezone=IST)
    assert (first["template"], first["default_layer"], first["member_layer"]) == (True, True, True)
    second = await seed_fieldops_defaults(db, tenant_code="ACME", timezone=IST)
    assert (second["template"], second["default_layer"], second["member_layer"]) == (False, False, False)
    template = await db.scalar(select(ShiftTemplate).where(ShiftTemplate.code == "WORK_SHIFT"))
    assert (template.name, template.timezone, template.start_local_time, template.end_local_time) == \
        ("Work Shift", IST, dt.time(9), dt.time(21))
    assert (template.start_mode, template.end_mode, template.start_enforcement) == ("anywhere", "anywhere", None)
    assert await db.scalar(select(func.count()).select_from(PolicyLayer)) == 2
    await db.commit()
    explain = await client.get(f"/api/fieldops/policies/resolve?user_id={acme.member.id}",
                               headers=acme.auth(acme.admin))
    values = explain.json()["data"]["values"]
    assert values["shift.template"] == "WORK_SHIFT" and values["session.field"]["field_max_sessions"] == 1
    assert values["tracking.intervals"]["ping_interval_s"] == 45


async def test_a_branch_admin_cannot_move_another_branchs_user(tree_world, db):
    client, w = tree_world
    from app.modules.geo.model import Place
    from geoalchemy2 import WKTElement

    with tenant_scope(w.tenant.id, w.branch_b.id):
        spot = Place(kind="hub", location_name="B hub", organization_id=w.branch_b.id,
                     coordinates=WKTElement(f"POINT({GODHRA[1]} {GODHRA[0]})", srid=4326))
        db.add(spot)
        await db.flush()
    await db.commit()
    hub = await client.post("/api/hubs", headers=w.auth(w.admin_b, w.branch_b),
                            json={"code": "HUB-B", "name": "B hub", "place_id": spot.id})
    assert hub.status_code == 201, hub.text
    body = {"assignments": [{"user_id": w.member_a.id, "hub_id": hub.json()["data"]["id"], "date": str(now().date())}]}
    refused = await client.post("/api/hubs/assignments", headers=w.auth(w.admin_b, w.branch_b), json=body)
    assert refused.status_code == 403
    allowed = await client.post("/api/hubs/assignments", headers=w.auth(w.admin_a, w.branch_a), json=body)
    assert allowed.status_code == 201, allowed.text
    hidden = await client.get(f"/api/hubs/assignments?user_id={w.member_a.id}", headers=w.auth(w.admin_b, w.branch_b))
    assert hidden.status_code == 200 and hidden.json()["data"] == []
