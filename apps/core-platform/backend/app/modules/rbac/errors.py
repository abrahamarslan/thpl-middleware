"""RBAC errors — one module-specific code so a client can tell a role/permission rule
violation from any other 422."""

from app.common.exception.errors import AppError


class RbacRuleError(AppError):
    status_code = 422
    code = "rbac_rule_violation"


__all__ = ["RbacRuleError"]
