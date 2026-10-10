"""ORM models of the ``catalogue`` schema (one file per table group)."""

from app.modules.catalogue.model.reference import (
    Attribute,
    AttributeOption,
    ItemGroup,
    PackagingType,
    SalesChannel,
    Unit,
    UqcCode,
)
from app.modules.catalogue.model.product import Product, ProductAttribute  # noqa: I001 — after reference
from app.modules.catalogue.model.item_unit import ItemUnit
from app.modules.catalogue.model.item import (
    Item,
    ItemAttributeValue,
    ItemComponent,
    ItemIdentifier,
    ItemMerchandising,
    ItemSalesChannel,
    ItemVendor,
)

__all__ = [
    "Attribute", "AttributeOption", "Item", "ItemAttributeValue", "ItemComponent", "ItemGroup", "ItemIdentifier",
    "ItemMerchandising", "ItemSalesChannel", "ItemUnit", "ItemVendor", "PackagingType", "Product",
    "ProductAttribute", "SalesChannel", "Unit", "UqcCode",
]
