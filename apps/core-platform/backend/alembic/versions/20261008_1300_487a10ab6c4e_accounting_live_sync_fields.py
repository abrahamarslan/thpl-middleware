"""Accounting: the two Zoho account flags the live chart carries, and a source's account id kept on its links.

Found by comparing the synced chart with live Zoho (THPL, 2026-10-08):

  * ``is_register_supported_account`` (228 of 231 true) and ``is_standalone_account`` (35 true) arrive in
    EVERY live ``/chartofaccounts`` list row (not in Zoho's documented example) and were kept only in the
    crosswalk's raw document. They become ``accounts.is_register_supported`` / ``accounts.is_standalone``
    (Zoho-owned, IN), filled here from ``sync.sync_records.raw`` — zero API calls, and needed because the
    apply gate skips unchanged rows, so the next sync would never write them.
  * ``accounts.placeholder`` is Zoho's slug of the account NAME (``gl_laptop``, ``gl_racks`` …) — the
    comment no longer calls it a system-account key, which the live chart disproved.
  * ``account_assignments.external_ref`` held the source's account id only while a link was PENDING. A
    Zoho-fed link now keeps it always (redesign §4.1 step 3), so every row says which Zoho account it came
    from; existing resolved Zoho rows are filled from the linked account's ``zoho_id`` echo.

Downgrade drops the two columns; ``external_ref`` values stay (they are correct either way).

Revision ID: 487a10ab6c4e
Revises: e4c737170f12
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "487a10ab6c4e"
down_revision: str | None = "e4c737170f12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXTERNAL_REF_NEW = ("The source's id for the account (e.g. Zoho account_id) — kept on every source-fed row, "
                     "resolved or pending; the reconcile lane links a pending one")
_EXTERNAL_REF_OLD = "The source's id for the account while it is unresolved; the reconcile lane links it"
_PLACEHOLDER_OLD = "Zoho template slug (gl_goods_in_transit): the robust key for recognising system accounts"
_PLACEHOLDER_NEW = ("Zoho's slug of the account name (gl_laptop, gl_goods_in_transit) — NOT a system-role marker "
                    "(verified on THPL: slugs of user-created names)")


def upgrade() -> None:
    op.add_column("accounts", sa.Column(
        "is_register_supported", sa.Boolean(), nullable=True,
        comment="Zoho is_register_supported_account: the account shows a transaction register"), schema="accounting")
    op.add_column("accounts", sa.Column(
        "is_standalone", sa.Boolean(), nullable=True, comment="Zoho is_standalone_account"), schema="accounting")
    op.alter_column("account_assignments", "external_ref", schema="accounting", existing_type=sa.Text(),
                    comment=_EXTERNAL_REF_NEW, existing_comment=_EXTERNAL_REF_OLD)
    op.alter_column("accounts", "placeholder", schema="accounting", existing_type=sa.Text(),
                    comment=_PLACEHOLDER_NEW, existing_comment=_PLACEHOLDER_OLD)

    # Fill from the stored documents (Zoho sends booleans; a string "true" is tolerated like the codec does).
    op.execute("""
        UPDATE accounting.accounts a
           SET is_register_supported = lower(r.raw->>'is_register_supported_account') = 'true',
               is_standalone         = lower(r.raw->>'is_standalone_account') = 'true'
          FROM sync.sync_records r
         WHERE r.module = 'chart_of_accounts' AND r.source_system = 'zoho'
           AND r.entity_table = 'accounting.accounts' AND r.entity_id = a.id
           AND r.raw ? 'is_register_supported_account'
    """)
    op.execute("""
        UPDATE accounting.account_assignments x
           SET external_ref = a.zoho_id
          FROM accounting.accounts a
         WHERE x.account_id = a.id AND x.source_system = 'zoho' AND x.external_ref IS NULL
           AND a.zoho_id IS NOT NULL
    """)


def downgrade() -> None:
    op.alter_column("accounts", "placeholder", schema="accounting", existing_type=sa.Text(),
                    comment=_PLACEHOLDER_OLD, existing_comment=_PLACEHOLDER_NEW)
    op.alter_column("account_assignments", "external_ref", schema="accounting", existing_type=sa.Text(),
                    comment=_EXTERNAL_REF_OLD, existing_comment=_EXTERNAL_REF_NEW)
    op.drop_column("accounts", "is_standalone", schema="accounting")
    op.drop_column("accounts", "is_register_supported", schema="accounting")
