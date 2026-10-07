"""Sign-in sessions (single field-app session per role, logout, refresh rotation, drain grant), the consent
API, and privacy settings enforcement — through the real API (docs/auth/sessions.md,
docs/compliance/consents.md, docs/users/privacy-settings.md)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.database.tenancy import tenant_scope
from app.modules.users.model import User
from app.modules.users.security import hash_password
from tests.test_fieldops_api import fix, now

PASSWORD = "Fieldwork#2026"


async def field_user(db, world, email="da@acme.example") -> User:
    """A member who can sign in with a password (the worlds' users carry a placeholder hash)."""
    with tenant_scope(world.tenant.id, world.organization.id):
        user = await db.scalar(select(User).where(User.id == world.member.id))
        user.email = email
        user.password = hash_password(PASSWORD)
        await db.flush()
    await db.commit()
    return user


async def login(client, email="da@acme.example", *, client_type="field_app", installation="install-A") -> dict:
    response = await client.post("/api/auth/login", json={
        "identifier": email, "password": PASSWORD, "client_type": client_type, "installation_id": installation,
        "device_type": "android" if client_type == "field_app" else "web"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def bearer(tokens: dict, **extra) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}", **extra}


async def single_session(client, db, world, *, on_new="revoke_previous") -> None:
    from app.modules.roles.model import Role

    role = await db.scalar(select(Role.id).where(Role.organization_id == world.organization.id, Role.code == "member"))
    response = await client.post("/api/fieldops/policy-layers", headers=world.auth(world.admin), json={
        "name": "one device", "scope_type": "role", "scope_id": role,
        "settings": {"session.field": {"field_max_sessions": 1, "field_on_new_login": on_new}}})
    assert response.status_code == 201, response.text


# ── sessions ────────────────────────────────────────────────────────────────────

async def test_device_b_signs_device_a_out(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    await single_session(client, db, acme)
    a = await login(client, installation="install-A")
    assert (await client.get("/api/auth/me", headers=bearer(a))).status_code == 200
    b = await login(client, installation="install-B")
    assert b["displaced_sessions"] == 1 and b["session_uuid"] != a["session_uuid"]

    refused = await client.get("/api/auth/me", headers=bearer(a))
    assert refused.status_code == 401
    body = refused.json()
    assert body["code"] == "session_revoked" and body["data"]["reason"] == "signed_in_elsewhere"
    assert body["data"]["drain_until"], "a displaced field session gets a telemetry-drain grant"
    assert (await client.get("/api/auth/me", headers=bearer(b))).status_code == 200

    # The drain grant: A may still upload what it queued BEFORE it was signed out — nothing else.
    before = fix(at=now() - dt.timedelta(minutes=5))
    after = fix(at=now() + dt.timedelta(minutes=1))
    drained = await client.post("/api/me/location-pings", headers=bearer(a), json={
        "uuid": str(uuid.uuid4()), "pings": [before, after]})
    assert drained.status_code == 200, drained.text
    data = drained.json()["data"]
    assert (data["accepted"], data["rejected"]) == (1, 1)
    assert "session_revoked" in data["results"][0]["reason"]
    assert (await client.get("/api/me/shifts", headers=bearer(a))).status_code == 401


async def test_web_sessions_are_not_limited_by_the_field_rule(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    await single_session(client, db, acme)
    one = await login(client, client_type="web")
    two = await login(client, client_type="web")
    assert two["displaced_sessions"] == 0
    assert (await client.get("/api/auth/me", headers=bearer(one))).status_code == 200


async def test_refuse_mode_answers_409_with_the_other_device(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    await single_session(client, db, acme, on_new="refuse")
    await login(client, installation="install-A")
    second = await client.post("/api/auth/login", json={
        "identifier": "da@acme.example", "password": PASSWORD, "client_type": "field_app"})
    assert second.status_code == 409 and second.json()["code"] == "active_session_exists"


async def test_without_a_layer_the_deployment_fallback_applies(worlds, db, monkeypatch):
    from app.core.conf import settings

    client, acme, _ = worlds
    await field_user(db, acme)
    monkeypatch.setattr(settings, "FIELD_MAX_SESSIONS", 0)
    a = await login(client)
    await login(client, installation="install-B")
    assert (await client.get("/api/auth/me", headers=bearer(a))).status_code == 200      # unlimited
    monkeypatch.setattr(settings, "FIELD_MAX_SESSIONS", 1)
    await login(client, installation="install-C")
    assert (await client.get("/api/auth/me", headers=bearer(a))).status_code == 401


async def test_logout_revokes_the_token_and_logout_all_every_device(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    a = await login(client, client_type="web")
    b = await login(client, client_type="web")
    out = await client.post("/api/auth/logout", headers=bearer(a))
    assert out.status_code == 200 and out.json()["data"]["sessions_revoked"] == 1
    after = await client.get("/api/auth/me", headers=bearer(a))
    assert after.status_code == 401 and after.json()["data"]["reason"] == "logout"
    assert (await client.get("/api/auth/me", headers=bearer(b))).status_code == 200
    await client.post("/api/auth/logout-all", headers=bearer(b))
    assert (await client.get("/api/auth/me", headers=bearer(b))).status_code == 401


async def _age_rotation(db, session_uuid: str, seconds: int = 120) -> None:
    from sqlalchemy import text

    await db.execute(text("UPDATE auth.user_sessions SET updated_at = now() - make_interval(secs => :s) "
                          "WHERE uuid = :u"), {"s": seconds, "u": session_uuid})
    await db.commit()


async def test_refresh_rotates_and_reuse_kills_the_session(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    first = await login(client, client_type="web")
    second = await client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200, second.text
    rotated = second.json()["data"]
    assert rotated["session_uuid"] == first["session_uuid"] and rotated["refresh_token"] != first["refresh_token"]
    await _age_rotation(db, first["session_uuid"])          # well past the 30 s race window
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401 and reuse.json()["data"]["reason"] == "refresh_reuse"
    assert (await client.get("/api/auth/me", headers=bearer(rotated))).status_code == 401


async def test_two_refreshes_racing_from_one_app_do_not_log_it_out(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    first = await login(client, client_type="web")
    a = await client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
    b = await client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})   # the race
    assert a.status_code == 200 and b.status_code == 200, b.text
    assert (await client.get("/api/auth/me", headers=bearer(b.json()["data"]))).status_code == 200


async def test_a_drained_fix_cannot_be_backdated_past_the_sign_out(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    await single_session(client, db, acme)
    a = await login(client, installation="install-A")
    await login(client, installation="install-B")
    # The device claims the fix was 10 minutes ago, but its monotonic clock says "just now" (after revocation).
    sent_elapsed = 9_000_000
    forged = fix(at=now() - dt.timedelta(minutes=10), elapsed_realtime_ms=sent_elapsed - 5, boot_count=4)
    response = await client.post("/api/me/location-pings", headers=bearer(a, **{
        "X-Device-Sent-At": now().isoformat(), "X-Device-Elapsed-Ms": str(sent_elapsed),
        "X-Device-Boot-Count": "4"}),
        json={"uuid": str(uuid.uuid4()), "pings": [forged]})
    assert response.status_code == 200 and response.json()["data"]["rejected"] == 1


async def test_listing_and_ending_my_sessions(worlds, db):
    client, acme, _ = worlds
    await field_user(db, acme)
    a = await login(client, client_type="web")
    b = await login(client, client_type="web")
    mine = await client.get("/api/auth/sessions", headers=bearer(a))
    assert mine.status_code == 200
    rows = mine.json()["data"]
    assert len(rows) == 2 and [r["current"] for r in rows].count(True) == 1
    ended = await client.delete(f"/api/auth/sessions/{b['session_uuid']}", headers=bearer(a))
    assert ended.status_code == 200
    assert (await client.get("/api/auth/me", headers=bearer(b))).status_code == 401
    admin_view = await client.get(f"/api/users/{acme.member.id}/sessions?include_revoked=true",
                                  headers=acme.auth(acme.admin))
    assert admin_view.status_code == 200 and len(admin_view.json()["data"]) == 2


async def test_legacy_tokens_without_a_session_keep_working(worlds):
    client, acme, _ = worlds
    assert (await client.get("/api/auth/me", headers=acme.auth(acme.member))).status_code == 200


# ── consent ─────────────────────────────────────────────────────────────────────

async def test_declining_consent_the_first_time_is_recorded(worlds):
    client, acme, _ = worlds
    declined = await client.post("/api/me/consents", headers=acme.auth(acme.member), json={
        "consent_type": "location_tracking", "consent_given": False, "consent_text_version": "1.0"})
    assert declined.status_code == 201, declined.text
    assert declined.json()["data"]["consent_given"] is False and declined.json()["data"]["is_active"] is False


async def test_consent_unblocks_the_shift_and_withdrawal_ends_it(worlds, db):
    client, acme, _ = worlds
    member = acme.auth(acme.member)
    current = (await client.get("/api/me/fieldops/current", headers=member)).json()["data"]
    assert current["consent"]["location_tracking"] == {"given": False, "version": None, "required": True}
    refused = await client.post("/api/me/shifts", headers=member, json={"uuid": str(uuid.uuid4()), "fix": fix()})
    assert refused.status_code == 422 and refused.json()["data"]["consent_endpoint"] == "/api/me/consents"

    body = {"consent_type": "location_tracking", "consent_text_version": "1.0", "consent_language": "en"}
    given = await client.post("/api/me/consents", headers=member, json=body)
    assert given.status_code == 201, given.text
    again = await client.post("/api/me/consents", headers=member, json=body)
    assert again.status_code == 200 and again.json()["data"]["id"] == given.json()["data"]["id"]

    shift = await client.post("/api/me/shifts", headers=member, json={"uuid": str(uuid.uuid4()), "fix": fix()})
    assert shift.status_code == 201, shift.text
    withdrawn = await client.post("/api/me/consents/location_tracking/withdraw", headers=member)
    assert withdrawn.status_code == 200 and withdrawn.json()["data"]["withdrawn"] == 1
    current = (await client.get("/api/me/fieldops/current", headers=member)).json()["data"]
    assert current["shift"] is None and current["consent"]["location_tracking"]["given"] is False
    from app.modules.fieldops.model import Shift

    row = await db.scalar(select(Shift).where(Shift.uuid == uuid.UUID(shift.json()["data"]["uuid"])))
    await db.refresh(row)
    assert (row.status, row.end_reason) == ("completed", "consent_withdrawn")


# ── privacy ─────────────────────────────────────────────────────────────────────

async def test_settings_options_list_every_value(worlds):
    client, acme, _ = worlds
    response = await client.get("/api/me/settings/options", headers=acme.auth(acme.member))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [o["value"] for o in data["profile_visibility"]] == ["everyone", "team", "managers", "private"]
    assert [o["value"] for o in data["contact_visibility"]] == ["everyone", "team", "hidden"]
    assert {c["key"] for c in data["notification_channels"]} == {"email", "push", "sms", "slack", "in_app"}
    assert data["two_factor_supported"] is False and data["admin_override"] is True


async def test_legacy_values_are_accepted_and_normalized(worlds):
    client, acme, _ = worlds
    response = await client.patch("/api/me/settings", headers=acme.auth(acme.member), json={
        "privacy": {"profile_visibility": "organization", "show_email": True, "show_phone": True},
        "notifications": {"slack": True}})
    assert response.status_code == 200, response.text
    privacy = response.json()["data"]["privacy"]
    assert (privacy["profile_visibility"], privacy["contact_visibility"]) == ("everyone", "everyone")
    assert response.json()["data"]["notifications"]["slack"] is True
    refused = await client.patch("/api/me/settings", headers=acme.auth(acme.member),
                                 json={"security": {"two_factor_enabled": True}})
    assert refused.status_code == 422


async def _colleague(db, world, *, email: str) -> User:
    from app.modules.roles.model import Role

    with tenant_scope(world.tenant.id, world.organization.id):
        role = await db.scalar(select(Role).where(Role.organization_id == world.organization.id, Role.code == "member"))
        user = User(name="Colleague", email=email, password="x", role_id=role.id, organization_id=world.organization.id,
                    phone="+91 90000 00001", designation="Delivery agent")
        db.add(user)
        await db.flush()
    await db.commit()
    return user


async def _same_team(db, world, *users: User) -> None:
    from app.modules.teams.model import Team, TeamType, UserTeam

    with tenant_scope(world.tenant.id, world.organization.id):
        kind = TeamType(type_code="FIELD", type_name="Field", organization_id=world.organization.id)
        db.add(kind)
        await db.flush()
        team = Team(team_code="HALOL", team_name="Halol", team_type_id=kind.id, organization_id=world.organization.id)
        db.add(team)
        await db.flush()
        for user in users:
            db.add(UserTeam(user_id=user.id, team_id=team.id, organization_id=world.organization.id))
        await db.flush()
    await db.commit()


@pytest.mark.parametrize(("contact", "teammate_sees", "stranger_sees"), [
    ("everyone", True, True), ("team", True, False), ("hidden", False, False)])
async def test_contact_visibility_follows_the_setting(worlds, db, contact, teammate_sees, stranger_sees):
    client, acme, _ = worlds
    subject = await _colleague(db, acme, email="subject@acme.example")
    teammate = await _colleague(db, acme, email="teammate@acme.example")
    stranger = await _colleague(db, acme, email="stranger@acme.example")
    await _same_team(db, acme, subject, teammate)
    from app.common.security.jwt import create_access_token

    def auth(user):
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    saved = await client.patch("/api/me/settings", headers=auth(subject),
                               json={"privacy": {"contact_visibility": contact}})
    assert saved.status_code == 200, saved.text
    for viewer, sees in ((teammate, teammate_sees), (stranger, stranger_sees)):
        card = (await client.get(f"/api/users/{subject.id}", headers=auth(viewer))).json()["data"]
        assert (card.get("email") == "subject@acme.example") is sees, (viewer.email, contact)
    admin = (await client.get(f"/api/users/{subject.id}", headers=acme.auth(acme.admin))).json()["data"]
    assert admin["email"] == "subject@acme.example"                       # administrators always see


async def test_a_private_profile_is_restricted_to_colleagues(worlds, db):
    client, acme, _ = worlds
    subject = await _colleague(db, acme, email="private@acme.example")
    from app.common.security.jwt import create_access_token

    token = {"Authorization": f"Bearer {create_access_token(str(subject.id))}"}
    await client.patch("/api/me/settings", headers=token, json={"privacy": {"profile_visibility": "private"}})
    card = (await client.get(f"/api/users/{subject.id}", headers=acme.auth(acme.member))).json()["data"]
    assert card["restricted"] is True and card["name"] == "Colleague" and card.get("designation") is None
