"""Errors of the price lists module — stable codes the API returns."""

from app.common.exception.errors import AppError


class PricingError(AppError):
    """A price cannot be computed from what the caller and the price list provide."""

    status_code = 422
    code = "pricing_unavailable"


class RoundingNotSupportedError(PricingError):
    """The list uses a Zoho rounding key whose exact semantics we have not verified.

    Refused rather than guessed: a wrong price is worse than no price.
    """

    code = "pricing_rounding_not_supported"


__all__ = ["PricingError", "RoundingNotSupportedError"]
