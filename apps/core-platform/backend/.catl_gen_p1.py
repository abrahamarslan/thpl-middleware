"""Generate the phase-1 migration from the validated design SQL (run once with WSL python3)."""

from pathlib import Path

DESIGN = Path("/home/a2/projects/th-middleware/docs/implementation-plans/catalogue/catalogue_schema.sql")
OUT = Path("/home/a2/projects/th-middleware/apps/core-platform/backend/alembic/versions/"
           "20261010_0900_66d0b2e09e76_catalogue_masters.py")

sql = DESIGN.read_text(encoding="utf-8")
tables = sql[sql.index("CREATE TABLE catalogue.uqc_codes"):
             sql.index("-- ---------------------------------------------------------------------------\n-- catalogue.products")]
uqc_seed = sql[sql.index("INSERT INTO catalogue.uqc_codes"):]
uqc_seed = uqc_seed[:uqc_seed.index("ON CONFLICT (code) DO NOTHING;") + len("ON CONFLICT (code) DO NOTHING;")]
seed_fn = sql[sql.index("CREATE OR REPLACE FUNCTION catalogue.seed_standard_units"):]
seed_fn = seed_fn[:seed_fn.index("END $$;") + len("END $$;")]

TEMPLATE = '''"""Catalogue phase 1 — masters: GST UQC codes, units, packaging types, sales channels, item groups,
variant attributes and their options.

    catalogue.uqc_codes          GLOBAL GSTN Unit Quantity Codes (seeded)
    catalogue.units              count + physical units per organization (standard set seeded)
    catalogue.packaging_types    packaging characteristics
    catalogue.sales_channels     route to market (zoho_code ↔ Zoho contact sales_channel)
    catalogue.item_groups        merchandising groups (tree)
    catalogue.attributes         variant axes …
    catalogue.attribute_options  … and their values

Every organization gets the standard units: existing ones here, new ones from the AFTER INSERT trigger
``trg_organizations_seed_catalogue`` on ``org_management.organizations`` (the database provisions it, so
no tenancy-core module has to import the catalogue).

The DDL is generated verbatim from the design file docs/implementation-plans/catalogue/catalogue_schema.sql
(§1, §2 up to products, §10.1, §10.2), so the migration and the reviewed design cannot drift. Statements
run one per ``execute`` (asyncpg runs one statement at a time).

Downgrade drops the trigger, the functions, the seven tables and the schema (lossy by nature).

Revision ID: 66d0b2e09e76
Revises: 5b8d2e71c4a9
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "66d0b2e09e76"
down_revision: str | None = "5b8d2e71c4a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = r"""
__TABLES__
"""

_UQC_SEED = r"""
__UQC__
"""

_SEED_FUNCTION = r"""
__SEED__
"""

_PROVISIONING = (
    r"""
CREATE OR REPLACE FUNCTION catalogue.on_organization_created() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM catalogue.seed_standard_units(NEW.tenant_id, NEW.id);
    RETURN NEW;
END $$
""",
    "COMMENT ON FUNCTION catalogue.on_organization_created() IS "
    "'Gives every new organization the standard catalogue units (trg_organizations_seed_catalogue).'",
    "CREATE TRIGGER trg_organizations_seed_catalogue AFTER INSERT ON org_management.organizations "
    "FOR EACH ROW EXECUTE FUNCTION catalogue.on_organization_created()",
    "SELECT catalogue.seed_standard_units(o.tenant_id, o.id) FROM org_management.organizations o "
    "WHERE o.deleted_at IS NULL",
)

#: The mixin-generated indexes, with the names Alembic autogenerate emits.
_ENTITY_TABLES = ("units", "packaging_types", "sales_channels", "item_groups", "attributes", "attribute_options")


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
    op.execute("CREATE SCHEMA IF NOT EXISTS catalogue")
    op.execute("COMMENT ON SCHEMA catalogue IS "
               "'Item master: units, packaging, merchandising groups, variant attributes, items, batches.'")
    for statement in _statements(_TABLES):
        op.execute(statement)
    for table in _ENTITY_TABLES:
        op.execute(f"CREATE UNIQUE INDEX ix_catalogue_{table}_uuid ON catalogue.{table} (uuid)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_deleted_at ON catalogue.{table} (deleted_at)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_status ON catalogue.{table} (status)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_tenant_id ON catalogue.{table} (tenant_id)")
        op.execute(f"CREATE INDEX ix_{table}_tenant_org ON catalogue.{table} (tenant_id, organization_id)")
    for statement in _statements(_UQC_SEED) + _statements(_SEED_FUNCTION):
        op.execute(statement)
    for statement in _PROVISIONING:
        op.execute(statement)

    bind = op.get_bind()
    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_organizations_seed_catalogue ON org_management.organizations")
    op.execute("DROP FUNCTION IF EXISTS catalogue.on_organization_created()")
    op.execute("DROP FUNCTION IF EXISTS catalogue.seed_standard_units(bigint, bigint)")
    for table in ("attribute_options", "attributes", "item_groups", "sales_channels", "packaging_types",
                  "units", "uqc_codes"):
        op.execute(f"DROP TABLE IF EXISTS catalogue.{table}")
    op.execute("DROP SCHEMA IF EXISTS catalogue")
'''

def _comments() -> str:
    """COMMENT ON statements taken from the ORM models (mixin column comments included), so the
    database's comments equal the models' and `alembic check` reports nothing for the catalogue."""
    import sys

    sys.path.insert(0, "/home/a2/projects/th-middleware/apps/core-platform/backend")
    from app.database.db import Base
    import app.modules.catalogue.model  # noqa: F401

    def lit(value):
        return "NULL" if value is None else "'" + value.replace("'", "''") + "'"

    lines = []
    for name in ("uqc_codes", "units", "packaging_types", "sales_channels", "item_groups", "attributes",
                 "attribute_options"):
        table = Base.metadata.tables[f"catalogue.{name}"]
        lines.append(f"COMMENT ON TABLE catalogue.{name} IS {lit(table.comment)};")
        for column in table.columns:
            lines.append(f"COMMENT ON COLUMN catalogue.{name}.{column.name} IS {lit(column.comment)};")
    return "\n".join(lines)


TEMPLATE = TEMPLATE.replace(
    "    for table in _ENTITY_TABLES:\n",
    "    for statement in _statements(_COMMENTS):\n        op.execute(statement)\n    for table in _ENTITY_TABLES:\n",
).replace('_UQC_SEED = r"""', '_COMMENTS = r"""\n__COMMENTS__\n"""\n\n_UQC_SEED = r"""')

text = (TEMPLATE.replace("__TABLES__", tables.strip()).replace("__COMMENTS__", _comments())
        .replace("__UQC__", uqc_seed.strip())
        .replace("__SEED__", seed_fn.strip()))
OUT.write_text(text, encoding="utf-8", newline="\n")
print(OUT, len(text))
