"""Account assignments — "this entity uses this account for this purpose", for ANY entity.

    AccountPurpose        GLOBAL  why an entity points at an account (``sales``,
                                  ``receivable``, ``output_tax`` …) and which account
                                  groups/types may answer it.
    AccountPurposePolicy  GLOBAL  which entity classes may carry which purposes (one row
                                  per class × purpose) — the opt-in list, written by the
                                  owning module's migration
                                  (``registration.register_account_owner_type``).
    AccountAssignment     ENTITY  the polymorphic row: an owner (``owner_type_code`` +
                                  ``owner_id``) → an account, for a purpose (and optionally
                                  a currency).

The ``tax.tax_assignments`` shape, for accounts (docs/implementation-plan/accounts-module.md
§5.6). Separate tables on purpose: taxes carry contexts, exemptions, ordered groups and
frozen snapshots; accounts carry a purpose and a currency. They meet at READ time, in the
resolution engine (``app.modules.resolution``).

Organization defaults are assignments too: owner ``("organization", org.id)``. One table
replaces v2's ``account_roles`` + role assignments, the inventory-preference account
columns and the ``is_retained_earnings``-style singleton flags; "one retained-earnings
account" is simply the slot ``(organization, X, retained_earnings, NULL)``.

**Why ``organization_id`` is part of the slot.** Some owners are tenant-wide
(``tax.tax_components``: ``organization_id`` NULL = shared). Charts of accounts are
per-organization, so one CGST component posts to account X in organization A and Y in
organization B: an assignment belongs to the organization of its ACCOUNT, and an owner may
be in that organization or tenant-wide (``core.assert_owner_scope``).

Integrity (database-authoritative, pre-flighted by ``assignment_service``):

  * ``(owner_type_code, purpose_code)`` FK → ``account_purpose_policies``: the class is
    registered AND opted in to this purpose;
  * ``(tenant_id, organization_id, account_id)`` FK → ``accounts``: same organization;
  * ``accounting.check_account_assignment_integrity()`` (deferred): the owner exists, is in
    scope, the policy is enabled, the account's group/type fits the purpose, a currency
    only where the purpose is per-currency;
  * ``accounting.find_orphan_account_assignments()``: the scheduled safety net.

A row may be *pending*: a source (Zoho) named an account we have not synced yet —
``account_id`` NULL, ``external_ref`` = the source's id; the generic reconcile lane
(``sync.pending_references``) links it. Pending rows never answer a resolution.

Loaders: ``account`` is ``lazy="raise"``; read with ``joinedload``.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    OrgEntityMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.accounting.enums import ACCOUNTING_SCHEMA
from app.modules.accounting.model import Account
from app.modules.entities.enums import CORE_SCHEMA

_LIVE = text("deleted_at IS NULL")


class AccountPurpose(BigIntPKWithUUIDv7Mixin, AuditMixin, AppMetaMixin, TimestampMixin, Base):
    """Why an entity points at an account — global vocabulary, seeded by the migration."""

    __tablename__ = "account_purposes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_account_purposes_code"),     # FK target: not partial
        CheckConstraint("btrim(code) <> ''", name="ck_account_purposes_code_not_blank"),
        CheckConstraint("cardinality(allowed_groups) > 0", name="ck_account_purposes_groups"),
        {"schema": ACCOUNTING_SCHEMA, "comment": "Why an entity points at an account (global vocabulary)."},
    )

    code: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    allowed_groups: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), nullable=False, comment="The assigned account's group must be one of these",
    )
    allowed_types: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(64)), comment="Narrower rule: the account's type must be one of these; NULL = any of the groups",
    )
    per_currency: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="true = one account per (owner, purpose, currency) — AR/AP control accounts",
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<AccountPurpose {self.code!r} groups={self.allowed_groups}>"


class AccountPurposePolicy(BigIntPKWithUUIDv7Mixin, AuditMixin, AppMetaMixin, TimestampMixin, Base):
    """Which entity class may carry which purpose (global policy, one row per class × purpose)."""

    __tablename__ = "account_purpose_policies"
    __table_args__ = (
        # FK target of the assignment's (owner_type_code, purpose_code): not partial.
        UniqueConstraint("entity_type_code", "purpose_code", name="uq_account_purpose_policies_class_purpose"),
        {"schema": ACCOUNTING_SCHEMA,
         "comment": "Which entity classes may carry which account purposes (global policy)."},
    )

    entity_type_code: Mapped[str] = mapped_column(
        String(64), ForeignKey(f"{CORE_SCHEMA}.entity_types.code", ondelete="RESTRICT",
                               name="fk_account_purpose_policies_entity_type"),
        nullable=False, comment="core.entity_types.code — the class must be registered first",
    )
    purpose_code: Mapped[str] = mapped_column(
        String(48), ForeignKey(f"{ACCOUNTING_SCHEMA}.account_purposes.code", ondelete="RESTRICT",
                               name="fk_account_purpose_policies_purpose"),
        nullable=False,
    )
    falls_back_to_organization: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="When this owner carries nothing for the purpose, resolution asks the organization",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="false = no NEW assignments for this class and purpose; existing rows stay valid",
    )
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<AccountPurposePolicy {self.entity_type_code}:{self.purpose_code}>"


class AccountAssignment(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One account an entity uses for one purpose (optionally in one currency)."""

    __tablename__ = "account_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_type_code", "purpose_code"],
            [f"{ACCOUNTING_SCHEMA}.account_purpose_policies.entity_type_code",
             f"{ACCOUNTING_SCHEMA}.account_purpose_policies.purpose_code"],
            name="fk_account_assignments_policy", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "account_id"],
            [f"{ACCOUNTING_SCHEMA}.accounts.tenant_id", f"{ACCOUNTING_SCHEMA}.accounts.organization_id",
             f"{ACCOUNTING_SCHEMA}.accounts.id"],
            name="fk_account_assignments_account", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "currency_id"], ["currency.currencies.tenant_id", "currency.currencies.id"],
            name="fk_account_assignments_currency", ondelete="RESTRICT",
        ),
        CheckConstraint(
            "account_id IS NOT NULL OR (external_ref IS NOT NULL AND source_system IS NOT NULL)",
            name="ck_account_assignments_target",
        ),
        CheckConstraint("owner_id > 0", name="ck_account_assignments_owner_id"),
        CheckConstraint("source_system IS NULL OR btrim(source_system) <> ''",
                        name="ck_account_assignments_source_not_blank"),
        # One account per slot per organization; "any currency" (NULL) collides with itself.
        Index("uq_account_assignments_slot", "organization_id", "owner_type_code", "owner_id", "purpose_code",
              "currency_id", unique=True, postgresql_nulls_not_distinct=True, postgresql_where=_LIVE),
        Index("ix_account_assignments_owner", "owner_type_code", "owner_id", postgresql_where=_LIVE),
        Index("ix_account_assignments_account", "account_id",
              postgresql_where=text("deleted_at IS NULL AND account_id IS NOT NULL")),
        {"schema": ACCOUNTING_SCHEMA,
         "comment": "Polymorphic account assignment: an owning entity → an account, for a purpose."},
    )

    owner_type_code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="core.entity_types.code of the owner, opted in per purpose",
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The owner's internal id; no FK (polymorphic) — proved at COMMIT",
    )
    purpose_code: Mapped[str] = mapped_column(String(48), nullable=False, comment="accounting.account_purposes.code")
    account_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The account; NULL only while a source's account is pending",
    )
    currency_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Only for per-currency purposes; NULL = any / base currency",
    )
    external_ref: Mapped[str | None] = mapped_column(
        Text, comment="The source's id for the account (e.g. Zoho account_id) — kept on every source-fed row, "
                      "resolved or pending; the reconcile lane links a pending one",
    )
    source_system: Mapped[str | None] = mapped_column(
        String(32), comment="NULL = maintained locally; 'zoho' = fed by a sync (read-only through the API)",
    )

    account: Mapped[Account | None] = relationship(
        "Account", primaryjoin="foreign(AccountAssignment.account_id) == Account.id", viewonly=True, lazy="raise",
    )

    @property
    def is_pending(self) -> bool:
        return self.account_id is None

    @property
    def owner_ref(self) -> tuple[str, int]:
        return self.owner_type_code, self.owner_id

    def __repr__(self) -> str:
        target = f"account={self.account_id}" if self.account_id is not None else f"pending={self.external_ref!r}"
        return f"<AccountAssignment {self.owner_type_code}:{self.owner_id} {self.purpose_code} {target}>"


__all__ = ["AccountAssignment", "AccountPurpose", "AccountPurposePolicy"]
