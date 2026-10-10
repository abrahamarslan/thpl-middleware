"""Zoho GSTIN / PAN / Udyam / VAT → ``tax.tax_registrations`` (owner ``party``).

Only the DETAIL document carries ``tax_info_list`` (the GSTINs with their ``tax_info_id``), so the
projection runs only when that key is present. ``gst_no`` without a matching list entry still yields a
primary GSTIN row (no Zoho id). PAN, Udyam, VAT and tax_reg_no come from the scalar keys. Numbers are
stored normalized and in clear (owner decision 2026-10-09).

Replace-set over the ZOHO-sourced rows of the owner only: local registrations (``source_system IS
NULL`` — e.g. a GSTIN a field rep verified) are never touched by the sync. Zoho rows are trusted: a
malformed number is stored as sent and reported, never refused.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.parties.enums import PARTY_ENTITY_TYPE
from app.modules.parties.model import Party
from app.modules.sync.translation import CODECS
from app.modules.taxes.tax_registration import RegistrationType, TaxRegistration, normalize_number

_str, _bool, _dt = CODECS["str"].decode, CODECS["bool"].decode, CODECS["zoho_datetime"].decode
REMOVED_REASON = "zoho:removed_from_contact"


def wanted_registrations(party: Party, payload: dict) -> list[dict[str, Any]]:
    """Every registration the payload names, keyed by (type, number)."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, number: Any, **extra: Any) -> None:
        normalized = normalize_number(number)
        if normalized is None or (kind, normalized) in seen:
            return
        seen.add((kind, normalized))
        out.append({"registration_type": kind, "registration_number": normalized, **extra})

    infos = [t for t in payload.get("tax_info_list") or [] if isinstance(t, dict)]
    for info in infos:
        add(RegistrationType.GSTIN.value, info.get("tax_registration_no"),
            zoho_id=_str(info.get("tax_info_id")), place_of_supply=_str(info.get("place_of_supply")),
            legal_name=_str(info.get("legal_name")), trade_name=_str(info.get("trader_name")),
            is_primary=bool(_bool(info.get("is_primary"))))
    has_primary_gstin = any(r.get("is_primary") for r in out)
    add(RegistrationType.GSTIN.value, payload.get("gst_no"), zoho_id=None,
        place_of_supply=_str(payload.get("place_of_contact")), legal_name=_str(payload.get("legal_name")),
        trade_name=_str(payload.get("trader_name")), is_primary=not has_primary_gstin)
    add(RegistrationType.PAN.value, payload.get("pan_no"), is_primary=True,
        legal_name=_str(payload.get("legal_name")))
    add(RegistrationType.UDYAM.value, payload.get("udyam_reg_no"), is_primary=True, details={
        "msme_type": _str(payload.get("msme_type")),
        "is_valid": _bool(payload.get("is_valid_udyam_no")),
        "validated_at": (lambda v: v.isoformat() if v else None)(_dt(payload.get("udyam_validated_time"))),
    })
    add(RegistrationType.VAT.value, payload.get("vat_reg_no"), is_primary=True)
    add(RegistrationType.TAX_REG_NO.value, payload.get("tax_reg_no"), is_primary=True)
    return out


async def project_registrations(db: AsyncSession, party: Party, payload: dict) -> dict[str, int]:
    counts = {"registrations_added": 0, "registrations_updated": 0, "registrations_removed": 0}
    existing = {(r.registration_type, r.registration_number): r for r in (await db.scalars(
        select(TaxRegistration).where(TaxRegistration.owner_type_code == PARTY_ENTITY_TYPE,
                                      TaxRegistration.owner_id == party.id,
                                      TaxRegistration.source_system == "zoho")
    )).all()}
    wanted = wanted_registrations(party, payload)
    keys = {(w["registration_type"], w["registration_number"]) for w in wanted}

    leaving = [r for key, r in existing.items() if key not in keys]
    for row in leaving:
        row.is_primary = False
        row.soft_delete(reason=REMOVED_REASON)
    counts["registrations_removed"] = len(leaving)

    rows: list[tuple[TaxRegistration, bool]] = []
    for item in wanted:
        primary = bool(item.pop("is_primary", False))
        row = existing.get((item["registration_type"], item["registration_number"]))
        if row is None:
            row = TaxRegistration(tenant_id=party.tenant_id, organization_id=party.organization_id,
                                  owner_type_code=PARTY_ENTITY_TYPE, owner_id=party.id, source_system="zoho",
                                  is_primary=False, **item)
            db.add(row)
            counts["registrations_added"] += 1
        else:
            changed = False
            for column, value in item.items():
                if getattr(row, column) != value:
                    setattr(row, column, value)
                    changed = True
            counts["registrations_updated"] += int(changed)
        rows.append((row, primary))

    # One primary per type: demote, flush, promote (uq_tax_registrations_one_primary).
    for row, primary in rows:
        if row.is_primary and not primary:
            row.is_primary = False
    await db.flush()
    for row, primary in rows:
        if primary and not row.is_primary:
            row.is_primary = True
    await db.flush()
    return counts


__all__ = ["project_registrations", "wanted_registrations"]
