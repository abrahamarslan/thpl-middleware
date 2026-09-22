"""Brand master (``core`` schema, package-by-feature).

    enums.py model.py schema.py crud.py service.py api.py   the feature
    ../entities/                                            shared core registry + vocabularies

HTTP: /api/brands. The brand master is canonical (not a Zoho mirror); the
brand ↔ manufacturer relation and its validity-window guard live here too.
"""

from app.modules.brands.model import Brand, BrandManufacturer

__all__ = ["Brand", "BrandManufacturer"]
