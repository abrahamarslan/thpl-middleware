"""Translators for the three tax resources.

Only the tax group needs more than its field map: its payload nests the member
taxes as an array (``taxes[]``), and the array's home is
``tax.tax_group_members``, a child table. The translator normalises the array
into member rows; the adapter's post-hook (hooks.py) writes them.

Each member entry also carries the member's own display and rate facts
(``tax_name``, ``tax_percentage``, …). They are deliberately NOT decoded: the
member component owns them and is synced by the ``taxes`` module, so copying
them here would create a second, drifting copy. The entry survives whole in
``sync.sync_records.raw`` (the ``snapshot`` layer of the field catalog).
"""

from __future__ import annotations

from app.modules.sync.translation import Decoded, FieldTranslator, PayloadShape
from app.modules.taxes.zoho.fields import EXEMPTION_FIELDS, TAX_FIELDS, TAX_GROUP_FIELDS

TAX_TRANSLATOR = FieldTranslator("taxes", TAX_FIELDS)
EXEMPTION_TRANSLATOR = FieldTranslator("tax_exemptions", EXEMPTION_FIELDS)


class TaxGroupTranslator(FieldTranslator):
    """``/settings/taxgroups/{id}`` ↔ ``tax.tax_components`` + ``tax.tax_group_members``."""

    def __init__(self, module: str) -> None:
        super().__init__(module, TAX_GROUP_FIELDS)

    def decode(self, payload: dict, *, shape: PayloadShape = PayloadShape.DETAIL) -> Decoded:
        decoded = super().decode(payload, shape=shape)
        members = payload.get("taxes")
        if isinstance(members, list):
            # ``position`` is the array index: the source has no explicit order,
            # so this is the order it returned them in.
            decoded.children["members"] = [
                {"tax_id": str(entry["tax_id"]), "position": position}
                for position, entry in enumerate(members)
                if isinstance(entry, dict) and entry.get("tax_id") not in (None, "")
            ]
        return decoded


TAX_GROUP_TRANSLATOR = TaxGroupTranslator("tax_groups")

__all__ = [
    "EXEMPTION_TRANSLATOR",
    "TAX_GROUP_TRANSLATOR",
    "TAX_TRANSLATOR",
    "TaxGroupTranslator",
]
