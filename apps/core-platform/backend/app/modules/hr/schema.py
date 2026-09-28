"""Transport schemas for employment (placement + lifecycle).

Statutory and payroll fields (EPFO UAN, ESIC, bank account, professional-tax state) are deliberately NOT
exposed here: they belong to a compliance/payroll surface with its own permission, not to the org chart.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.modules.hr.enums import EmploymentStatus, EmploymentType, PersonnelType, WorkLocationType

_CODE = r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,49}$"


class EmploymentCreate(BaseModel):
    user_id: int = Field(..., gt=0)
    employee_code: str = Field(..., pattern=_CODE)
    personnel_type: PersonnelType
    employment_type: EmploymentType
    employment_status: EmploymentStatus = EmploymentStatus.PENDING_ONBOARDING
    work_location_type: WorkLocationType | None = None
    department: str | None = Field(None, description="Department uuid, code or id (of the request's organization)")
    job_title: str | None = Field(None, description="Job title uuid, code or id")
    cost_center: str | None = Field(None, max_length=50)
    hub_id: int | None = Field(None, gt=0)
    reporting_manager_user_id: int | None = Field(None, gt=0)
    date_of_joining: dt.date
    probation_period_days: int | None = Field(None, ge=0)
    date_of_confirmation: dt.date | None = None
    notice_period_days: int | None = Field(None, ge=0)


class EmploymentUpdate(BaseModel):
    personnel_type: PersonnelType | None = None
    employment_type: EmploymentType | None = None
    employment_status: EmploymentStatus | None = None
    work_location_type: WorkLocationType | None = None
    department: str | None = Field(None, description="Department uuid, code or id; '' clears it")
    job_title: str | None = Field(None, description="Job title uuid, code or id; '' clears it")
    cost_center: str | None = Field(None, max_length=50)
    hub_id: int | None = Field(None, gt=0)
    reporting_manager_user_id: int | None = Field(None, gt=0, description="Set null to clear")
    probation_period_days: int | None = Field(None, ge=0)
    date_of_confirmation: dt.date | None = None
    notice_period_days: int | None = Field(None, ge=0)
    row_version: int = Field(..., ge=1)


class EmploymentEnd(BaseModel):
    date_of_exit: dt.date
    exit_reason: str | None = Field(None, max_length=255)
    employment_status: EmploymentStatus = EmploymentStatus.RESIGNED
    rehire_eligible: bool | None = None
    row_version: int = Field(..., ge=1)


class EmploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    organization_id: int
    user_id: int
    is_current: bool
    employee_code: str
    personnel_type: str
    employment_type: str
    employment_status: str
    work_location_type: str | None = None
    department_id: int | None = None
    job_title_id: int | None = None
    cost_center: str | None = None
    hub_id: int | None = None
    reporting_manager_user_id: int | None = None
    date_of_joining: dt.date
    probation_period_days: int | None = None
    date_of_confirmation: dt.date | None = None
    notice_period_days: int | None = None
    date_of_exit: dt.date | None = None
    exit_reason: str | None = None
    rehire_eligible: bool | None = None
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime


class OrgChartNode(BaseModel):
    user_id: int
    name: str | None = None
    employee_code: str | None = None
    department_id: int | None = None
    job_title_id: int | None = None
    reports: list[OrgChartNode] = []
