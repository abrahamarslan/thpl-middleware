"""Errors of the accounting module — stable codes the API returns."""

from app.common.exception.errors import AppError, ConflictError


class AccountRuleError(AppError):
    """A business rule refused the write (wrong group for a purpose, sub-account not allowed …)."""

    status_code = 422
    code = "account_rule_violation"


class ZohoOwnedFieldError(AppError):
    """A local edit touched a column Zoho feeds on a Zoho-linked account."""

    status_code = 422
    code = "zoho_owned_field"


class ZohoMasteredChartError(AppError):
    """Local account creation in an organization whose chart Zoho masters (until outbound exists)."""

    status_code = 422
    code = "zoho_mastered_chart"


class AccountInUseError(ConflictError):
    """The account still has children or assignments."""

    code = "account_in_use"


__all__ = ["AccountInUseError", "AccountRuleError", "ZohoMasteredChartError", "ZohoOwnedFieldError"]
