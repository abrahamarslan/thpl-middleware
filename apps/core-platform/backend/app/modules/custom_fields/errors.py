"""Business-rule failures of the custom-fields module (mapped to 422 by handlers)."""

from app.common.exception.errors import AppError


class CustomFieldRuleError(AppError):
    """The request is well-formed but breaks a custom-field rule (a value in the
    wrong storage column, a dependency cycle, an owner type mismatch …)."""

    status_code = 422
    code = "custom_field_rule_violation"


__all__ = ["CustomFieldRuleError"]