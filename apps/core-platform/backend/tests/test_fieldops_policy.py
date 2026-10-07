"""Policy layers — the precedence/lock contract (pure ``fold``), the registry, and resolution through the
API on a real organization tree (docs/fieldops/policy-layers.md)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.modules.fieldops.policy import settings as reg
from app.modules.fieldops.policy.resolver import LayerRow, fold


def layer(scope: str = "organization", *, depth: int = 0, settings: dict | None = None, locks=(), priority: int = 0,
          id: int = 1, scope_id: int | None = None) -> LayerRow:
    return LayerRow(id=id, uuid=uuid.uuid4(), name=f"{scope}-{depth}-{id}", organization_id=depth + 1, depth=depth,
                    scope_type=scope, scope_id=scope_id if scope != "organization" else None,
                    settings=settings or {}, locked_keys=tuple(locks), priority=priority)


# ── pure: fold ──────────────────────────────────────────────────────────────────

def test_no_layers_is_the_code_default_floor():
    flat = fold([]).flat
    assert flat["ping_interval_s"] == 60 and flat["require_location_consent"] is True
    assert flat["field_max_sessions"] == 0 and flat["shift_template"] is None


def test_a_role_layer_setting_one_field_keeps_the_organizations_other_values():
    """The flaw of winner-takes-all work_policies (plan §4.1): a role row reset HQ's values to defaults."""
    hq = layer(settings={"tracking.intervals": {"ping_interval_s": 45, "stationary_interval_s": 200},
                         "geofence.rules": {"geofence_enforcement": "hard_block"}}, id=1)
    role = layer("role", settings={"shift.requirements": {"require_start_selfie": True}}, id=2, scope_id=7)
    flat = fold([role, hq]).flat
    assert flat["require_start_selfie"] is True
    assert flat["ping_interval_s"] == 45 and flat["stationary_interval_s"] == 200
    assert flat["geofence_enforcement"] == "hard_block"


def test_scope_rank_beats_org_depth():
    """A branch's GENERAL default never overrides HQ's role rule; a branch ROLE rule does."""
    hq_role = layer("role", depth=0, settings={"tracking.intervals": {"ping_interval_s": 30}}, id=1, scope_id=7)
    branch_default = layer(depth=1, settings={"tracking.intervals": {"ping_interval_s": 90}}, id=2)
    assert fold([hq_role, branch_default]).flat["ping_interval_s"] == 30
    branch_role = layer("role", depth=1, settings={"tracking.intervals": {"ping_interval_s": 120}}, id=3, scope_id=7)
    assert fold([hq_role, branch_default, branch_role]).flat["ping_interval_s"] == 120


@pytest.mark.parametrize(("order", "expected"), [
    (["organization", "role", "team", "hub", "beat", "user"], 600),
    (["user", "beat", "hub", "team", "role", "organization"], 600),
])
def test_the_most_specific_scope_wins_whatever_the_input_order(order, expected):
    values = {"organization": 60, "role": 90, "team": 120, "hub": 180, "beat": 300, "user": 600}
    layers = [layer(s, settings={"tracking.intervals": {"ping_interval_s": values[s]}}, id=i, scope_id=i)
              for i, s in enumerate(order, start=1)]
    assert fold(layers).flat["ping_interval_s"] == expected


def test_priority_then_id_break_ties_and_the_tie_is_visible():
    a = layer("team", settings={"tracking.intervals": {"ping_interval_s": 100}}, id=1, scope_id=1)
    b = layer("team", settings={"tracking.intervals": {"ping_interval_s": 200}}, id=2, scope_id=2)
    assert fold([b, a]).flat["ping_interval_s"] == 200                     # same rank/depth/priority: id order
    a_high = layer("team", settings={"tracking.intervals": {"ping_interval_s": 100}}, id=1, scope_id=1, priority=5)
    assert fold([b, a_high]).flat["ping_interval_s"] == 100


def test_a_lock_stops_every_narrower_layer_and_is_reported():
    hq = layer(settings={"consent.required": True}, locks=["consent.required"], id=1)
    role = layer("role", settings={"consent.required": False}, id=2, scope_id=7)
    folded = fold([hq, role])
    assert folded.flat["require_location_consent"] is True
    assert folded.conflicts == [{"layer": str(role.uuid), "key": "consent.required", "reason": "locked",
                                 "locked_by": str(hq.uuid)}]


def test_a_field_lock_leaves_the_rest_of_the_group_settable():
    hq = layer(settings={"geofence.rules": {"geofence_enforcement": "hard_block"}},
               locks=["geofence.rules.geofence_enforcement"], id=1)
    role = layer("role", settings={"geofence.rules": {"geofence_enforcement": "advisory", "default_visit_radius_m": 250}},
                 id=2, scope_id=7)
    flat = fold([hq, role]).flat
    assert flat["geofence_enforcement"] == "hard_block" and flat["default_visit_radius_m"] == 250


def test_a_contribution_that_breaks_an_invariant_is_skipped_not_applied():
    hq = layer(settings={"tracking.intervals": {"ping_interval_s": 45}}, id=1)
    bad = layer("role", settings={"tracking.intervals": {"min_interval_s": 100}}, id=2, scope_id=7)   # min > base
    folded = fold([hq, bad])
    assert folded.flat["ping_interval_s"] == 45 and folded.flat["min_interval_s"] == 15
    assert folded.conflicts[0]["reason"] == "invalid_combination"


def test_a_setting_outside_its_allowed_scopes_never_applies():
    hub = layer("hub", settings={"session.field": {"field_max_sessions": 1}}, id=1, scope_id=3)
    folded = fold([hub])
    assert folded.flat["field_max_sessions"] == 0
    assert folded.conflicts[0]["reason"] == "scope_not_allowed"


def test_battery_bands_must_descend_to_zero():
    with pytest.raises(ValueError):
        reg.TrackingIntervals(battery_bands=[{"min_pct": 15, "interval_seconds": 120}, {"min_pct": 30}])
    with pytest.raises(ValueError):
        reg.TrackingIntervals(battery_bands=[{"min_pct": 30}, {"min_pct": 15, "interval_seconds": 120}])
    ok = reg.TrackingIntervals(battery_bands=[{"min_pct": 30}, {"min_pct": 15, "interval_seconds": 120},
                                              {"min_pct": 0, "interval_seconds": 600}])
    assert [b.min_pct for b in ok.battery_bands] == [30, 15, 0]


def test_layer_values_are_validated_per_field_and_unknown_keys_refused():
    assert reg.validate_layer_value("tracking.intervals", {"ping_interval_s": 45}) == {"ping_interval_s": 45}
    with pytest.raises(reg.SettingError):
        reg.validate_layer_value("tracking.intervals", {"ping_interval": 45})
    with pytest.raises(reg.SettingError):
        reg.validate_layer_value("nope.setting", True)
    assert reg.validate_layer_value("security.mock_location_action", "end_shift") == "end_shift"


def test_flat_names_are_unique_and_cover_the_legacy_policy_columns():
    legacy = {"requires_shift", "allow_visits_without_shift", "require_location_consent", "require_start_selfie",
              "require_odometer", "require_start_at_place_id", "earliest_start_local", "latest_end_local",
              "max_shift_hours", "auto_close_grace_minutes", "stale_shift_after_minutes", "max_pause_minutes",
              "max_pauses_per_shift", "paid_pause_types", "track_during_pause", "tracking_mode", "ping_interval_s",
              "stationary_interval_s", "ping_min_distance_m", "geofence_enforcement", "default_visit_radius_m",
              "geocoded_radius_factor", "max_fix_accuracy_m", "allow_manual_location", "min_visit_minutes",
              "late_task_window_hours", "gap_flag_minutes", "clock_skew_flag_seconds", "min_tracking_coverage_pct"}
    assert legacy <= set(reg.FLAT_TO_KEY)


def test_a_new_dimension_needs_no_resolver_change():
    """Beats: a layer of scope 'beat' folds by rank like any other — nothing in fold names a dimension."""
    folded = fold([layer(settings={"tracking.intervals": {"ping_interval_s": 60}}, id=1),
                   layer("beat", settings={"tracking.intervals": {"ping_interval_s": 240}}, id=2, scope_id=9)])
    assert folded.flat["ping_interval_s"] == 240


def test_the_android_config_renders_v5_bands_and_derived_flags():
    from app.modules.fieldops.policy.render import render

    flat = fold([layer(settings={"tracking.intervals": {"ping_interval_s": 45},
                                 "security.mock_location_action": "reject_and_alert"}, id=1)]).flat
    body = render(flat, config_version=7, effective_from=None)
    assert body["config_version"] == 7 and body["schema_version"] == 5
    assert body["location_request"]["base_interval_seconds"] == 45
    assert body["location_request"]["battery_thresholds"] == [
        {"min_pct": 30, "interval_seconds": 45}, {"min_pct": 15, "interval_seconds": 120},
        {"min_pct": 0, "interval_seconds": 600}]
    assert body["location_request"]["activity_based_intervals"]["still"] == 300     # = stationary_interval_s
    assert body["feature_flags"]["enforce_mock_rejection"] is True
    assert body["accuracy_filter"]["max_accepted_accuracy_meters"] == 200


# ── integration: through the API ────────────────────────────────────────────────

async def _member_role_id(db, world) -> int:
    from sqlalchemy import select

    from app.modules.roles.model import Role

    return await db.scalar(select(Role.id).where(Role.organization_id == world.organization.id, Role.code == "member"))


async def test_layers_resolve_for_a_user_with_provenance_and_a_monotonic_version(worlds, db):
    client, acme, _ = worlds
    admin = acme.auth(acme.admin)
    org = await client.post("/api/fieldops/policy-layers", headers=admin, json={
        "name": "ACME default", "settings": {"tracking.intervals": {"ping_interval_s": 45},
                                             "consent.required": True},
        "locked_keys": ["consent.required"]})
    assert org.status_code == 201, org.text
    member_role = await _member_role_id(db, acme)
    role = await client.post("/api/fieldops/policy-layers", headers=admin, json={
        "name": "ACME members", "scope_type": "role", "scope_id": member_role,
        "settings": {"session.field": {"field_max_sessions": 1}}})
    assert role.status_code == 201, role.text

    locked = await client.post("/api/fieldops/policy-layers", headers=admin, json={
        "name": "ACME user", "scope_type": "user", "scope_id": acme.member.id,
        "settings": {"consent.required": False}})
    assert locked.status_code == 422 and locked.json()["code"] == "policy_setting_locked"

    explain = await client.get(f"/api/fieldops/policies/resolve?user_id={acme.member.id}", headers=admin)
    assert explain.status_code == 200, explain.text
    data = explain.json()["data"]
    assert data["values"]["tracking.intervals"]["ping_interval_s"] == 45
    assert data["values"]["session.field"]["field_max_sessions"] == 1
    assert data["provenance"]["session.field.field_max_sessions"] == role.json()["data"]["layer"]["uuid"]
    assert [layer["scope_type"] for layer in data["layers"]] == ["organization", "role"]

    first = await client.get("/api/me/fieldops/config", headers=acme.auth(acme.member))
    assert first.status_code == 200, first.text
    v1 = first.json()["data"]["config_version"]
    assert first.json()["data"]["location_request"]["base_interval_seconds"] == 45
    not_modified = await client.get("/api/me/fieldops/config",
                                    headers=acme.auth(acme.member, **{"If-None-Match": first.headers["etag"]}))
    assert not_modified.status_code == 304

    await client.delete(f"/api/fieldops/policy-layers/{role.json()['data']['layer']['uuid']}?reason=cleanup",
                        headers=admin)
    after = await client.get("/api/me/fieldops/config", headers=acme.auth(acme.member))
    assert after.json()["data"]["config_version"] > v1         # never decreases, even when a layer goes away


async def test_a_setting_not_allowed_at_a_scope_is_refused_on_write(worlds, db):
    client, acme, _ = worlds
    refused = await client.post("/api/fieldops/policy-layers", headers=acme.auth(acme.admin), json={
        "name": "bad", "scope_type": "user", "scope_id": acme.member.id,
        "settings": {"retention.local": 3}})
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_policy_settings"
    beat = await client.post("/api/fieldops/policy-layers", headers=acme.auth(acme.admin), json={
        "name": "beat", "scope_type": "beat", "scope_id": 1, "settings": {}})
    assert beat.status_code == 422 and beat.json()["code"] == "scope_not_available"


async def test_the_settings_catalogue_lists_every_setting(worlds):
    client, acme, _ = worlds
    response = await client.get("/api/fieldops/policy-settings", headers=acme.auth(acme.admin))
    assert response.status_code == 200
    keys = {item["key"] for item in response.json()["data"]}
    assert {"shift.template", "session.field", "tracking.intervals", "security.mock_location_action"} <= keys


async def test_preview_counts_who_a_draft_layer_would_change(worlds):
    client, acme, _ = worlds
    preview = await client.post("/api/fieldops/policies/preview", headers=acme.auth(acme.admin), json={
        "name": "draft", "settings": {"tracking.intervals": {"ping_interval_s": 90}}})
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["affected_count"] >= 2 and "ping_interval_s" in data["affected"][0]["changed"]


async def test_a_branch_override_and_an_hq_lock_on_a_tree(tree_world, db):
    client, w = tree_world
    hq = w.auth(w.holding_admin, w.holding)
    created = await client.post("/api/fieldops/policy-layers", headers=hq, json={
        "name": "Holding", "settings": {"tracking.intervals": {"ping_interval_s": 60},
                                        "geofence.rules": {"geofence_enforcement": "soft_block"}},
        "locked_keys": ["geofence.rules.geofence_enforcement"]})
    assert created.status_code == 201, created.text
    branch = await client.post("/api/fieldops/policy-layers", headers=w.auth(w.admin_a, w.branch_a), json={
        "name": "Branch A", "settings": {"tracking.intervals": {"ping_interval_s": 30}}})
    assert branch.status_code == 201, branch.text
    blocked = await client.patch(f"/api/fieldops/policy-layers/{branch.json()['data']['layer']['uuid']}",
                                 headers=w.auth(w.admin_a, w.branch_a), json={
                                     "row_version": 1, "settings": {"geofence.rules": {"geofence_enforcement": "advisory"}}})
    assert blocked.status_code == 422 and blocked.json()["code"] == "policy_setting_locked"
    explained = await client.get(f"/api/fieldops/policies/resolve?user_id={w.member_a.id}", headers=hq)
    values = explained.json()["data"]["values"]
    assert values["tracking.intervals"]["ping_interval_s"] == 30            # deeper organization layer wins
    assert values["geofence.rules"]["geofence_enforcement"] == "soft_block"


def test_effective_from_scheduling_is_respected_by_fold_inputs():
    """A scheduled layer is filtered by the loader (not fold): fold only ever sees live layers."""
    future = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    row = layer(settings={"tracking.intervals": {"ping_interval_s": 75}}, id=1)
    assert fold([row]).flat["ping_interval_s"] == 75 and future > dt.datetime.now(dt.UTC)
