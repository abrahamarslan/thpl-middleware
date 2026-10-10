"""The chart of accounts.

    AccountType   GLOBAL  the 46-code type vocabulary (Zoho's documented list ∪ the
                          tenant's own response). FK target BY CODE, so it is not
                          soft-deletable — a type is retired with ``is_enabled``.
    Account       ENTITY  one ledger account of one organization (``OrgEntityMixin``:
                          tenant + organization NOT NULL, composite FK to the
                          organization). Zoho-synced through the crosswalk.

Zoho provenance. ``Account`` is a crosswalk module: identity, the apply gate's fence and
hash, the raw document and the custom fields live in ``sync.sync_records`` — NOT here.
The one Zoho column is the ``zoho_id`` echo, written only by the engine
(``SyncContract.identity_echo``), never by hand, never the identity of record. It answers
"is this row Zoho-linked?", which every local edit asks (docs/implementation-plan/
sync-crosswalk-delta-v3.md §3). ``AccountType.zoho_id`` is Zoho's numeric type id, a
vendor-wide constant.

One activity signal. ``status`` (``active`` / ``inactive``) is the only one; Zoho's
``is_active`` maps onto it through a codec and ``is_active`` here is a read-only property.
No ``DeactivationMixin`` — a third signal is the contradiction the v2 design had to CHECK
away (docs/implementation-plan/accounts-module.md §5.2).

Derived, never written by the application (database triggers, migration
``accounting_chart_of_accounts``):

    normal_balance_is_debit   type's default side, inverted for a contra account
    depth                     0 for a root, parent's + 1 otherwise; cascaded on re-parent

Both are ``server_onupdate=FetchedValue()`` so the ORM reads them back after a write.

Integrity in the database, not only the service:

    fk_accounts_parent_scope     a parent is in the same tenant AND organization
    fk_accounts_currency         the currency is the same tenant's
    accounting.derive_account_fields()   cycle refusal, depth, normal side
    accounting.guard_account_delete()    no soft delete with live children / assignments

Type rules (sub-accounts allowed, parent in the same group) are the SERVICE's, applied
to local writes only: Zoho masters its own chart and a trigger that refused Zoho's data
would make our replica wrong, not Zoho right (§2.3 #6).

Loaders (stated): every relationship is ``lazy="raise"``; crud reads with explicit
``joinedload`` / ``load_only``. ``comments`` (``HasCommentsMixin``) is ``raise_on_sql``.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    HashGuardMixin,
    OrgEntityMixin,
    TimestampMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.accounting.enums import ACCOUNTING_SCHEMA, AccountGroup, AccountStatus, values
from app.modules.comments.mixins import HasCommentsMixin
# The FK targets must be mapped wherever an account is: a process that imports only this module (a seeder,
# a Celery task) would otherwise fail with NoReferencedTableError on currency.currencies.
from app.modules.currencies import model as _currency_model  # noqa: F401
from app.modules.entities import model as _entity_model  # noqa: F401

_LIVE = text("deleted_at IS NULL")


class AccountType(BigIntPKWithUUIDv7Mixin, AuditMixin, AppMetaMixin, TimestampMixin, Base):
    """One account type (``cost_of_goods_sold``, ``stock`` …) — global reference data."""

    __tablename__ = "account_types"
    __table_args__ = (
        UniqueConstraint("code", name="uq_account_types_code"),       # FK target: not partial
        Index("uq_account_types_zoho_id", "zoho_id", unique=True, postgresql_where=text("zoho_id IS NOT NULL")),
        CheckConstraint(f"account_group IN ({values(AccountGroup)})", name="ck_account_types_group"),
        CheckConstraint("btrim(code) <> ''", name="ck_account_types_code_not_blank"),
        {"schema": ACCOUNTING_SCHEMA,
         "comment": "Account type vocabulary (Zoho documented list ∪ the tenant's own response); global."},
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="Zoho account_type, e.g. 'stock'")
    zoho_id: Mapped[str | None] = mapped_column(
        String(16), comment="Zoho's numeric account-type id ('1'..'112'), a vendor constant; NULL = never reported",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, comment="Zoho account_type_formatted")
    account_group: Mapped[str] = mapped_column(String(16), nullable=False, comment="asset/liability/equity/income/expense")
    default_normal_balance_is_debit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, comment="true = debit-normal (asset, expense); drives accounts.normal_balance_is_debit",
    )
    is_sub_account_allowed: Mapped[bool | None] = mapped_column(
        Boolean, comment="Zoho rule; NULL = not reported by Zoho (the service allows, Zoho decides on push)",
    )
    can_show_opening_balance: Mapped[bool | None] = mapped_column(Boolean)
    can_enable_in_ze: Mapped[bool | None] = mapped_column(Boolean, comment="Usable in Zoho Expense")
    asset_type: Mapped[str | None] = mapped_column(String(32), comment="fixed_asset / cwip / iaud")
    is_documented: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="In the Zoho API docs' allowed values (false = observed only in a tenant response)",
    )
    is_sales_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                    server_default=text("false"), comment="Offered by the sales picker")
    is_purchase_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                       server_default=text("false"),
                                                       comment="Offered by the purchase picker")
    is_inventory_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                        server_default=text("false"),
                                                        comment="Offered by the inventory picker")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<AccountType {self.code!r} {self.account_group}>"


class Account(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin, HashGuardMixin, HasCommentsMixin,
    SoftDeleteFilteredMixin, Base,
):
    """One ledger account of one organization."""

    __tablename__ = "accounts"
    __commentable_type__ = "account"
    __table_args__ = (
        # Targets of the composite FKs into accounts (same organization / same tenant).
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_accounts_scope_id"),
        UniqueConstraint("tenant_id", "id", name="uq_accounts_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "parent_id"],
            [f"{ACCOUNTING_SCHEMA}.accounts.tenant_id", f"{ACCOUNTING_SCHEMA}.accounts.organization_id",
             f"{ACCOUNTING_SCHEMA}.accounts.id"],
            name="fk_accounts_parent_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "currency_id"], ["currency.currencies.tenant_id", "currency.currencies.id"],
            name="fk_accounts_currency", ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN ({values(AccountStatus)})", name="ck_accounts_status"),
        CheckConstraint("btrim(account_name) <> ''", name="ck_accounts_name_not_blank"),
        CheckConstraint("account_code IS NULL OR btrim(account_code) <> ''", name="ck_accounts_code_not_blank"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_accounts_not_own_parent"),
        CheckConstraint("depth >= 0", name="ck_accounts_depth_nonneg"),
        CheckConstraint("(parent_id IS NULL) = (depth = 0)", name="ck_accounts_depth_root"),
        Index("uq_accounts_code", "organization_id", "account_code", unique=True,
              postgresql_where=text("deleted_at IS NULL AND account_code IS NOT NULL")),
        Index("uq_accounts_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_accounts_org_type", "organization_id", "account_type", postgresql_where=_LIVE),
        Index("ix_accounts_parent", "parent_id", postgresql_where=_LIVE),
        Index("ix_accounts_name_trgm", "account_name", postgresql_using="gin",
              postgresql_ops={"account_name": "gin_trgm_ops"}, postgresql_where=_LIVE),
        {"schema": ACCOUNTING_SCHEMA,
         "comment": "Chart of accounts: one ledger account of one organization; Zoho-synced (crosswalk)."},
    )

    account_type: Mapped[str] = mapped_column(
        String(64), ForeignKey(f"{ACCOUNTING_SCHEMA}.account_types.code", ondelete="RESTRICT",
                               name="fk_accounts_account_type"),
        nullable=False, comment="accounting.account_types.code — an unknown Zoho type fails that one record",
    )
    parent_id: Mapped[int | None] = mapped_column(BigInteger, comment="Parent account (same organization); NULL = root")
    account_code: Mapped[str | None] = mapped_column(Text, comment="Opaque GL code; leading zeros kept; blank = NULL")
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(
        Text,
        Computed("CASE WHEN account_code IS NULL THEN account_name ELSE account_code || ' - ' || account_name END",
                 persisted=True),
        comment="code - name, for pickers and search (generated)",
    )
    description: Mapped[str | None] = mapped_column(Text)
    currency_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="currency.currencies; NULL = the organization's base currency",
    )
    is_contra: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Contra account: its normal side is the opposite of its type's (accumulated depreciation)",
    )
    normal_balance_is_debit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), server_onupdate=FetchedValue(),
        comment="DERIVED by trigger from the type and is_contra — never written by the application",
    )
    depth: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), server_onupdate=FetchedValue(),
        comment="DERIVED by trigger: 0 for a root, parent's depth + 1; cascaded on re-parent",
    )
    is_system_account: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Zoho system account: cannot be deleted or re-typed",
    )
    is_user_created: Mapped[bool | None] = mapped_column(Boolean, comment="Zoho is_user_created; NULL = not reported")
    placeholder: Mapped[str | None] = mapped_column(
        Text, comment="Zoho's slug of the account name (gl_laptop, gl_goods_in_transit) — NOT a system-role marker "
                      "(verified on THPL: slugs of user-created names)",
    )
    is_expense_claim_enabled: Mapped[bool | None] = mapped_column(Boolean, comment="Zoho can_show_in_ze")
    show_on_dashboard: Mapped[bool | None] = mapped_column(Boolean)
    is_register_supported: Mapped[bool | None] = mapped_column(
        Boolean, comment="Zoho is_register_supported_account: the account shows a transaction register",
    )
    is_standalone: Mapped[bool | None] = mapped_column(Boolean, comment="Zoho is_standalone_account")
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Engine-maintained echo of Zoho account_id (not the identity of record)",
    )

    type_ref: Mapped[AccountType] = relationship(
        "AccountType", primaryjoin="foreign(Account.account_type) == AccountType.code",
        viewonly=True, lazy="raise",
    )
    parent: Mapped[Account | None] = relationship(
        "Account", primaryjoin="foreign(Account.parent_id) == Account.id", remote_side="Account.id",
        viewonly=True, lazy="raise",
    )

    @property
    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE.value

    @property
    def is_zoho_linked(self) -> bool:
        return self.zoho_id is not None

    def __repr__(self) -> str:
        return f"<Account id={self.id} {self.display_name!r} type={self.account_type}>"


__all__ = ["Account", "AccountType"]
