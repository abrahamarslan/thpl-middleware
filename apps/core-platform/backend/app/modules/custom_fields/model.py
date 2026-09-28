"""Custom-fields engine (schema ``extfields``) — a typed, registry-driven
key/value store that lets any registered entity type carry a growing set of
custom fields without schema churn.

    DataType         GLOBAL  Zoho's custom-field data_type vocabulary, mapped to
                             the typed column on ``field_values`` that holds the
                             value. Lookup, not CHECK (AP8) — the source
                             vocabulary grows with a seed row, not a migration.
    FieldDefinition  ENTITY  one custom field *definition* (Class F): name,
                             type, rules and DPDP classification. Definition
                             data only — it never carries a value.
    FieldValue       ENTITY  one custom-field *answer* per (field, owner). The
                             value lives in exactly one of five typed columns.

Owner registry. Unlike the reference design's dedicated ``owner_types`` table,
the owner-type vocabulary is the shared ``core.entity_types`` registry
(``code`` -> ``target_schema.target_table``): ``field_definitions.owner_type_code``
and ``field_values.owner_type_code`` are real FKs to ``core.entity_types.code``,
so registering a new owner class is a registry row, not DDL — the same choice
the categories plan makes (D2).

Polymorphic integrity. ``field_values.owner_id`` has no real FK: no single target
table exists. Integrity rests on (a) the ``core.entity_types`` FK proving the
*class* is registered, (b) ``ck_field_values_single_value`` (at most one typed
column), and (c) the deferred ``extfields.check_field_value_integrity()``
constraint trigger, which proves the *instance* exists via the existing
``core.assert_entity_exists()`` AND that the populated column matches the
definition's data type. ``extfields.find_orphan_field_values()`` is the
scheduled safety net.

DPDP. ``field_definitions.pii_type`` classifies what a definition collects and
drives erasure of every value under it. It is classification metadata, not
personal data itself.

Scoping. ``data_types`` is global reference data (like ``document_types``); the
two entity tables are ``OrgEntityMixin`` (``tenant_id`` + ``organization_id``
NOT NULL). A value's composite FK to its definition pins scope AND owner type at
once, so a value can never answer another organization's definition.

Loaders: every relationship is ``lazy="raise"``; list reads use ``load_only``.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    OrgEntityMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.custom_fields.enums import (
    EXTFIELDS_SCHEMA,
    PiiType,
    StorageColumn,
    values,
)
from app.modules.entities.enums import CORE_SCHEMA

_LIVE = text("deleted_at IS NULL")
_STORAGE_CHECK = f"storage_column IN ({values(StorageColumn)})"
_PII_CHECK = f"pii_type IS NULL OR pii_type IN ({values(PiiType)})"
_SINGLE_VALUE_CHECK = (
    "num_nonnulls(value_text, value_numeric, value_date, value_boolean, value_json) <= 1"
)


class DataType(BigIntPKWithUUIDv7Mixin, AuditMixin, TimestampMixin, SoftDeleteFilteredMixin, Base):
    """Zoho custom-field data_type vocabulary -> storage-column mapping (GLOBAL).

    The lookup indirection is the point: ``code`` is open (a new Zoho type is a
    seed row), while ``storage_column`` names one of five real columns and is
    CHECK-constrained.
    """

    __tablename__ = "data_types"
    __table_args__ = (
        CheckConstraint(_STORAGE_CHECK, name="ck_data_types_storage_column"),
        # One live row per code; a retired code can be reused after soft-delete.
        Index("uq_data_types_code", "code", unique=True, postgresql_where=_LIVE),
        {
            "schema": EXTFIELDS_SCHEMA,
            "comment": "Zoho custom-field data_type vocabulary mapped to which typed column on "
                       "field_values holds it. Global lookup, not CHECK (AP8).",
        },
    )

    code: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Zoho data_type code, e.g. 'amount', 'multiselect'. P0.",
    )
    label: Mapped[str | None] = mapped_column(
        Text, comment="Human-readable label, e.g. 'Amount'. P0.",
    )
    storage_column: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Which typed column on field_values stores this data type. P0.",
    )

    field_definitions: Mapped[list[FieldDefinition]] = relationship(
        "FieldDefinition", back_populates="data_type", lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<DataType id={self.id} code={self.code!r} -> {self.storage_column}>"


class FieldDefinition(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One custom-field definition (Class F): schema, behavior and policy.

    Never carries a value; ``is_custom_field`` is dropped because every row here
    is a custom field by construction. ``owner_type_code`` is a FK to the shared
    ``core.entity_types`` registry. ``pii_type`` drives DPDP erasure.
    """

    __tablename__ = "field_definitions"
    __table_args__ = (
        # Targets of the self FKs and of field_values' composite FK.
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_field_definitions_scope_id"),
        UniqueConstraint("tenant_id", "organization_id", "owner_type_code", "id",
                         name="uq_field_definitions_owner_scope_id"),
        CheckConstraint(_PII_CHECK, name="ck_field_definitions_pii_type"),
        CheckConstraint("depends_on_field_id IS NULL OR depends_on_field_id <> id",
                        name="ck_field_definitions_no_self_dependency"),
        CheckConstraint("sort_order IS NULL OR sort_order >= 0", name="ck_field_definitions_sort_order"),
        CheckConstraint("max_length IS NULL OR max_length > 0", name="ck_field_definitions_max_length"),
        CheckConstraint("precision IS NULL OR (precision >= 0 AND precision <= 38)",
                        name="ck_field_definitions_precision"),
        # A dependency must be a field of the same scope (MATCH SIMPLE skips NULL).
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "depends_on_field_id"],
            [f"{EXTFIELDS_SCHEMA}.field_definitions.tenant_id",
             f"{EXTFIELDS_SCHEMA}.field_definitions.organization_id",
             f"{EXTFIELDS_SCHEMA}.field_definitions.id"],
            name="fk_field_definitions_depends_on", ondelete="RESTRICT",
        ),
        # One live api_name per (organization, owner type).
        Index("uq_field_definitions_scope_apiname",
              "tenant_id", "organization_id", "owner_type_code", "api_name",
              unique=True, postgresql_where=_LIVE),
        Index("ix_field_definitions_owner", "tenant_id", "organization_id", "owner_type_code",
              postgresql_where=_LIVE),
        {
            "schema": EXTFIELDS_SCHEMA,
            "comment": "Custom field definitions (Class F). Definition data only; owner_type_code "
                       "FK to the shared core.entity_types registry.",
        },
    )

    owner_type_code: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{CORE_SCHEMA}.entity_types.code", ondelete="RESTRICT",
                         name="fk_field_definitions_owner_type"),
        nullable=False, comment="Registered entity type this field is defined for. P0.",
    )
    data_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{EXTFIELDS_SCHEMA}.data_types.id", ondelete="RESTRICT",
                               name="fk_field_definitions_data_type"),
        nullable=False, comment="Field data type; selects the storage column on field_values. P0.",
    )
    api_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Stable machine name, unique per owner type. P0.",
    )
    label: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Human-readable field label. P0.",
    )

    # ---- presentation --------------------------------------------------------
    placeholder: Mapped[str | None] = mapped_column(Text, comment="Input placeholder text. P1.")
    help_text: Mapped[str | None] = mapped_column(Text, comment="Helper text shown with the field. P1.")
    default_value: Mapped[str | None] = mapped_column(Text, comment="Default value (text form). P1.")
    sort_order: Mapped[int | None] = mapped_column(Integer, comment="Display order within the owner type. P1.")

    # ---- validation ----------------------------------------------------------
    precision: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Decimal precision for numeric types. P1.",
    )
    max_length: Mapped[int | None] = mapped_column(
        Integer, comment="Maximum length for text types. P1.",
    )

    # ---- mandatory policy ----------------------------------------------------
    is_mandatory: Mapped[bool | None] = mapped_column(Boolean, comment="Field is required. P1.")
    is_mandatory_in_sales_item: Mapped[bool | None] = mapped_column(Boolean, comment="Required on sales items. P1.")
    is_mandatory_in_storefront: Mapped[bool | None] = mapped_column(Boolean, comment="Required on the storefront. P1.")
    is_mandatory_in_hp: Mapped[bool | None] = mapped_column(Boolean, comment="Required on the hosted page. P1.")

    # ---- visibility policy ---------------------------------------------------
    show_in_store: Mapped[bool | None] = mapped_column(Boolean, comment="Visible on the storefront. P1.")
    show_in_hp: Mapped[bool | None] = mapped_column(Boolean, comment="Visible on the hosted page. P1.")
    show_in_all_pdf: Mapped[bool | None] = mapped_column(Boolean, comment="Visible in all generated PDFs. P1.")
    edit_on_store: Mapped[bool | None] = mapped_column(Boolean, comment="Editable from the storefront. P1.")
    is_read_only: Mapped[bool | None] = mapped_column(Boolean, comment="Read-only (e.g. autonumber). P1.")
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, default=True, server_default=text("true"), comment="Field is active; NULL = unspecified. P1.",
    )

    # ---- dependency ----------------------------------------------------------
    is_dependent_field: Mapped[bool | None] = mapped_column(
        Boolean, comment="Value/visibility depends on another field. P1.",
    )
    depends_on_field_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The field this definition depends on (self-reference). P1.",
    )

    # ---- value behavior ------------------------------------------------------
    is_inherited_value: Mapped[bool | None] = mapped_column(Boolean, comment="Value may be inherited. P1.")
    is_basecurrency_amount: Mapped[bool | None] = mapped_column(
        Boolean, comment="Amount is expressed in the base currency. P1.",
    )

    # ---- DPDP ----------------------------------------------------------------
    pii_type: Mapped[str | None] = mapped_column(
        Text, comment="Drives DPDP erasure for every field_values row under this definition. P0.",
    )

    data_type: Mapped[DataType] = relationship(
        "DataType", back_populates="field_definitions", lazy="raise",
    )
    depends_on_field: Mapped[FieldDefinition | None] = relationship(
        "FieldDefinition", remote_side="FieldDefinition.id", viewonly=True, lazy="raise",
    )
    field_values: Mapped[list[FieldValue]] = relationship(
        "FieldValue", back_populates="field_definition", lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<FieldDefinition id={self.id} owner={self.owner_type_code!r} api_name={self.api_name!r}>"


class FieldValue(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One custom-field answer per (field, owner), in exactly one typed column.

    Which column is legal is determined by the definition's
    ``data_type.storage_column`` and enforced by the deferred
    ``extfields.check_field_value_integrity()`` trigger. ``owner_id`` carries no
    real FK (polymorphic tradeoff): the class is proven by the ``entity_types``
    FK, the instance by ``core.assert_entity_exists()`` at COMMIT, and
    ``find_orphan_field_values()`` reports any that leaked.
    """

    __tablename__ = "field_values"
    __table_args__ = (
        CheckConstraint(_SINGLE_VALUE_CHECK, name="ck_field_values_single_value"),
        # Pins scope AND owner type to the definition at once; also the FK to it.
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "owner_type_code", "field_definition_id"],
            [f"{EXTFIELDS_SCHEMA}.field_definitions.tenant_id",
             f"{EXTFIELDS_SCHEMA}.field_definitions.organization_id",
             f"{EXTFIELDS_SCHEMA}.field_definitions.owner_type_code",
             f"{EXTFIELDS_SCHEMA}.field_definitions.id"],
            name="fk_field_values_definition", ondelete="CASCADE",
        ),
        # One live value per (field, owner); soft-delete frees the slot.
        Index("uq_field_values_field_owner",
              "field_definition_id", "owner_type_code", "owner_id",
              unique=True, postgresql_where=_LIVE),
        # "Give me all custom fields of this entity".
        Index("ix_field_values_owner",
              "tenant_id", "organization_id", "owner_type_code", "owner_id",
              postgresql_where=_LIVE),
        {
            "schema": EXTFIELDS_SCHEMA,
            "comment": "One custom field answer per owner. owner_id has no real FK (polymorphic "
                       "tradeoff) -- integrity via core.entity_types + assert_entity_exists + "
                       "find_orphan_field_values().",
        },
    )

    field_definition_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The field this value answers. P0.",
    )
    owner_type_code: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{CORE_SCHEMA}.entity_types.code", ondelete="RESTRICT",
                         name="fk_field_values_owner_type"),
        nullable=False, comment="Registered entity type of the value's owner. P0.",
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="Internal id of the owning entity; polymorphic, no FK possible. P0.",
    )

    value_text: Mapped[str | None] = mapped_column(
        Text, comment="Text-typed value (text/email/phone/url/dropdown/autonumber/attachment). P0.",
    )
    value_numeric: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), comment="Numeric-typed value (amount/decimal/percent/number). P0.",
    )
    value_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Date/datetime-typed value. P0.",
    )
    value_boolean: Mapped[bool | None] = mapped_column(
        Boolean, comment="Checkbox-typed value. P0.",
    )
    value_json: Mapped[dict | list | None] = mapped_column(
        # none_as_null: a Python None must be SQL NULL, not JSON `null` — otherwise
        # an unanswered field would populate the column and trip the single-value CHECK.
        JSONB(none_as_null=True), comment="JSON-typed value (multiselect and structured values). P0.",
    )

    field_definition: Mapped[FieldDefinition] = relationship(
        "FieldDefinition", back_populates="field_values", lazy="raise",
    )

    def __repr__(self) -> str:
        return (
            f"<FieldValue id={self.id} field={self.field_definition_id} "
            f"owner={self.owner_type_code}:{self.owner_id}>"
        )


__all__ = ["DataType", "FieldDefinition", "FieldValue"]