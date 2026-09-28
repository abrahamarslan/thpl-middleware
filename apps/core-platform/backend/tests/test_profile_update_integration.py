"""``PATCH /api/auth/me/profile`` against a real database.

Two production failures this pins:

* saving the SAME address twice was a 500 — ``create_place`` reuses the
  near-duplicate place, the old ``current`` link was closed (not deleted), and the
  new link for that place broke ``uq_place_links_dedupe``;
* an unknown country / timezone was discovered only after the user row had been
  written, audited and pushed to Authentik (a rollback cannot recall that push).

``tests/test_profile_endpoints.py`` mocks the boundaries; these do not.
"""

from sqlalchemy import func, select

from app.modules.geo.model import PlaceLink
from app.modules.users.model import Country, CountryTimezone, Timezone, User

HEADERS = {"X-Organization-Code": "ACME-HQ"}
PUNE = {"street": "1 Main Road", "city": "Pune", "postal_code": "411001",
        "latitude": 18.5204, "longitude": 73.8567}
MUMBAI = {"street": "9 Marine Drive", "city": "Mumbai", "postal_code": "400020",
          "latitude": 19.0760, "longitude": 72.8777}


async def _seed_reference(db) -> None:
    """India + Asia/Kolkata — the smallest reference data the profile endpoint needs.
    (The `db` fixture truncates these tables again, so nothing leaks between tests.)"""
    db.add_all([
        Country(iso2="IN", iso3="IND", name="India", currency_code="INR"),
        Timezone(iana_name="Asia/Kolkata", display_name="Kolkata"),
    ])
    await db.flush()
    db.add(CountryTimezone(country_iso2="IN", timezone_name="Asia/Kolkata", is_default=True))
    await db.commit()


async def _links(db, user_id: int) -> list[PlaceLink]:
    return list((await db.scalars(
        select(PlaceLink).where(PlaceLink.owner_type == "user", PlaceLink.owner_id == user_id)
        .order_by(PlaceLink.id)
    )).all())


async def _patch(client, acme, body: dict):
    return await client.patch(
        "/api/auth/me/profile", headers=acme.auth(acme.member, **HEADERS), json=body,
    )


# ── the address 500 ─────────────────────────────────────────────────────────

async def test_saving_the_same_address_twice_is_idempotent(worlds, db):
    client, acme, _ = worlds
    body = {"address": PUNE}

    first = await _patch(client, acme, body)
    second = await _patch(client, acme, body)
    third = await _patch(client, acme, body)

    assert first.status_code == second.status_code == third.status_code == 200, second.text
    links = await _links(db, acme.member.id)
    assert len(links) == 1 and links[0].valid_to is None and links[0].is_primary
    assert second.json()["data"]["address"]["city"] == "Pune"


async def test_resaving_an_address_refreshes_its_label_without_a_new_row(worlds, db):
    client, acme, _ = worlds
    await _patch(client, acme, {"address": {**PUNE, "label": "Home"}})
    again = await _patch(client, acme, {"address": {**PUNE, "label": "Flat 4B"}})

    assert again.status_code == 200, again.text
    links = await _links(db, acme.member.id)
    assert len(links) == 1
    assert links[0].label == "Flat 4B"
    assert again.json()["data"]["address"]["label"] == "Flat 4B"


async def test_moving_to_a_new_address_keeps_the_old_one_as_history(worlds, db):
    client, acme, _ = worlds
    await _patch(client, acme, {"address": PUNE})
    moved = await _patch(client, acme, {"address": MUMBAI})

    assert moved.status_code == 200, moved.text
    links = await _links(db, acme.member.id)
    assert [link.valid_to is None for link in links] == [False, True]      # Pune closed, Mumbai open
    assert moved.json()["data"]["address"]["city"] == "Mumbai"


async def test_moving_back_to_an_old_address_is_allowed(worlds, db):
    """A → B → A: the closed A link is history, so it must not block a new A link."""
    client, acme, _ = worlds
    for address in (PUNE, MUMBAI, PUNE):
        response = await _patch(client, acme, {"address": address})
        assert response.status_code == 200, response.text

    links = await _links(db, acme.member.id)
    assert len(links) == 3
    assert sum(link.valid_to is None for link in links) == 1              # exactly one open
    assert links[-1].valid_to is None and links[-1].is_primary
    assert response.json()["data"]["address"]["city"] == "Pune"


# ── validate up front ───────────────────────────────────────────────────────

async def test_an_unknown_timezone_is_refused_before_anything_is_written(worlds, db, mocker):
    client, acme, _ = worlds
    await _seed_reference(db)
    push = mocker.patch("app.modules.users.authentik_sync.sync_update_profile")
    before = acme.member.name

    response = await _patch(client, acme, {
        "first_name": "Bruno", "last_name": "Client", "phone": "8978675678",
        "timezone": "ist", "address": PUNE,
    })

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "invalid_profile_value"
    assert body["data"]["field"] == "timezone" and "Asia/Kolkata" in body["data"]["hint"]
    push.assert_not_called()                                              # nothing reached Authentik
    await db.refresh(acme.member)
    assert acme.member.name == before and acme.member.first_name is None  # no user write
    assert await _links(db, acme.member.id) == []                         # no address either


async def test_an_unknown_country_is_refused_before_anything_is_written(worlds, db, mocker):
    client, acme, _ = worlds
    await _seed_reference(db)
    push = mocker.patch("app.modules.users.authentik_sync.sync_update_profile")

    response = await _patch(client, acme, {"first_name": "Bruno", "country_code": "zz"})

    assert response.status_code == 422, response.text
    assert response.json()["data"]["field"] == "country_code"
    push.assert_not_called()
    await db.refresh(acme.member)
    assert acme.member.first_name is None


async def test_a_valid_full_profile_saves_country_timezone_and_address(worlds, db):
    client, acme, _ = worlds
    await _seed_reference(db)

    response = await _patch(client, acme, {
        "first_name": "Bruno", "last_name": "Client", "phone": "8978675678",
        "country_code": "in", "timezone": "Asia/Kolkata", "language": "hi",
        "address": {**PUNE, "label": "Home"},
    })

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Bruno Client" and data["country_code"] == "IN"
    assert data["timezone"] == "Asia/Kolkata" and data["timezone_source"] == "manual"
    assert data["address"]["city"] == "Pune"
    user = await db.scalar(select(User).where(User.id == acme.member.id))
    assert user.phone == "8978675678" and user.language == "hi"
    assert await db.scalar(select(func.count()).select_from(PlaceLink)
                           .where(PlaceLink.owner_id == acme.member.id)) == 1
