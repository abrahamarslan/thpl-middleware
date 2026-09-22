"""``core`` registry tables — the entity-type catalogue and polymorphic aliases.

    EntityType   the closed catalogue of entity types a polymorphic reference
                 (an alias, an owner pair) may name. ``code`` is the stable key
                 other tables FK to; ``target_schema``/``target_table`` let a
                 deferred trigger prove the referenced row actually exists.
    EntityAlias  alternative names for any registered entity (a brand's former
                 name, a manufacturer's misspelling). Integrity is the
                 registry's: ``entity_id`` cannot carry a real FK because the
                 target table varies, so ``core.check_entity_alias()`` (a
                 deferrable constraint trigger) validates it instead and
                 ``core.find_orphan_entity_aliases()`` reports what leaked.

Scoping. ``entity_types`` is global reference data (like ``tax.gst_treatment_types``):
one catalogue for the whole platform. ``entity_aliases`` is tenant-scoped
(``TenantScopedMixin``: ``tenant_id`` NOT NULL, ``organization_id`` optional) so
a tenant's aliases never leak across tenants.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    TenantScopedMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.entities.enums import CORE_SCHEMA, EntityAliasKind, values

_LIVE = text("deleted_at IS NULL")


class EntityType(BigIntPKWithUUIDv7Mixin, AuditMixin, TimestampMixin, SoftDeleteFilteredMixin, Base):
    """A registered entity type (``brand``, ``manufacturer``, …)."""

    __tablename__ = "entity_types"
    __table_args__ = (
        # Not partial: this is the FK target for entity_aliases.entity_type.
        UniqueConstraint("code", name="uq_entity_types_code"),
        CheckConstraint("btrim(code) <> ''", name="ck_entity_types_code_not_blank"),
        CheckConstraint("btrim(name) <> ''", name="ck_entity_types_name_not_blank"),
        CheckConstraint("btrim(target_schema) <> ''", name="ck_entity_types_target_schema_not_blank"),
        CheckConstraint("btrim(target_table) <> ''", name="ck_entity_types_target_table_not_blank"),
        {"schema": CORE_SCHEMA,
         "comment": "Catalogue of entity types polymorphic references may name."},
    )

    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Stable registry code, e.g. 'brand', 'manufacturer'",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, comment="Human-readable label")
    target_schema: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Schema of the table rows of this type live in",
    )
    target_table: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Table rows of this type live in",
    )
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<EntityType id={self.id} code={self.code!r} -> {self.target_schema}.{self.target_table}>"


class EntityAlias(BigIntPKWithUUIDv7Mixin, TenantScopedMixin, AuditMixin, AppMetaMixin, TimestampMixin,
                  SoftDeleteFilteredMixin, Base):
    """An alternative name for a registered entity."""

    __tablename__ = "entity_aliases"
    __table_args__ = (
        CheckConstraint("btrim(alias) <> ''", name="ck_entity_aliases_alias_not_blank"),
        CheckConstraint(
            f"kind IS NULL OR kind IN ({values(EntityAliasKind)})",
            name="ck_entity_aliases_kind",
        ),
        CheckConstraint(
            "language_code IS NULL OR language_code ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="ck_entity_aliases_language_code",
        ),
        # One live alias per entity per tenant (the alias_normalized is never NULL
        # because alias is NOT NULL).
        Index("uq_entity_aliases_current", "tenant_id", "entity_type", "entity_id", "alias_normalized",
              unique=True, postgresql_where=_LIVE),
        Index("ix_entity_aliases_lookup", "tenant_id", "entity_type", "alias_normalized",
              postgresql_where=_LIVE),
        Index("ix_entity_aliases_alias_trgm", "alias_normalized", postgresql_using="gin",
              postgresql_ops={"alias_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        {"schema": CORE_SCHEMA,
         "comment": "Alternative names for any registered entity (integrity via core.check_entity_alias)."},
    )

    entity_type: Mapped[str] = mapped_column(
        String(64), ForeignKey(f"{CORE_SCHEMA}.entity_types.code", ondelete="RESTRICT",
                               name="fk_entity_aliases_entity_type"),
        nullable=False, comment="Registry code from core.entity_types.code",
    )
    entity_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="Internal id of the target; no FK possible (polymorphic)",
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False, comment="Exactly as received")
    alias_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(r"lower(btrim(regexp_replace(alias, '\s+', ' ', 'g')))", persisted=True),
        comment="STORED generated lower-cased alias; lookup and trigram search",
    )
    kind: Mapped[str | None] = mapped_column(
        Text, comment="abbreviation / former_name / misspelling / translation / trade_name; NULL = unclassified",
    )
    language_code: Mapped[str | None] = mapped_column(String(16), comment="BCP-47 language tag")

    def __repr__(self) -> str:
        return f"<EntityAlias id={self.id} {self.entity_type}:{self.entity_id} alias={self.alias!r}>"


__all__ = ["EntityAlias", "EntityType"]
