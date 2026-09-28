"""Devices, app sessions and tracking-health events.

``Device``         one row per app INSTALLATION (an app-generated id — never IMEI/Android ID,
                   which Android 10+ withholds anyway). A shift is bound to the device that
                   started it; fixes from another device are flagged ``foreign_device``
                   (improvement-document F-30). ENTITY.
``DeviceSession``  one row per app launch (``uuid`` = the client's session id): the
                   capability snapshot that decides whether tracking CAN work — permission
                   level, precise vs approximate, battery-optimisation exemption, automatic
                   time. Upserted on every launch. LEDGER-shaped (no row_version).
``DeviceEvent``    append-only tracking-health events (GPS off, permission revoked, time
                   changed, app restarted after being killed …). LEDGER.

``client_app_version`` is the FIELD APP's version. ``app_version`` (AppMetaMixin) is the
SERVER version stamped by ``app/database/tenancy.py`` — never write the client's there.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    BigIntPKWithUUIDv7Mixin,
    DeactivationMixin,
    MultiTenantMixin,
    OrgEntityMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.fieldops.enums import (
    FIELDOPS_SCHEMA,
    DeviceEventType,
    LocationPermission,
    Platform,
    TimeBasis,
    values,
)


class Device(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, DeactivationMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_devices_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_devices_user", ondelete="CASCADE"),
        Index("uq_devices_installation_live", "tenant_id", "installation_id", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("uq_devices_one_primary", "tenant_id", "user_id", unique=True,
              postgresql_where=text("is_primary AND deleted_at IS NULL")),
        Index("ix_devices_user", "tenant_id", "user_id", postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint(f"platform IN ({values(Platform)})", name="chk_devices_platform"),
        {"schema": FIELDOPS_SCHEMA, "comment": "App installations; a shift is bound to one (device binding)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="The user the installation belongs to")
    installation_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="App-generated installation id (opaque, preserved exactly)",
    )
    platform: Mapped[str] = mapped_column(String(10), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    os_version: Mapped[str | None] = mapped_column(String(40))
    app_id: Mapped[str | None] = mapped_column(String(100), comment="Package / bundle id (FieldMate vs DLP)")
    push_token: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="The user's field device",
    )
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                       server_default=text("now()"))
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                      server_default=text("now()"))

    def __repr__(self) -> str:
        return f"<Device id={self.id} user={self.user_id} {self.platform}:{self.installation_id}>"


class DeviceSession(BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AppMetaMixin, TimestampMixin, Base):
    __tablename__ = "device_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "device_id"], [f"{FIELDOPS_SCHEMA}.devices.tenant_id",
                                                          f"{FIELDOPS_SCHEMA}.devices.id"],
                             name="fk_device_sessions_device", ondelete="CASCADE"),
        Index("ix_device_sessions_device", "device_id", text("started_at DESC")),
        Index("ix_device_sessions_user", "tenant_id", "user_id", text("started_at DESC")),
        CheckConstraint(f"location_permission IS NULL OR location_permission IN ({values(LocationPermission)})",
                        name="chk_device_sessions_permission"),
        {"schema": FIELDOPS_SCHEMA,
         "comment": "One row per app session (uuid = client session id): the capability snapshot."},
    )

    device_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                    server_default=text("now()"))
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                      server_default=text("now()"))
    client_app_version: Mapped[str | None] = mapped_column(String(32), comment="Field-app version (NOT app_version)")
    client_build: Mapped[str | None] = mapped_column(String(32))
    os_version: Mapped[str | None] = mapped_column(String(40))
    sdk_int: Mapped[int | None] = mapped_column(Integer, comment="Android API level")
    boot_count: Mapped[int | None] = mapped_column(Integer, comment="Device boot counter at session start")
    location_permission: Mapped[str | None] = mapped_column(String(24))
    precise_location: Mapped[bool | None] = mapped_column(Boolean, comment="False = Android 12+ approximate grant")
    battery_optimization_exempt: Mapped[bool | None] = mapped_column(Boolean)
    power_save_mode: Mapped[bool | None] = mapped_column(Boolean)
    auto_time_enabled: Mapped[bool | None] = mapped_column(Boolean, comment="False = user-set clock (tamper signal)")
    auto_timezone_enabled: Mapped[bool | None] = mapped_column(Boolean)
    developer_options: Mapped[bool | None] = mapped_column(Boolean)
    is_rooted: Mapped[bool | None] = mapped_column(Boolean)
    integrity_verdict: Mapped[str | None] = mapped_column(String(40), comment="Play Integrity / App Attest summary")
    integrity_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    network_type: Mapped[str | None] = mapped_column(String(10))
    carrier: Mapped[str | None] = mapped_column(String(60))
    locale: Mapped[str | None] = mapped_column(String(20))
    device_timezone: Mapped[str | None] = mapped_column(String(64), comment="Diagnostics only — never business time")

    def __repr__(self) -> str:
        return f"<DeviceSession {self.uuid} device={self.device_id}>"


class DeviceEvent(BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AppMetaMixin, Base):
    __tablename__ = "device_events"
    __table_args__ = (
        Index("ix_device_events_user_time", "tenant_id", "user_id", text("occurred_at DESC")),
        CheckConstraint(f"event_type IN ({values(DeviceEventType)})", name="chk_device_events_type"),
        CheckConstraint(f"time_basis IN ({values(TimeBasis)})", name="chk_device_events_time_basis"),
        {"schema": FIELDOPS_SCHEMA,
         "comment": "Append-only tracking-health events (uuid = client event id)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    device_id: Mapped[int | None] = mapped_column(BigInteger)
    session_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    client_timestamp: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Device wall clock as reported (raw telemetry, untrusted)",
    )
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     comment="Business time (fieldops clock.py)")
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     server_default=text("now()"))
    time_basis: Mapped[str] = mapped_column(String(24), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"<DeviceEvent {self.event_type} user={self.user_id} at={self.occurred_at}>"
