"""Generate the phase-2 migration (items core) from the validated design SQL — run with the venv python."""

import sys
from pathlib import Path

ROOT = Path("/home/a2/projects/th-middleware")
DESIGN = ROOT / "docs/implementation-plans/catalogue/catalogue_schema.sql"
OUT = ROOT / "apps/core-platform/backend/alembic/versions/20261010_1200_3f8a1c5e9b27_catalogue_items.py"
sys.path.insert(0, str(ROOT / "apps/core-platform/backend"))

sql = DESIGN.read_text(encoding="utf-8")


def between(start: str, end: str) -> str:
    i = sql.index(start)
    return sql[i:sql.index(end, i)]


products = between("CREATE TABLE catalogue.products", "-- ============================================================================\n-- §3. Items")
items = between("CREATE TABLE catalogue.items", "-- ============================================================================\n-- §4. Batches")
functions = between("CREATE OR REPLACE FUNCTION catalogue.guard_item_unit()",
                    "-- ============================================================================\n-- §6. Pricing")

TABLES = ("products", "product_attributes", "items", "item_merchandising", "item_attribute_values", "item_units",
          "item_identifiers", "item_components", "item_sales_channels", "item_vendors")


def comments() -> str:
    from app.database.db import Base
    import app.modules.catalogue.model  # noqa: F401

    def lit(value):
        return "NULL" if value is None else "'" + value.replace("'", "''") + "'"

    out = []
    for name in TABLES:
        table = Base.metadata.tables[f"catalogue.{name}"]
        out.append(f"COMMENT ON TABLE catalogue.{name} IS {lit(table.comment)};")
        for column in table.columns:
            out.append(f"COMMENT ON COLUMN catalogue.{name}.{column.name} IS {lit(column.comment)};")
    return "\n".join(out)


TEMPLATE = '''"""Catalogue phase 2 — items core: products (variant templates), items (the SKU), storefront content,
variant values, the packaging hierarchy, identifiers/barcodes per level, components, channel listings,
vendors; plus the media gallery and the polymorphic registrations items need.

    catalogue.products / product_attributes      variant templates and their axes
    catalogue.items                              the SKU documents and stock reference
    catalogue.item_merchandising                 1:1 storefront / SEO content (a different owner)
    catalogue.item_attribute_values              a variant's axis values
    catalogue.item_units                         the packaging hierarchy (base_factor by trigger, structure immutable)
    catalogue.item_identifiers                   barcodes / codes, per pack level (GS1)
    catalogue.item_components                    BOM / kit / box contents (acyclic by trigger)
    catalogue.item_sales_channels                channel listings
    catalogue.item_vendors                       suppliers (party.parties vendors)
    media.items.position                         ordering inside a gallery collection
    registrations                                entity types item / product; taxes (item: one tax per context +
                                                 exemptions); accounts (sales / purchase / inventory_asset);
                                                 comments (item, product)

DDL generated verbatim from docs/implementation-plans/catalogue/catalogue_schema.sql (§2 products, §3, §5);
comments from the ORM models — so `alembic check` reports nothing for the catalogue. One statement per execute.

Revision ID: 3f8a1c5e9b27
Revises: 66d0b2e09e76
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8a1c5e9b27"
down_revision: str | None = "66d0b2e09e76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DDL = r"""
__PRODUCTS__

__ITEMS__

__FUNCTIONS__
"""

_COMMENTS = r"""
__COMMENTS__
"""

_TABLES = __TABLES__


def _statements(script: str) -> list[str]:
    """Split on ``;`` at line ends, never inside a ``$$`` body; drop comment-only chunks."""
    out, buf, in_body = [], [], False
    for line in script.splitlines():
        buf.append(line)
        if line.count("$$") % 2 == 1:
            in_body = not in_body
        if not in_body and line.rstrip().endswith(";"):
            stmt = "\\n".join(buf).strip()
            buf = []
            body = "\\n".join(x for x in stmt.splitlines() if not x.strip().startswith("--")).strip()
            if body:
                out.append(stmt.rstrip(";"))
    tail = "\\n".join(x for x in buf if not x.strip().startswith("--")).strip()
    if tail:
        out.append(tail.rstrip(";"))
    return out


def upgrade() -> None:
    for statement in _statements(_DDL) + _statements(_COMMENTS):
        op.execute(statement)
    for table in _TABLES:
        op.execute(f"CREATE UNIQUE INDEX ix_catalogue_{table}_uuid ON catalogue.{table} (uuid)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_deleted_at ON catalogue.{table} (deleted_at)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_status ON catalogue.{table} (status)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_tenant_id ON catalogue.{table} (tenant_id)")
        op.execute(f"CREATE INDEX ix_{table}_tenant_org ON catalogue.{table} (tenant_id, organization_id)")

    # Gallery collections (item images) need an order; single-image collections (avatar) keep 0.
    op.add_column("items", sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False,
                                     comment="Order inside a gallery collection (0 for single-image collections)"),
                  schema="media")

    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO core.entity_types (code, name, target_schema, target_table, description, created_by_name) VALUES "
        "('item', 'Item', 'catalogue', 'items', 'An item (SKU) of the catalogue.', 'system:migration'), "
        "('product', 'Product', 'catalogue', 'products', 'A variant template grouping items.', 'system:migration') "
        "ON CONFLICT (code) DO NOTHING"))
    from app.modules.accounting.registration import register_account_owner_type
    from app.modules.comments.registration import register_commentable_entity_type
    from app.modules.taxes.registration import register_taxable_entity_type

    register_taxable_entity_type(
        bind, code="item", name="Item", target_schema="catalogue", target_table="items",
        allows_multiple=False, allows_exemption=True,
        description="Item GST preferences (Zoho item_tax_preferences / tax_exemption_id).",
    )
    register_account_owner_type(
        bind, code="item", name="Item", target_schema="catalogue", target_table="items",
        purposes={"sales": True, "purchase": True, "inventory_asset": True},
        description="Zoho item account_id / purchase_account_id / inventory_account_id.",
    )
    register_commentable_entity_type(bind, code="item", name="Item", target_schema="catalogue",
                                     target_table="items", description="Notes on an item.")
    register_commentable_entity_type(bind, code="product", name="Product", target_schema="catalogue",
                                     target_table="products", description="Notes on a product.")

    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for statement in (
        "DELETE FROM comments.commentable_entity_types WHERE entity_type_code IN ('item', 'product')",
        "DELETE FROM accounting.account_purpose_policies WHERE entity_type_code = 'item'",
        "DELETE FROM tax.taxable_entity_types WHERE entity_type_code = 'item'",
    ):
        bind.execute(sa.text(statement))
    op.drop_column("items", "position", schema="media")
    op.execute("ALTER TABLE catalogue.items DROP CONSTRAINT IF EXISTS fk_items_zoho_item_unit")
    for table in ("item_vendors", "item_sales_channels", "item_components", "item_identifiers",
                  "item_attribute_values", "item_merchandising", "item_units", "items", "product_attributes",
                  "products"):
        op.execute(f"DROP TABLE IF EXISTS catalogue.{table}")
    for function in ("guard_item_unit()", "guard_items_base_unit()", "guard_item_component_cycle()",
                     "convert_quantity(numeric, bigint, bigint)"):
        op.execute(f"DROP FUNCTION IF EXISTS catalogue.{function}")
    for statement in (
        "DELETE FROM extfields.field_values WHERE owner_type_code IN ('item', 'product')",
        "DELETE FROM extfields.field_definitions WHERE owner_type_code IN ('item', 'product')",
        "DELETE FROM core.entity_types WHERE code IN ('item', 'product')",
    ):
        bind.execute(sa.text(statement))
'''

text = (TEMPLATE.replace("__PRODUCTS__", products.strip()).replace("__ITEMS__", items.strip())
        .replace("__FUNCTIONS__", functions.strip()).replace("__COMMENTS__", comments())
        .replace("__TABLES__", repr(TABLES)))
OUT.write_text(text, encoding="utf-8", newline="\n")
print(OUT, len(text))
