"""Shift templates — what a shift looks like when nobody scheduled one (docs/fieldops/shift-templates.md).

A template is DATA only: the local window (09:00 → 21:00, optionally overnight), the work type, the days
it applies, and where work starts and ends (``RouteEndpointsMixin``). It has NO targeting columns: WHO
gets which template is the policy setting ``shift.template`` (a template code), resolved through the
policy layers like every other obligation — organization-wide is an organization layer, "for members"
a role layer, a beat a beat layer. One targeting mechanism, not two.

Templates are defined at an organization and usable by its subtree; ``code`` is unique per tenant (a
policy layer references it by code). A shift copies the template's values when it materializes
(``shifts.template_snapshot``): editing a template never changes a past shift.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.fieldops.endpoints import RouteEndpointsMixin, endpoint_table_args
from app.modules.fieldops.enums import FIELDOPS_SCHEMA, ShiftWorkType, values


class ShiftTemplate(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, RouteEndpointsMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "shift_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_shift_templates_tenant_id"),
        *endpoint_table_args("shift_templates"),
        CheckConstraint(f"work_type IN ({values(ShiftWorkType)})", name="chk_shift_templates_work_type"),
        CheckConstraint("status IN ('active','inactive')", name="chk_shift_templates_status"),
        CheckConstraint("end_day_offset IN (0, 1)", name="chk_shift_templates_day_offset"),
        CheckConstraint("end_day_offset = 1 OR end_local_time > start_local_time",
                        name="chk_shift_templates_window"),
        CheckConstraint("cardinality(days_of_week) > 0 AND days_of_week <@ ARRAY[1,2,3,4,5,6,7]::smallint[]",
                        name="chk_shift_templates_days"),
        CheckConstraint("valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
                        name="chk_shift_templates_validity"),
        Index("uq_shift_templates_code_live", "tenant_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        {"schema": FIELDOPS_SCHEMA,
         "comment": "Shift patterns used when no shift was scheduled; assigned via policy setting shift.template."},
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False, comment="Unique per tenant, e.g. WORK_SHIFT")
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="e.g. 'Work Shift' — the shift's title")
    description: Mapped[str | None] = mapped_column(Text)
    title_pattern: Mapped[str | None] = mapped_column(
        String(200), comment="Optional title, with {name} {date} {weekday} placeholders",
    )
    work_type: Mapped[str] = mapped_column(String(20), nullable=False, default=ShiftWorkType.OTHER.value,
                                           server_default=text("'other'"))
    start_local_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_local_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_day_offset: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"),
                                                comment="1 = ends the next day (overnight)")
    timezone: Mapped[str | None] = mapped_column(String(64), comment="IANA zone; NULL = the organization's")
    days_of_week: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, default=lambda: [1, 2, 3, 4, 5, 6, 7],
        server_default=text("ARRAY[1,2,3,4,5,6,7]::smallint[]"), comment="ISO weekdays (1 = Monday)",
    )
    valid_from: Mapped[dt.date | None] = mapped_column(Date)
    valid_until: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active", server_default=text("'active'"))

    @property
    def planned_minutes(self) -> int:
        start = self.start_local_time.hour * 60 + self.start_local_time.minute
        end = self.end_local_time.hour * 60 + self.end_local_time.minute + 1440 * self.end_day_offset
        return end - start

    def __repr__(self) -> str:
        return f"<ShiftTemplate {self.code} {self.start_local_time}-{self.end_local_time}>"


__all__ = ["ShiftTemplate"]
