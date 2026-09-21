"""Celery must never blindly replay a Zoho write whose outcome is unknown.

`ZohoApiError` now aliases the base `ZohoError`; putting it back into
`autoretry_for` would make Celery retry an AMBIGUOUS create and duplicate the
record in Zoho. These tests pin the task retry configuration.
"""

import pytest

from app.modules.zoho.core.errors import (
    ZohoAmbiguousOutcome,
    ZohoApiError,
    ZohoAuthRevokedError,
    ZohoContractError,
    ZohoNotFoundError,
    ZohoQuotaExhaustedError,
    ZohoTransientError,
    ZohoValidationError,
)
from app.tasks import zoho_sync


@pytest.mark.parametrize(
    "task", [zoho_sync.sync_module_run, zoho_sync.fetch_detail]
)
def test_tasks_do_not_autoretry_the_zoho_base_class(task):
    assert ZohoApiError not in tuple(task.autoretry_for)


@pytest.mark.parametrize(
    "exc",
    [
        ZohoAmbiguousOutcome("create outcome unknown"),
        ZohoQuotaExhaustedError("daily ceiling"),
        ZohoAuthRevokedError("reconnect"),
        ZohoValidationError("bad payload"),
        ZohoNotFoundError("gone"),
        ZohoContractError("bad shape"),
    ],
)
def test_non_retryable_failures_are_excluded(exc):
    task = zoho_sync.fetch_detail
    assert isinstance(exc, tuple(task.dont_autoretry_for))


def test_transient_failures_are_still_retried():
    task = zoho_sync.fetch_detail
    assert isinstance(ZohoTransientError("5xx"), tuple(task.autoretry_for))
    assert not isinstance(ZohoTransientError("5xx"), tuple(task.dont_autoretry_for))
