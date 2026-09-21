"""Business-rule failures of the document module (mapped to 422 by the global handlers)."""

from app.common.exception.errors import AppError


class DocumentRuleError(AppError):
    """The request is well-formed but breaks a document rule (a second FRONT page,
    a second owner, verifying an incomplete two-sided document …)."""

    status_code = 422
    code = "document_rule_violation"
