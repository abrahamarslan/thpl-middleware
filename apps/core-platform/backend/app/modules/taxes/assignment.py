"""Tax assignments — "this entity carries these taxes", for ANY entity.

    TaxableEntityType   GLOBAL  which entity classes may carry taxes, and how
                                (one tax per context or several; exemptions or
                                not). The opt-in list. One row per class.
    TaxAssignment       ENTITY  the polymorphic row: an owner (``owner_type_code``
                                + ``owner_id``) → a tax component OR an exemption,
                                in a context (inter/intra, sales/purchase).

Why this shape. A category, an item, a customer and an invoice line all say "these
taxes apply to me" — and every one of them said it with its own column or its own
child table (Zoho's ``category_tax_preferences``, an item's ``tax_id``, a contact's
``tax_exemption_id``, a line's ``line_item_taxes``). One table serves them all:
a new taxable entity is a registry row + a policy row + ``HasTaxesMixin`` on its
model, never a migration to this schema (docs/implementation-plan/tax-assignments.md).

**Assignments are references, not amounts.** A row points at a live
``tax_components`` row, so a rate change reaches every category and item that
carries it. A document that has been ISSUED must not follow the rate, so an
assignment can be *frozen*: ``snapshot`` holds the tax as it was (name, rate,
type, and a group's members) and the row becomes immutable. Computed tax
AMOUNTS are the document module's — they depend on a base this table never sees.

Integrity is the registry's, exactly as for ``core.entity_aliases`` /
``extfields.field_values`` / ``core.categorizables``:

  * ``owner_type_code`` is a real FK to ``taxable_entity_types.entity_type_code``,
    which is itself a real FK to ``core.entity_types.code`` — so the class is
    registered AND opted in, in the database, at insert time;
  * ``owner_id`` has no FK (no single target table); the deferred
    ``tax.check_tax_assignment_integrity()`` proves the instance exists via
    ``core.assert_entity_exists()``, that it belongs to the SAME tenant and
    organization as the assignment, that the class's policy is honoured, and that
    the row does not break the class's cardinality rule;
  * ``tax.guard_frozen_tax_assignment()`` refuses to change a frozen row;
  * ``tax.find_orphan_tax_assignments()`` is the scheduled safety net.

A row may be *pending*: a source (Zoho) named a tax we have not synced yet.
``tax_component_id`` is then NULL and ``external_ref`` carries the source's id;
the generic reconcile lane (``sync.pending_references``) links it when the tax
arrives — no new machinery.

Scoping. ``OrgEntityMixin`` (tenant + organization NOT NULL): an assignment
belongs to the organization its owner does. The composite FKs to
``tax_components`` / ``tax_exemptions`` pin the tax to the same TENANT (a
component is tenant-wide; which organizations may use it is
``organization_tax_components``, checked by the service).

Loaders: every relationship is ``lazy="raise"``; ``HasTaxesMixin.tax_assignments``
is ``raise_on_sql`` and read with an explicit ``selectinload``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
from app.modules.entities.enums import CORE_SCHEMA
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.enums import TAX_SCHEMA, TaxSpecification, TaxTransactionType, values
from app.modules.taxes.exemption import TaxExemption

_LIVE = text("deleted_at IS NULL")

#: A row targets exactly one thing: a component, or an exemption — or, while a
#: source's tax has not been synced yet, nothing but the source's id.
_TARGET_CHECK = (
    "num_nonnulls(tax_component_id, tax_exemption_id) = 1 "
    "OR (tax_component_id IS NULL AND tax_exemption_id IS NULL "
    "AND external_ref IS NOT NULL AND source_system IS NOT NULL)"
)


class TaxableEntityType(BigIntPKWithUUIDv7Mixin, AuditMixin, AppMetaMixin, TimestampMixin, Base):
    """Which entity classes may carry taxes, and under what rule (GLOBAL policy).

    Global reference data (allow-listed in ``tests/test_tenancy.py``): whether an
    ``item`` can carry taxes is a platform fact, not a tenant preference. Rows are
    written by the migration / seeder of the module that owns the entity
    (``registration.register_taxable_entity_type``); there is no write API.

    Not soft-deletable on purpose: ``taxable_entity_types.entity_type_code`` is the
    FK target of ``tax_assignments.owner_type_code`` and PostgreSQL cannot
    reference a partial unique index. Retire a class with ``is_enabled = false``.
    """

    __tablename__ = "taxable_entity_types"
    __table_args__ = (
        UniqueConstraint("entity_type_code", name="uq_taxable_entity_types_code"),
        {"schema": TAX_SCHEMA, "comment": "Which entity classes may carry taxes, and under what rule (global)."},
    )

    entity_type_code: Mapped[str] = mapped_column(
        String(64), ForeignKey(f"{CORE_SCHEMA}.entity_types.code", ondelete="RESTRICT",
                               name="fk_taxable_entity_types_entity_type"),
        nullable=False, comment="core.entity_types.code — the class must be registered first",
    )
    allows_multiple: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="false = at most ONE tax per (owner, inter/intra, sales/purchase) context — Zoho's shape for "
                "categories, items and contacts; true = several apply together (an invoice line's IGST + cess)",
    )
    allows_exemption: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Whether this class may be assigned a tax exemption (items, contacts, lines: yes; categories: no)",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="false = no NEW assignments for this class; existing rows stay valid",
    )
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return (f"<TaxableEntityType {self.entity_type_code!r} multiple={self.allows_multiple} "
                f"exemption={self.allows_exemption} enabled={self.is_enabled}>")


class TaxAssignment(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One tax (or exemption) carried by one entity, in one context."""

    __tablename__ = "tax_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tax_component_id"],
            [f"{TAX_SCHEMA}.tax_components.tenant_id", f"{TAX_SCHEMA}.tax_components.id"],
            name="fk_tax_assignments_component", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tax_exemption_id"],
            [f"{TAX_SCHEMA}.tax_exemptions.tenant_id", f"{TAX_SCHEMA}.tax_exemptions.id"],
            name="fk_tax_assignments_exemption", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_type_code"], [f"{TAX_SCHEMA}.taxable_entity_types.entity_type_code"],
            name="fk_tax_assignments_owner_type", ondelete="RESTRICT",
        ),
        CheckConstraint(_TARGET_CHECK, name="ck_tax_assignments_target"),
        CheckConstraint(
            f"tax_specification IS NULL OR tax_specification IN ({values(TaxSpecification)})",
            name="ck_tax_assignments_specification",
        ),
        CheckConstraint(
            f"transaction_type IS NULL OR transaction_type IN ({values(TaxTransactionType)})",
            name="ck_tax_assignments_transaction_type",
        ),
        CheckConstraint("(frozen_at IS NULL) = (snapshot IS NULL)", name="ck_tax_assignments_frozen_pair"),
        CheckConstraint("owner_id > 0", name="ck_tax_assignments_owner_id"),
        CheckConstraint("position >= 0", name="ck_tax_assignments_position"),
        CheckConstraint("source_system IS NULL OR btrim(source_system) <> ''",
                        name="ck_tax_assignments_source_not_blank"),
        # No duplicate assignment of one tax to one owner in one context. NULLS NOT
        # DISTINCT: "any context" (NULL) must collide with itself.
        Index("uq_tax_assignments_component", "owner_type_code", "owner_id", "tax_component_id",
              "tax_specification", "transaction_type", unique=True, postgresql_nulls_not_distinct=True,
              postgresql_where=text("deleted_at IS NULL AND tax_component_id IS NOT NULL")),
        Index("uq_tax_assignments_exemption", "owner_type_code", "owner_id", "tax_exemption_id",
              "tax_specification", "transaction_type", unique=True, postgresql_nulls_not_distinct=True,
              postgresql_where=text("deleted_at IS NULL AND tax_exemption_id IS NOT NULL")),
        Index("uq_tax_assignments_pending", "owner_type_code", "owner_id", "source_system", "external_ref",
              "tax_specification", "transaction_type", unique=True, postgresql_nulls_not_distinct=True,
              postgresql_where=text("deleted_at IS NULL AND tax_component_id IS NULL "
                                    "AND tax_exemption_id IS NULL")),
        # The read path: "this owner's taxes".
        Index("ix_tax_assignments_owner", "owner_type_code", "owner_id", postgresql_where=_LIVE),
        # Impact analysis: "who carries this tax?" (a rate change, a retirement).
        Index("ix_tax_assignments_component", "tax_component_id",
              postgresql_where=text("deleted_at IS NULL AND tax_component_id IS NOT NULL")),
        Index("ix_tax_assignments_exemption", "tax_exemption_id",
              postgresql_where=text("deleted_at IS NULL AND tax_exemption_id IS NOT NULL")),
        {"schema": TAX_SCHEMA,
         "comment": "Polymorphic tax assignment: an owning entity → a tax component or exemption, in a context."},
    )

    # ---- whose ---------------------------------------------------------------
    owner_type_code: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="core.entity_types.code of the owning entity, opted in via tax.taxable_entity_types",
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The owner's internal id; no FK (polymorphic) — proved at COMMIT",
    )

    # ---- what ----------------------------------------------------------------
    tax_component_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="A tax rate or tax group; NULL for an exemption or while a source's tax is pending",
    )
    tax_exemption_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="An exemption instead of a tax (only for classes with allows_exemption)",
    )
    external_ref: Mapped[str | None] = mapped_column(
        Text, comment="The source's id for the tax while it is unresolved (tax_component_id NULL); "
                      "the reconcile lane links it",
    )

    # ---- when (the context it applies in) ---------------------------------------
    tax_specification: Mapped[str | None] = mapped_column(
        Text, comment="'inter' / 'intra'; NULL = any",
    )
    transaction_type: Mapped[str | None] = mapped_column(
        Text, comment="'sales' / 'purchase'; NULL = both",
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0"),
        comment="Order among the taxes of one owner (several taxes apply in this order)",
    )

    # ---- who wrote it ----------------------------------------------------------
    source_system: Mapped[str | None] = mapped_column(
        String(32), comment="NULL = maintained locally; 'zoho' = fed by the sync (read-only through the API)",
    )

    # ---- frozen snapshot -------------------------------------------------------
    snapshot: Mapped[dict | None] = mapped_column(
        JSONB, comment="The tax as it was when the owning document was issued (name, rate, type, group members)",
    )
    frozen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Set with snapshot; a frozen row can no longer change",
    )

    tax_component: Mapped[TaxComponent | None] = relationship(
        "TaxComponent",
        primaryjoin="foreign(TaxAssignment.tax_component_id) == TaxComponent.id",
        viewonly=True, lazy="raise",
    )
    tax_exemption: Mapped[TaxExemption | None] = relationship(
        "TaxExemption",
        primaryjoin="foreign(TaxAssignment.tax_exemption_id) == TaxExemption.id",
        viewonly=True, lazy="raise",
    )

    @property
    def is_pending(self) -> bool:
        return self.tax_component_id is None and self.tax_exemption_id is None

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None

    @property
    def owner_ref(self) -> tuple[str, int]:
        return self.owner_type_code, self.owner_id

    def __repr__(self) -> str:
        target = (f"component={self.tax_component_id}" if self.tax_component_id is not None
                  else f"exemption={self.tax_exemption_id}" if self.tax_exemption_id is not None
                  else f"pending={self.external_ref!r}")
        return (f"<TaxAssignment {self.owner_type_code}:{self.owner_id} {target} "
                f"spec={self.tax_specification} txn={self.transaction_type}>")


__all__ = ["TaxAssignment", "TaxableEntityType"]
