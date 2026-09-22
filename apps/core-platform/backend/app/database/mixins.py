"""Reusable declarative model mixins.

Design decision — *mixins vs utilities*:
  - Cross-cutting COLUMNS (timestamps, soft delete, tenant, audit-user) are
    best expressed as **mixins**: they are pure schema, compose cleanly, and
    every table wants the same shape. That is what lives here.
  - Cross-cutting BEHAVIOUR that must never be forgotten (tenant filter,
    tenant/actor/app-version stamping) lives in ONE place:
    app/database/tenancy.py (session events). Business auditing stays an
    explicit utility (app/modules/activity/recorder.py).

Table classes (docs/tenancy/README.md §3) — every table is exactly one:

    ENTITY  TenantEntityMixin (= all of the below)            users, roles, files, mirrors, …
    LEDGER  TenantScopedMixin + AppMetaMixin                  logs, tokens, sync bookkeeping
    GLOBAL  none of the tenant mixins (allow-listed, reasoned) countries, timezones, settings catalog

Mix into a model in this order (most-specific first, Base last):

    class Foo(IntPKMixin, TenantEntityMixin, Base):
        __tablename__ = "foo"
        ...

Opt-in capabilities, added on top of the bundle only where a table needs them
(full catalogue: docs/tenancy/README.md §2):

    PolymorphicOwnerMixin   owner_type + owner_id, no FK (addresses, notes, attachments)
    HashGuardMixin          content_hash for upserts that skip unchanged rows
    VerificationMixin       who/when/how a record was checked
    DeactivationMixin       reversible "not usable for new work", distinct from delete
    SoftDelete[Filtered]Mixin   deleted_at/by/reason (Filtered = automatic query filter)

Mixins carry columns and tiny pure helpers only — never listeners,
relationships or I/O.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID as PyUUID
from uuid import uuid4 as py_uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

#: Schema holding the tenancy root tables.
ORG_SCHEMA = "org_management"


class IntPKMixin:
    """Surrogate big-integer primary key (internal; never exposed in APIs)."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class BigIntPKWithUUIDMixin(IntPKMixin):
    """Surrogate BigInteger PK for internal indexing/joins + public UUID for API exposure."""

    uuid: Mapped[PyUUID] = mapped_column(
        PgUUID(as_uuid=True),
        default=py_uuid4,
        unique=True,
        index=True,
        nullable=False,
    )


class BigIntPKWithUUIDv7Mixin(IntPKMixin):
    """``BigIntPKWithUUIDMixin`` with a database-generated, time-ordered UUID.

    PostgreSQL 18 ``uuidv7()`` puts the timestamp in the high bits, so the
    unique index on ``uuid`` is appended to instead of scattered across the
    tree (uuid4's problem at scale). The value comes from the server default,
    so there is no Python-side ``default``: a row inserted by raw SQL or a
    Core statement gets one too, and the ORM reads it back through RETURNING.

    Opt-in — existing tables keep uuid4 so no migration has to rewrite them.
    Needs PG >= 18 (the deployment image and the scratch test image both are).
    """

    uuid: Mapped[PyUUID] = mapped_column(
        PgUUID(as_uuid=True),
        server_default=text("uuidv7()"),
        unique=True,
        index=True,
        nullable=False,
        comment="Time-ordered public reference id (PG18 uuidv7())",
    )


class TimestampMixin:
    """DB-authoritative created/updated timestamps (timezone-aware, UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ── tenancy ─────────────────────────────────────────────────────────────────

class TenantBound:
    """The ``tenant_id`` column + the marker app/database/tenancy.py filters
    and stamps on. Tables that own their tenancy constraints (organizations)
    inherit it directly and redeclare ``tenant_id`` with their named FK.

    The column lives HERE (not only in TenantScopedMixin) because
    ``with_loader_criteria(TenantBound, lambda cls: cls.tenant_id == …)``
    evaluates the lambda against this class too.
    """

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{ORG_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False, index=True, comment="Owning tenant (isolation key)",
    )


class TenantScopedMixin(TenantBound):
    """Row belongs to one tenant (required) and optionally one organization of it.

    * ``tenant_id`` → ``org_management.tenants.id`` (RESTRICT), NOT NULL.
    * ``organization_id`` NULL = tenant-wide row.
    * Composite FK ``(tenant_id, organization_id)`` →
      ``organizations (tenant_id, id)``: the DATABASE guarantees the
      organization belongs to the same tenant (MATCH SIMPLE: skipped when
      ``organization_id`` is NULL).

    Filled and enforced by app/database/tenancy.py — queries see only the
    current tenant's rows; inserts get the current tenant/organization.
    """

    organization_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Owning organization within the tenant; NULL = tenant-wide",
    )

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)          # declarative maps the class here
        table = cls.__dict__.get("__table__")
        if table is None or "organization_id" not in table.c:
            return
        name = f"fk_{table.name}_tenant_org"
        if any(getattr(c, "name", None) == name for c in table.constraints):
            return
        table.append_constraint(ForeignKeyConstraint(
            ["tenant_id", "organization_id"],
            [f"{ORG_SCHEMA}.organizations.tenant_id", f"{ORG_SCHEMA}.organizations.id"],
            name=name, ondelete="RESTRICT",
        ))
        Index(f"ix_{table.name}_tenant_org", table.c.tenant_id, table.c.organization_id)


#: v1 name (UUID, nullable) — now the enforced BigInteger scoping above.
TenantMixin = TenantScopedMixin


class MultiTenantMixin(TenantBound):
    """STRICT scope: the row belongs to one tenant **and** one organization.

    The difference from ``TenantScopedMixin`` is one word — ``organization_id``
    is NOT NULL — and it changes what the database can promise. With a
    nullable column the composite FK is MATCH SIMPLE: a NULL organization
    skips the check. Here every row is checked, so a row can never reference
    another tenant's organization, and "tenant-wide" rows cannot exist by
    accident.

    Use it for operational data that is always owned by a branch / legal
    entity (the location hub: places, addresses, geofences). Use
    ``TenantScopedMixin`` when a row may legitimately be tenant-wide.

    ``ondelete="CASCADE"`` here vs RESTRICT on ``TenantScopedMixin``: deleting
    a tenant is still blocked by the RESTRICT tables, so in practice the
    cascade only fires for a tenant whose other data is already gone.

    Note on writes: ``app/database/tenancy.py`` stamps ``organization_id``
    from the request context. Callers that may run without one must resolve it
    first (``app/modules/geo/service.py: require_organization``) so the user
    gets "choose an organization" instead of an IntegrityError.
    """

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{ORG_SCHEMA}.tenants.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="Tenant isolation key",
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="Organization within the tenant (required)",
    )

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        table = cls.__dict__.get("__table__")
        if table is None or "organization_id" not in table.c:
            return
        name = f"fk_{table.name}_tenant_org"
        if any(getattr(c, "name", None) == name for c in table.constraints):
            return
        table.append_constraint(ForeignKeyConstraint(
            ["tenant_id", "organization_id"],
            [f"{ORG_SCHEMA}.organizations.tenant_id", f"{ORG_SCHEMA}.organizations.id"],
            name=name, ondelete="CASCADE",
        ))
        # Serves the tenant+org filter AND the composite FK's cascade lookups;
        # a separate single-column index on organization_id would be redundant.
        Index(f"ix_{table.name}_tenant_org", table.c.tenant_id, table.c.organization_id)


class AuditMixin:
    """Who created / last updated the row. ``*_name`` is denormalised so the
    history reads without a join (and survives the user being deleted).
    System writers (Zoho sync, Celery) have no user id: ``created_by`` NULL,
    ``created_by_name`` e.g. ``system:zoho-sync``.

    ``updated_by`` and ``updated_by_name`` are stamped together (tenancy.py)
    and only when a user is acting — a system write leaves both as they were,
    so the pair never disagrees."""

    created_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id of the creator (NULL = system)")
    created_by_name: Mapped[str | None] = mapped_column(String(255), comment="Creator display name at the time")
    updated_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id of the last updater")
    updated_by_name: Mapped[str | None] = mapped_column(String(255), comment="Last updater display name at the time")


#: v1 name.
AuditUserMixin = AuditMixin


class StatusMixin:
    """Record lifecycle status + verification flag.

    ``status`` is OUR lifecycle (``active`` by default); tables add a CHECK for
    their allowed values. A Zoho-owned status is mirrored as ``zoho_status``.
    """

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default=text("'active'"), index=True,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )


class VerificationMixin:
    """Evidence that a record was checked by a human or an external authority.

    Complements ``StatusMixin.is_verified`` (the fast boolean everything
    filters on) with WHO checked it, WHEN, HOW and with WHAT evidence.
    ``verification_status`` carries the nuance a boolean cannot: an address
    that a geocoder resolved is not an address a courier stood in front of,
    and a *disputed* one is worse than an unchecked one.
    """

    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified", server_default=text("'unverified'"), index=True,
        comment="unverified / geocoded_only / field_verified / disputed (tables CHECK their own set)",
    )
    verification_method: Mapped[str | None] = mapped_column(
        String(50), comment="How it was verified (geocode, field_visit, utility_bill, otp, …)",
    )
    verification_data: Mapped[dict | None] = mapped_column(
        JSONB, comment="Evidence: file refs, provider response ids, signatures",
    )
    verified_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id of the verifier (NULL = system)")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def mark_verified(
        self, *, method: str, status: str = "field_verified", data: dict | None = None, by: int | None = None,
    ) -> None:
        from app.database.tenancy import current_actor

        # A machine's opinion is not verification: "geocoded_only" means a
        # provider returned a point, not that anyone confirmed the record.
        self.is_verified = status not in ("unverified", "disputed", "geocoded_only")
        self.verification_status = status
        self.verification_method = method
        self.verification_data = data
        self.verified_by = by if by is not None else current_actor().user_id
        self.verified_at = datetime.now(UTC)

    def mark_unverified(self, *, status: str = "unverified") -> None:
        self.is_verified = False
        self.verification_status = status
        self.verified_by = None
        self.verified_at = None


class RowVersionMixin:
    """Optimistic locking: every ORM UPDATE is ``… WHERE row_version = :seen``
    and increments it; a concurrent writer gets ``StaleDataError`` instead of
    silently overwriting. Core ``update()`` statements must bump it themselves.
    """

    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="Optimistic-lock counter (incremented on every update)",
    )

    @declared_attr.directive
    def __mapper_args__(cls):  # noqa: N805
        if "__table__" not in cls.__dict__:
            return {}
        # eager_defaults: server-computed columns (updated_at = now()) come back
        # via RETURNING, so a row can be serialised right after an UPDATE
        # without lazy IO (which async sessions forbid).
        return {"version_id_col": cls.__table__.c.row_version, "eager_defaults": True}


class SoftDeleteMixin:
    """Soft delete: who, when and why. Queries must filter deleted_at IS NULL
    (use SoftDeleteFilteredMixin for the automatic filter)."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id who deleted it")
    deleted_reason: Mapped[str | None] = mapped_column(Text, comment="Why it was deleted")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, *, reason: str | None = None, by: int | None = None) -> None:
        from app.database.tenancy import current_actor

        self.deleted_at = datetime.now(UTC)
        self.deleted_reason = reason
        self.deleted_by = by if by is not None else current_actor().user_id

    def restore(self) -> None:
        self.deleted_at = None
        self.deleted_by = None
        self.deleted_reason = None


class AppMetaMixin:
    """Which application version last wrote the row + free-form app metadata.

    ``app_version`` is stamped from ``settings.VERSION`` on every insert and
    update (tenancy.py). ``app_metadata`` is for the APPLICATION (feature
    flags, client hints, migration markers) — business data goes in columns.
    """

    app_version: Mapped[str | None] = mapped_column(String(32), comment="App version that last wrote the row")
    app_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )


class DeactivationMixin:
    """Reversible deactivation (distinct from deletion): the record stays
    visible and referenced, but is not usable for new work."""

    deactivation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivation_reason: Mapped[str | None] = mapped_column(Text)
    deactivated_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id who deactivated it")

    @property
    def is_deactivated_now(self) -> bool:
        return self.deactivation_date is not None

    def deactivate(self, *, reason: str | None = None, by: int | None = None) -> None:
        from app.database.tenancy import current_actor

        self.deactivation_date = datetime.now(UTC)
        self.deactivation_reason = reason
        self.deactivated_by = by if by is not None else current_actor().user_id

    def reactivate(self) -> None:
        self.deactivation_date = None
        self.deactivation_reason = None
        self.deactivated_by = None


class PolymorphicOwnerMixin:
    """The row belongs to *some entity*, named by class + id, with no foreign key.

    Use it when the same table serves many owners — addresses, notes,
    attachments, contacts of a user / vehicle / customer / invoice — and a hard
    FK per owner table is impossible. The price of dropping the FK is that the
    database no longer guarantees the owner exists or that the type is spelled
    right, so each table takes on two duties:

    * a CHECK over the closed set of owner types (an open set becomes
      ``'Customer'`` / ``'customers'`` / ``'customer'``) — see
      ``geo.place_links.OWNER_TYPES``;
    * a composite index that leads with the tenant, e.g.
      ``Index("ix_<table>_owner", "tenant_id", "owner_type", "owner_id")``.

    No per-column ``index=True`` on purpose: ``owner_type`` has a dozen values
    (useless alone) and every real read is "this owner's rows", which only the
    composite serves.

    ``owner_id`` is the owner's internal BigInteger PK, never its public UUID.
    """

    owner_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Owning entity class, e.g. 'user', 'vehicle' (CHECK the set per table)",
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Owning entity id (no FK)")

    @property
    def owner_ref(self) -> tuple[str, int]:
        return self.owner_type, self.owner_id


class HashGuardMixin:
    """Content fingerprint for hash-guarded upserts.

    An upsert that re-receives an unchanged record should write nothing: no new
    ``updated_at``, no ``row_version`` bump, no Debezium event. Store the hash
    of the business payload and let PostgreSQL compare::

        stmt = insert(Model).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Model.tenant_id, Model.code],
            set_={..., "content_hash": stmt.excluded.content_hash, "updated_at": func.now()},
            where=Model.content_hash.is_distinct_from(stmt.excluded.content_hash),
        )

    ``IS DISTINCT FROM`` (not ``!=``) so a row whose hash is still NULL is
    rewritten once instead of being skipped forever.

    Hash the *business* fields only — leave out timestamps, sync cursors and
    anything else that changes without the record changing. Not indexed: the
    guard compares against the row the conflict key already found.

    Zoho mirrors do not use this; ``ZohoMirrorMixin.zoho_raw_hash`` is the same
    idea with the apply-gate's provenance rules on top.
    """

    content_hash: Mapped[str | None] = mapped_column(
        String(64), comment="sha256 (hex) of the business payload — skip the write when unchanged",
    )

    @staticmethod
    def hash_content(payload: Mapping[str, Any], *, exclude: Iterable[str] = ()) -> str:
        """sha256 hex of the canonical payload minus the top-level ``exclude`` keys.

        Canonical = sorted keys, no whitespace, non-JSON values stringified, so
        key order and formatting never look like a change.
        """
        skip = set(exclude)
        canonical = json.dumps(
            {k: v for k, v in payload.items() if k not in skip},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TenantEntityMixin(
    TenantScopedMixin, AuditMixin, StatusMixin, RowVersionMixin, AppMetaMixin, TimestampMixin,
):
    """The full entity bundle (soft delete is added separately so a model can
    pick SoftDeleteMixin or the auto-filtered SoftDeleteFilteredMixin)."""


class OrgEntityMixin(
    MultiTenantMixin, AuditMixin, StatusMixin, RowVersionMixin, AppMetaMixin, TimestampMixin,
):
    """``TenantEntityMixin`` for data that always belongs to an organization
    (``organization_id`` NOT NULL). Add a soft-delete mixin separately."""


class LedgerMixin(TenantScopedMixin, AppMetaMixin):
    """Append-only / operational rows: tenant-scoped + app metadata only.
    No row_version (never updated concurrently), no soft delete (an audit trail
    is never "deleted"), no status (the row IS the event)."""


__all__ = [
    "ORG_SCHEMA",
    "AppMetaMixin",
    "AuditMixin",
    "AuditUserMixin",
    "BigIntPKWithUUIDMixin",
    "BigIntPKWithUUIDv7Mixin",
    "DeactivationMixin",
    "HashGuardMixin",
    "IntPKMixin",
    "LedgerMixin",
    "MultiTenantMixin",
    "OrgEntityMixin",
    "PolymorphicOwnerMixin",
    "RowVersionMixin",
    "SoftDeleteMixin",
    "StatusMixin",
    "TenantBound",
    "TenantEntityMixin",
    "TenantMixin",
    "TenantScopedMixin",
    "TimestampMixin",
    "VerificationMixin",
]
