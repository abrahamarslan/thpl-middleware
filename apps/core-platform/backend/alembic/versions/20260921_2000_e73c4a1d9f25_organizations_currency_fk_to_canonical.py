"""Repoint organizations.currency_id at the canonical currency master

``fk_organizations_currency`` still referenced the old ``zoho_currencies``
mirror. Since currencies moved to the crosswalk architecture the sync writes
``currency.currencies``, so every organization whose payload carries a currency
failed its detail apply with:

    insert or update on table "organizations" violates foreign key constraint
    "fk_organizations_currency"
    DETAIL: Key (currency_id)=(105) is not present in table "zoho_currencies".

Found by running the sync for real rather than by reading the schema.

Existing values point at ``zoho_currencies`` ids, which are meaningless against
the new target, so they are translated where the crosswalk can identify the
same record and cleared where it cannot — a NULL here means "not yet linked",
which the sync repairs on its next run, whereas a wrong id would be silently
believed.

Revision ID: e73c4a1d9f25
Revises: d52a6f0bc318
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e73c4a1d9f25"
down_revision: str | None = "d52a6f0bc318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_organizations_currency"
_TABLE = "organizations"
_SCHEMA = "org_management"


def upgrade() -> None:
    op.drop_constraint(_FK, _TABLE, schema=_SCHEMA, type_="foreignkey")

    # Translate old mirror ids to canonical ids through the currency code, which
    # is the business key both tables agree on.
    op.execute(
        f"""
        UPDATE {_SCHEMA}.{_TABLE} o
        SET    currency_id = c.id
        FROM   zoho_currencies z
        JOIN   currency.currencies c
               ON c.tenant_id = z.tenant_id
              AND c.currency_code = z.currency_code
              AND c.deleted_at IS NULL
        WHERE  o.currency_id = z.id
        """
    )
    # Anything still pointing at a mirror row we could not translate is cleared;
    # zoho_currency_id stays on the row, so the next sync relinks it.
    op.execute(
        f"""
        UPDATE {_SCHEMA}.{_TABLE} o
        SET    currency_id = NULL
        WHERE  o.currency_id IS NOT NULL
          AND  NOT EXISTS (SELECT 1 FROM currency.currencies c WHERE c.id = o.currency_id)
        """
    )

    op.create_foreign_key(
        _FK, _TABLE, "currencies", ["currency_id"], ["id"],
        source_schema=_SCHEMA, referent_schema="currency", ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, _TABLE, schema=_SCHEMA, type_="foreignkey")
    op.execute(
        f"""
        UPDATE {_SCHEMA}.{_TABLE} o
        SET    currency_id = z.id
        FROM   currency.currencies c
        JOIN   zoho_currencies z
               ON z.tenant_id = c.tenant_id
              AND z.currency_code = c.currency_code
              AND z.deleted_at IS NULL
        WHERE  o.currency_id = c.id
        """
    )
    op.execute(
        f"""
        UPDATE {_SCHEMA}.{_TABLE} o
        SET    currency_id = NULL
        WHERE  o.currency_id IS NOT NULL
          AND  NOT EXISTS (SELECT 1 FROM zoho_currencies z WHERE z.id = o.currency_id)
        """
    )
    op.create_foreign_key(
        _FK, _TABLE, "zoho_currencies", ["currency_id"], ["id"],
        source_schema=_SCHEMA, ondelete="SET NULL",
    )
