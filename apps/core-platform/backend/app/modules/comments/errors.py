"""Comments' own error code — same shape as ``geo.scope.GeoRuleError``."""

from __future__ import annotations

from app.common.exception.errors import AppError


class CommentRuleError(AppError):
    """A comments business rule was broken (not a permission check — see ``rbac.deps``)."""

    status_code = 422
    code = "comment_rule_violation"


__all__ = ["CommentRuleError"]
