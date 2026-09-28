"""Who may operate the Zoho integration.

RBAC now (docs/rbac-module.md): the admin routes declare ``Perm("zoho.integration:read")`` /
``Perm("zoho.integration:manage")`` directly. ``ZohoOperator`` is kept as an alias for the manage
permission so existing imports keep working.

The old ``ZOHO_OPERATOR_EMAILS`` allow-list (and its "empty + DEBUG = anyone" rule) is retired: an
operator is a user whose role carries ``zoho.integration:manage`` — grant it with a role assignment.
"""

from app.modules.rbac.deps import Perm

ZohoOperator = Perm("zoho.integration:manage")

__all__ = ["ZohoOperator"]
