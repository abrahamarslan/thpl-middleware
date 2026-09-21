"""Backwards-compatibility shim — the Zoho client moved to ``transport.py``.

``ZohoClient`` now runs every call through the governor (daily quota, rate,
concurrency), the circuit breaker and the shared token manager, and its
``paginate()`` raises instead of swallowing errors. The verb helpers keep the
v1 signatures, so existing callers (the v1 sync engine) work unchanged.

    from app.modules.zoho.core.transport import ZohoOp, zoho_client   # preferred
    from app.modules.zoho.core.client import zoho_client              # legacy
"""

from app.modules.zoho.core.transport import Api, ZohoClient, ZohoOp, ZohoPage, zoho_client

__all__ = ["Api", "ZohoClient", "ZohoOp", "ZohoPage", "zoho_client"]
