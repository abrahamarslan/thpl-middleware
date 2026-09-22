"""Manufacturer master (``core`` schema, package-by-feature).

    enums.py model.py schema.py crud.py service.py api.py   the feature
    ../entities/                                            shared core registry + vocabularies

HTTP: /api/manufacturers. The master is canonical; its registrations/licences
(GSTIN, PAN, CIN, FSSAI, drug licence, …) live in ``manufacturer_identifiers``.
"""

from app.modules.manufacturers.model import Manufacturer, ManufacturerIdentifier

__all__ = ["Manufacturer", "ManufacturerIdentifier"]
