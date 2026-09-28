"""The visit-task registry — what each ``task_type`` carries and where it may happen.

A registry, not an ``if task_type == …`` chain (coding standards): the service validates a
task's ``payload`` with its spec's Pydantic model, checks the visit's channel, and checks
the reference type. Adding a task type = one entry here + the enum value + one CHECK
migration; nothing else changes.

Payload models accept unknown keys (``extra="allow"``): the field app evolves faster than
the server, and dropping a field a newer app sent would lose data. Known keys are
validated.

Amounts are NOT in the payload: a task carries ``amount`` + ``currency_code`` as columns so
metrics can sum them without reading every module's documents.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.fieldops.enums import Channel, NoOrderReason, TaskType

_ALL = frozenset(c.value for c in Channel)
_FIELD = frozenset({Channel.FIELD.value})
_FIELD_VIDEO = frozenset({Channel.FIELD.value, Channel.VIDEO.value})


class _Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class OrderLine(_Payload):
    item_ref: str = Field(..., max_length=100, description="Item code or uuid")
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)


class TakeOrderPayload(_Payload):
    lines: list[OrderLine] = Field(default_factory=list, max_length=500)
    expected_delivery_date: dt.date | None = None
    note: str | None = Field(default=None, max_length=2000)


class NoOrderPayload(_Payload):
    reason: NoOrderReason
    competitor: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class CollectPaymentPayload(_Payload):
    mode: str = Field(..., pattern="^(cash|upi|cheque|neft|rtgs|card|other)$")
    instrument_no: str | None = Field(default=None, max_length=60, description="Cheque / UTR / txn id")
    instrument_date: dt.date | None = None
    against_invoices: list[str] = Field(default_factory=list, max_length=100)


class DeliverPayload(_Payload):
    invoice_ref: str | None = Field(default=None, max_length=100)
    items: list[OrderLine] = Field(default_factory=list, max_length=500)
    received_by: str | None = Field(default=None, max_length=200)


class ReturnPayload(_Payload):
    invoice_ref: str | None = Field(default=None, max_length=100)
    lines: list[OrderLine] = Field(default_factory=list, max_length=500)
    reason: str = Field(..., max_length=200)


class StockCheckPayload(_Payload):
    counts: dict[str, Decimal] = Field(default_factory=dict, description="item_ref → quantity on shelf")


class DetailingPayload(_Payload):
    products: list[str] = Field(..., min_length=1, max_length=50)
    duration_minutes: Decimal | None = Field(default=None, ge=0)


class SamplePayload(_Payload):
    """Free samples are a compliance record (pharma marketing codes require batch-level logs)."""

    product_ref: str = Field(..., max_length=100)
    batch_no: str = Field(..., max_length=60)
    quantity: Decimal = Field(..., gt=0)
    recipient_name: str | None = Field(default=None, max_length=200)
    recipient_registration_no: str | None = Field(default=None, max_length=60)


class SurveyPayload(_Payload):
    survey_ref: str = Field(..., max_length=100)
    answers: dict = Field(default_factory=dict)


class MerchandisingPayload(_Payload):
    display_type: str | None = Field(default=None, max_length=60)
    compliant: bool | None = None
    note: str | None = Field(default=None, max_length=2000)


class FeedbackPayload(_Payload):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)


class NotePayload(_Payload):
    text: str = Field(..., min_length=1, max_length=4000)


@dataclass(frozen=True, slots=True)
class TaskTypeSpec:
    code: TaskType
    payload_model: type[BaseModel]
    channels: frozenset[str]
    #: ``core.entity_types`` codes a task of this type may reference (empty = none)
    reference_types: frozenset[str] = frozenset()
    #: the task carries a money amount (order value, collection)
    carries_amount: bool = False
    #: counts as an order for metrics
    is_order: bool = False
    is_collection: bool = False


_SPECS: tuple[TaskTypeSpec, ...] = (
    TaskTypeSpec(TaskType.TAKE_ORDER, TakeOrderPayload, _ALL, frozenset({"sales_order"}),
                 carries_amount=True, is_order=True),
    TaskTypeSpec(TaskType.RECORD_NO_ORDER, NoOrderPayload, _ALL),
    TaskTypeSpec(TaskType.COLLECT_PAYMENT, CollectPaymentPayload, _ALL, frozenset({"customer_payment"}),
                 carries_amount=True, is_collection=True),
    TaskTypeSpec(TaskType.DELIVER, DeliverPayload, _FIELD, frozenset({"delivery", "invoice"})),
    TaskTypeSpec(TaskType.PROCESS_RETURN, ReturnPayload, _FIELD, frozenset({"sales_return"}), carries_amount=True),
    TaskTypeSpec(TaskType.PROCESS_EXCHANGE, ReturnPayload, _FIELD, frozenset({"sales_return"})),
    TaskTypeSpec(TaskType.STOCK_CHECK, StockCheckPayload, _FIELD),
    TaskTypeSpec(TaskType.PRODUCT_DETAILING, DetailingPayload, _FIELD_VIDEO),
    TaskTypeSpec(TaskType.DISTRIBUTE_SAMPLE, SamplePayload, _FIELD),
    TaskTypeSpec(TaskType.SURVEY, SurveyPayload, _ALL),
    TaskTypeSpec(TaskType.MERCHANDISING, MerchandisingPayload, _FIELD),
    TaskTypeSpec(TaskType.CUSTOMER_FEEDBACK, FeedbackPayload, _ALL),
    TaskTypeSpec(TaskType.NOTE, NotePayload, _ALL),
)

REGISTRY: dict[str, TaskTypeSpec] = {spec.code.value: spec for spec in _SPECS}


def spec_for(task_type: str) -> TaskTypeSpec:
    try:
        return REGISTRY[task_type]
    except KeyError:
        raise ValueError(f"unknown task_type {task_type!r}") from None


def _check_complete() -> None:
    missing = {t.value for t in TaskType} - REGISTRY.keys()
    if missing:
        raise RuntimeError(f"task types without a registry entry: {sorted(missing)}")


_check_complete()

__all__ = ["REGISTRY", "TaskTypeSpec", "spec_for"]
