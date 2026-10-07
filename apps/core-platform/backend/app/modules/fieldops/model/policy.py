"""Policy layers — what a field worker MUST do, and how the field app behaves (obligations + client config).

What a user MAY do is RBAC (``fieldops.field_work:use`` …). What they MUST do — run a shift, be tracked,
be inside the fence, use one device — does not compose by union the way permissions do, so it lives
here (docs/fieldops/field-app-integration-plan.md §4).

``PolicyLayer``  a SPARSE set of settings (``settings`` JSONB, keys from ``policy/settings.py``) with a
                 TARGET: ``organization`` (the layer is that organization's fallback for its whole
                 subtree; at the root organization it is the tenant default) or ``role`` / ``team`` /
                 ``hub`` / ``beat`` / ``user`` within that organization's subtree. ``scope_id`` is
                 polymorphic and has no FK — validated on write by the dimension registry.
                 Layers merge PER SETTING FIELD from general to specific over the code defaults
                 (``policy/resolver.py``). ``locked_keys`` stop narrower layers from overriding.
``PolicyEpoch``  one counter per tenant, bumped in the same transaction as any layer write: the
                 config version the app sees (monotonic whichever layer wins) and the cache key.

This replaced ``fieldops.work_policies`` (one whole row per organization × role, winner takes all)
in migration ``b7e4c1a9d3f2``. A shift still freezes what applied at its start
(``shifts.policy_snapshot``).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import AppMetaMixin, BigIntPKWithUUIDv7Mixin, IntPKMixin, MultiTenantMixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.fieldops.enums import FIELDOPS_SCHEMA, values
from app.modules.fieldops.policy.settings import Scope


class PolicyLayer(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "policy_layers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_policy_layers_tenant_id"),
        CheckConstraint(f"scope_type IN ({values(Scope)})", name="chk_policy_layers_scope_type"),
        CheckConstraint("(scope_type = 'organization') = (scope_id IS NULL)", name="chk_policy_layers_scope_id"),
        CheckConstraint("status IN ('active','inactive')", name="chk_policy_layers_status"),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="chk_policy_layers_settings_object"),
        CheckConstraint("effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from",
                        name="chk_policy_layers_window"),
        # One live layer per target per start instant; a scheduled change is a second row with a later start.
        Index("uq_policy_layers_target_live", "tenant_id", "organization_id", "scope_type",
              text("COALESCE(scope_id, 0)"), text("COALESCE(effective_from, '-infinity'::timestamptz)"),
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_policy_layers_lookup", "tenant_id", "scope_type", "scope_id",
              postgresql_where=text("deleted_at IS NULL AND status = 'active'")),
        {"schema": FIELDOPS_SCHEMA,
         "comment": "Sparse policy layers (organization/role/team/hub/beat/user), merged per setting."},
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[int | None] = mapped_column(BigInteger, comment="Target id (roles/teams/hubs/beats/users); "
                                                                     "NULL for an organization layer. No FK.")
    settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Sparse {setting_key: value}; group values hold only the fields this layer sets",
    )
    locked_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]"),
        comment="Setting keys (or key.field) narrower layers may not override",
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"),
                                          comment="Tie-breaker between layers of the same rank and depth")
    effective_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active",
                                        server_default=text("'active'"))

    def __repr__(self) -> str:
        return f"<PolicyLayer id={self.id} org={self.organization_id} {self.scope_type}:{self.scope_id} {self.name!r}>"


class PolicyEpoch(IntPKMixin, MultiTenantMixin, AppMetaMixin, Base):
    """Per-tenant monotonic version of the policy layers — ONE row per tenant (``uq_policy_epochs_tenant``),
    held at the tenant's root organization. LEDGER-shaped: written only by the Core
    ``INSERT … ON CONFLICT … RETURNING`` in ``resolver.bump_epoch``, inside the layer write's transaction."""

    __tablename__ = "policy_epochs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_policy_epochs_tenant"),
        {"schema": FIELDOPS_SCHEMA, "comment": "Per-tenant policy version (bumped on layer writes)."},
    )

    epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default=text("1"))
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                    server_default=text("now()"))


__all__ = ["PolicyEpoch", "PolicyLayer"]
