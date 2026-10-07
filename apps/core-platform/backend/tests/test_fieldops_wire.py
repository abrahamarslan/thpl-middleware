"""The inbound ping mapper (``fieldops/wire.py``) — PURE, table-driven, using the Android team's own
payload examples (docs/fieldops/android-contract.md) — plus the ingest through the API."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from app.modules.fieldops.schema import PingIn
from app.modules.fieldops.wire import WireError, normalize, owner_ids

SHIFT = "0190a0b0-0000-7000-8000-00000000b001"
STOP = "0190a0b0-0000-7000-8000-00000000e001"
FENCE = "0190a0b0-0000-7000-8000-00000000f001"


def android(**over) -> dict:
    """The guide's 'geofence enter' example, with UUID ids (shift/stop/fence ids are the server's uuids)."""
    base = {
        "ping_id": "018f2b3e-8b52-7d03-ad4f-5c7b2a1e3f22", "da_id": "DA-4821", "shift_id": SHIFT, "stop_id": STOP,
        "capture_reason": "geofence_enter", "captured_at": "2026-08-14T05:41:03.000Z",
        "elapsed_realtime_ns": 123456901234567, "received_at": "2026-08-14T05:41:04.220Z",
        "latitude": 21.7702, "longitude": 70.6188, "accuracy": 22.1, "bearing": None, "speed": 0.4,
        "provider": "fused", "is_mock_location": False, "battery_pct": 61, "battery_state": "discharging",
        "network_type": "4g", "activity_type": "still", "activity_confidence": 78, "app_state": "background",
        "geofence_event": {"geofence_id": FENCE, "type": "enter"}, "is_significant": True,
        "distance_from_last_m": 44.2, "device_model": "Samsung Galaxy M14", "os_version": "14", "app_version_code": 132,
    }
    base.update(over)
    return base


OWNER = owner_ids(SimpleNamespace(id=7, uuid="u-7", username="ravi"), ["DA-4821"])


def test_the_android_geofence_example_maps_field_by_field():
    out = normalize(android(), owners=OWNER)
    assert out["uuid"] == "018f2b3e-8b52-7d03-ad4f-5c7b2a1e3f22"
    assert out["client_timestamp"] == "2026-08-14T05:41:03.000Z"
    assert out["elapsed_realtime_ms"] == 123456901                    # ns → ms
    assert (out["accuracy_m"], out["speed_mps"], out["is_mock"]) == (22.1, 0.4, False)
    assert (out["shift_uuid"], out["visit_uuid"], out["geofence_uuid"]) == (SHIFT, STOP, FENCE)
    assert (out["kind"], out["checkpoint_label"]) == ("checkpoint", "geofence_enter")
    assert (out["client_significant"], out["client_distance_m"]) == (True, 44.2)
    for dropped in ("received_at", "device_model", "os_version", "app_version_code", "da_id"):
        assert dropped not in out
    item = PingIn.model_validate(out)
    assert item.battery_state.value == "discharging" and item.app_state.value == "background"


@pytest.mark.parametrize(("reason", "kind", "label"), [
    ("interval", "continuous", None), ("shift_start", "checkpoint", "shift_start"),
    ("shift_end", "checkpoint", "shift_end"), ("start_delivery", "checkpoint", "visit_start"),
    ("end_delivery", "checkpoint", "visit_end"), ("geofence_exit", "checkpoint", "geofence_exit"),
])
def test_capture_reasons(reason, kind, label):
    event = {"geofence_id": FENCE, "type": reason.split("_")[1]} if reason.startswith("geofence") else None
    out = normalize(android(capture_reason=reason, geofence_event=event), owners=OWNER)
    assert out["kind"] == kind and out.get("checkpoint_label") == label


def test_the_room_entity_in_camel_case_is_refused_with_its_field_names():
    room = {"pingId": "x", "daId": "DA-4821", "captureReason": "geofence_enter", "capturedAtEpochMs": 17860370863000,
            "syncStatus": "SYNCED", "syncAttempts": 0, "latitude": 21.7, "longitude": 70.6, "ping_id": "x"}
    with pytest.raises(WireError) as caught:
        normalize(room, owners=None)
    assert "syncStatus" in str(caught.value) and "capturedAtEpochMs" in str(caught.value)


def test_a_fix_of_another_user_is_refused():
    with pytest.raises(WireError, match="user_mismatch"):
        normalize(android(da_id="DA-9999"), owners=OWNER)


def test_epoch_millis_and_bearing_and_network_are_normalized():
    out = normalize(android(captured_at=1786037086300, bearing=360.0, network_type="LTE", capture_reason="interval",
                            geofence_event=None), owners=OWNER)
    assert out["client_timestamp"].startswith("2026-08-0")
    assert out["heading_deg"] == 0.0 and out["network_type"] == "unknown"


def test_geofence_event_must_agree_with_the_reason():
    with pytest.raises(WireError, match="contradicts"):
        normalize(android(geofence_event={"geofence_id": FENCE, "type": "exit"}), owners=OWNER)
    with pytest.raises(WireError, match="needs geofence_event"):
        normalize(android(geofence_event=None), owners=OWNER)


def test_the_native_shape_passes_through():
    native = {"uuid": str(uuid.uuid4()), "latitude": 1.0, "longitude": 2.0, "accuracy_m": 5, "kind": "continuous"}
    assert normalize(native, owners=None) == native


# ── through the API ─────────────────────────────────────────────────────────────

async def test_android_pings_are_ingested_with_their_new_columns(worlds, db):
    from sqlalchemy import select

    from app.modules.fieldops.model import LocationPing
    from tests.test_fieldops_api import consent, headers, start_shift

    client, acme, _ = worlds
    await consent(db, acme, acme.member)
    shift = await start_shift(client, acme, acme.member, at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30))
    now = dt.datetime.now(dt.UTC)
    ambient = android(ping_id=str(uuid.uuid4()), shift_id=shift["uuid"], stop_id=None, capture_reason="interval",
                      geofence_event=None, captured_at=(now - dt.timedelta(minutes=2)).isoformat(),
                      da_id=str(acme.member.id), latitude=22.7772, longitude=73.6203)
    camel = {"pingId": "y", "syncStatus": "SYNCED", "ping_id": str(uuid.uuid4())}
    stranger = android(ping_id=str(uuid.uuid4()), da_id="someone-else", capture_reason="interval",
                       geofence_event=None, shift_id=shift["uuid"], stop_id=None)
    response = await client.post("/api/me/location-pings", headers=headers(acme, acme.member), json={
        "uuid": str(uuid.uuid4()), "pings": [ambient, camel, stranger, {"latitude": 1}]})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["accepted"], data["rejected"]) == (1, 3)
    reasons = {r["uuid"]: r["reason"] for r in data["results"]}
    assert "unknown fields" in reasons[camel["ping_id"]] and "user_mismatch" in reasons[stranger["ping_id"]]
    assert None in reasons, "an item with no id is reported with uuid null, not the string 'None'"
    row = await db.scalar(select(LocationPing).where(LocationPing.uuid == uuid.UUID(ambient["ping_id"])))
    assert (row.app_state, row.battery_state, row.is_charging, row.client_distance_m) == \
        ("background", "discharging", False, pytest.approx(44.2))
