"""Zoho billing / shipping / additional addresses → ``geo.places`` + ``geo.place_links`` (owner ``party``).

Rules (docs/implementation-plan/contacts-module.md §6.4):

1. **One Zoho address = one link.** Zoho's ``address_id`` is ``place_links.zoho_id``. The PLACE is the
   physical spot and may be shared by owners (Design Rule Zero), so the Zoho id never goes on it.
2. **Link types.** ``billing_address`` → ``billing`` (primary), ``shipping_address`` → ``shipping``
   (primary), each of ``addresses[]`` → ``other`` (owner decision 2026-10-09).
3. **Postal-empty → nothing.** Zoho sends billing AND shipping objects with their own ids even when
   every field is blank (most parties); an address with no postal text creates no place, and an existing
   link for that id is closed (``valid_to``) — history, never deleted.
4. **Reuse within the party only.** Billing and shipping with the same text share ONE place through two
   links. Places are never matched across parties: Zoho owns this text, and an edit to party A's
   address must never move party B's shop.
5. **Copy-on-write.** When Zoho changes an address, the place is edited in place only if nothing else
   links to it and nobody field-verified it; otherwise a new place is created and the link repointed
   (the verified place stays for the field team).
6. **Closing.** An ``address_id`` no longer in the document closes its link. Local links (``zoho_id IS
   NULL`` — e.g. a field-verified shop pin) are never touched by the sync.
7. **Duplicates collapse.** Two Zoho addresses with the same text and type (seen live: the same
   ``addresses[]`` entry twice under two ``address_id``s) keep ONE link; the duplicate is counted
   (``duplicates_skipped``) instead of failing the contact on ``uq_place_links_dedupe``.
"""

from __future__ import annotations

from typing import Any

import structlog
from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo.enums import LinkType, PlaceKind
from app.modules.geo.model.link import PlaceLink
from app.modules.geo.model.place import Place
from app.modules.geo.service import compose_address
from app.modules.parties.enums import PARTY_ENTITY_TYPE, PartyType
from app.modules.parties.model import Party
from app.modules.sync.translation import CODECS

logger = structlog.get_logger("app.parties.zoho")

_str = CODECS["str"].decode
_POSTAL = ("street", "street2", "city", "state", "postal_code", "country")
#: Plausible coordinates for an Indian organization (lat 6–37 N, long 68–98 E).
_BBOX = {"IN": (6.0, 37.0, 68.0, 98.0)}


def address_parts(raw: dict | None) -> dict[str, Any] | None:
    """Zoho address object → place columns; None when it carries no postal text at all."""
    if not isinstance(raw, dict):
        return None
    parts = {
        "street": _str(raw.get("address")),
        "street2": _str(raw.get("street2")),
        "city": _str(raw.get("city")),
        "state": _str(raw.get("state")),
        "state_code": _str(raw.get("state_code")),
        "postal_code": _str(raw.get("zip")),
        "country": _str(raw.get("country")),
        "country_code": (_str(raw.get("country_code")) or "").upper() or None,
        "district": _str(raw.get("county")),
        "fax": _str(raw.get("fax")),
    }
    if not any(parts[k] for k in _POSTAL):
        return None
    if parts["country"] is None and parts["country_code"] in (None, "IN"):
        parts["country"] = "India"
    if parts["country_code"] is None and (parts["country"] or "").strip().lower() == "india":
        parts["country_code"] = "IN"
    return parts


def fingerprint(parts: dict[str, Any]) -> tuple:
    return tuple(" ".join((parts.get(k) or "").lower().split()) for k in _POSTAL)


def place_fingerprint(place: Place) -> tuple:
    return fingerprint({"street": place.street, "street2": place.street2, "city": place.city,
                        "state": place.state, "postal_code": place.postal_code, "country": place.country})


def plausible_point(latitude: Any, longitude: Any, country_code: str = "IN") -> tuple[float, float] | None:
    try:
        lat, lon = float(str(latitude).strip()), float(str(longitude).strip())
    except (TypeError, ValueError):
        return None
    lat_min, lat_max, lon_min, lon_max = _BBOX.get(country_code, (-90.0, 90.0, -180.0, 180.0))
    if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
        return None
    return lat, lon


def _point(lat: float, lon: float) -> WKTElement:
    return WKTElement(f"POINT({lon} {lat})", srid=4326)       # WKT is longitude first


def wanted_addresses(payload: dict) -> list[tuple[str, str, dict | None, str | None]]:
    """``(address_id, link_type, raw, label)`` for every Zoho address the payload carries."""
    out: list[tuple[str, str, dict | None, str | None]] = []
    for key, link_type in (("billing_address", LinkType.BILLING.value), ("shipping_address", LinkType.SHIPPING.value)):
        raw = payload.get(key)
        if isinstance(raw, dict) and _str(raw.get("address_id")):
            out.append((_str(raw["address_id"]), link_type, raw, None))
    for index, raw in enumerate(payload.get("addresses") or [], start=1):
        if isinstance(raw, dict) and _str(raw.get("address_id")):
            out.append((_str(raw["address_id"]), LinkType.OTHER.value, raw, f"Additional address {index}"))
    return out


async def _other_links(db: AsyncSession, place_id: int, link_id: int | None) -> int:
    stmt = select(func.count()).select_from(PlaceLink).where(PlaceLink.place_id == place_id,
                                                             PlaceLink.deleted_at.is_(None))
    if link_id is not None:
        stmt = stmt.where(PlaceLink.id != link_id)
    return int(await db.scalar(stmt) or 0)


def _fill_place(place: Place, parts: dict[str, Any], raw: dict) -> None:
    for column in ("street", "street2", "city", "state", "state_code", "postal_code", "country_code", "district", "fax"):
        if getattr(place, column) != parts[column]:
            setattr(place, column, parts[column])
    if place.country != parts["country"]:
        place.country = parts["country"] or "India"
    point = plausible_point(raw.get("latitude"), raw.get("longitude"), parts["country_code"] or "IN")
    if point is not None and not place.has_coordinates:
        place.coordinates = _point(*point)
        place.provider = place.provider or "zoho"
    formatted = compose_address(place)
    if place.formatted_address != formatted:
        place.formatted_address = formatted


async def project_addresses(db: AsyncSession, party: Party, payload: dict) -> dict[str, int]:
    counts = {"places_created": 0, "places_updated": 0, "links_added": 0, "links_updated": 0, "links_closed": 0,
              "duplicates_skipped": 0}
    scope = {"tenant_id": party.tenant_id, "organization_id": party.organization_id}
    kind = PlaceKind.CUSTOMER_SITE.value if party.party_type == PartyType.CUSTOMER.value else PlaceKind.ADDRESS.value

    links = list((await db.scalars(
        select(PlaceLink).where(PlaceLink.owner_type == PARTY_ENTITY_TYPE, PlaceLink.owner_id == party.id,
                                PlaceLink.zoho_id.is_not(None))
    )).all())
    by_zoho = {link.zoho_id: link for link in links}
    place_ids = {link.place_id for link in links}
    places = {p.id: p for p in (await db.scalars(select(Place).where(Place.id.in_(place_ids)))).all()} if place_ids else {}

    wanted = wanted_addresses(payload)
    seen = {address_id for address_id, *_ in wanted}
    # Rule 6 FIRST: a departed address must release its primary slot before a new one claims it
    # (uq_place_links_one_primary — e.g. Zoho replaced the billing address with a new address_id).
    for link in links:
        if link.zoho_id not in seen and link.valid_to is None:
            link.close()
            counts["links_closed"] += 1
    await db.flush()

    for address_id, link_type, raw, label in wanted:
        parts = address_parts(raw)
        link = by_zoho.get(address_id)
        if parts is None:                                   # rule 3
            if link is not None and link.valid_to is None:
                link.close()
                counts["links_closed"] += 1
            continue
        target_fp = fingerprint(parts)

        place: Place | None = places.get(link.place_id) if link is not None else None
        if place is None or place_fingerprint(place) != target_fp:
            # Rule 4: the same text already has a place among THIS party's open Zoho links of another type.
            reuse = next((places[o.place_id] for o in links
                          if o is not link and o.valid_to is None and o.place_id in places
                          and o.link_type != link_type and place_fingerprint(places[o.place_id]) == target_fp), None)
            if reuse is not None:
                place = reuse
            elif (place is not None and place.verification_status != "field_verified"
                  and await _other_links(db, place.id, link.id if link is not None else None) == 0):
                _fill_place(place, parts, raw)              # rule 5: private and unverified → edit in place
                counts["places_updated"] += 1
            else:
                place = Place(**scope, kind=kind, status="active")
                _fill_place(place, parts, raw)
                db.add(place)
                await db.flush()
                places[place.id] = place
                counts["places_created"] += 1
        else:
            _fill_place(place, parts, raw)                  # same text: refresh fax / coordinates / formatting

        # Rule 7: Zoho may carry the same text twice in addresses[] (two address_ids, one address). Both
        # resolve to the same place and the second would duplicate an open (place, type) link
        # (uq_place_links_dedupe) and fail the whole contact — keep ONE link and count the duplicate.
        twin = next((o for o in links if o is not link and o.valid_to is None and o.deleted_at is None
                     and o.place_id == place.id and o.link_type == link_type), None)
        if twin is not None:
            if link is not None and link.valid_to is None:
                link.close()
                counts["links_closed"] += 1
            counts["duplicates_skipped"] += 1
            continue

        link_values = {
            "place_id": place.id, "link_type": link_type,
            "is_primary": link_type in (LinkType.BILLING.value, LinkType.SHIPPING.value),
            "attention": _str(raw.get("attention")), "contact_phone": _str(raw.get("phone")), "label": label,
        }
        if link is None:
            link = PlaceLink(**scope, owner_type=PARTY_ENTITY_TYPE, owner_id=party.id, zoho_id=address_id,
                             **link_values)
            db.add(link)
            links.append(link)
            by_zoho[address_id] = link
            counts["links_added"] += 1
        else:
            changed = False
            if link.valid_to is not None:                   # Zoho filled an address it had emptied: reopen
                link.valid_to = None
                changed = True
            for column, value in link_values.items():
                if getattr(link, column) != value:
                    setattr(link, column, value)
                    changed = True
            counts["links_updated"] += int(changed)
        await db.flush()
    return counts


async def apply_custom_coordinates(db: AsyncSession, party: Party, latitude: Any, longitude: Any) -> str:
    """``cf_location_latitude/longitude`` → the billing (else shipping) place, when plausible and the place
    has no coordinates from a better source. Returns what happened (for the data-quality counters)."""
    point = plausible_point(latitude, longitude)
    if point is None:
        return "implausible"
    link = await db.scalar(
        select(PlaceLink).where(PlaceLink.owner_type == PARTY_ENTITY_TYPE, PlaceLink.owner_id == party.id,
                                PlaceLink.deleted_at.is_(None), PlaceLink.valid_to.is_(None),
                                PlaceLink.link_type.in_((LinkType.BILLING.value, LinkType.SHIPPING.value)))
        .order_by(PlaceLink.link_type.asc()).limit(1)        # 'billing' < 'shipping'
    )
    if link is None:
        return "no_address"
    place = await db.get(Place, link.place_id)
    if place is None:
        return "no_address"
    if place.has_coordinates and place.provider not in (None, "zoho", "zoho_custom_field"):
        return "kept_better_source"
    place.coordinates = _point(*point)
    place.provider = "zoho_custom_field"
    await db.flush()
    return "applied"


__all__ = ["address_parts", "apply_custom_coordinates", "plausible_point", "project_addresses", "wanted_addresses"]
