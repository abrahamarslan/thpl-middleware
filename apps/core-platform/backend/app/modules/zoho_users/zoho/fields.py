"""Zoho users field map (docs/zoho-docs-md/users.md). Pull-only."""

from app.modules.zoho.sync.config import FieldMapping as F

FIELDS: list[F] = [
    F(zoho="name", local="name", transform="str", outbound=False),
    F(zoho="email", local="email", transform="str", outbound=False),
    F(zoho="user_role", local="user_role", transform="str", outbound=False),
    F(zoho="role_id", local="role_id", transform="str", outbound=False),
    F(zoho="status", local="zoho_status", transform="str", outbound=False),
    F(zoho="user_type", local="user_type", transform="str", outbound=False),
    F(zoho="is_current_user", local="is_current_user", transform="bool", outbound=False),
    F(zoho="is_customer_segmented", local="is_customer_segmented", transform="bool", outbound=False),
    F(zoho="is_vendor_segmented", local="is_vendor_segmented", transform="bool", outbound=False),
    F(zoho="photo_url", local="photo_url", transform="str", outbound=False),
    F(zoho="cost_rate", local="cost_rate", transform="decimal", outbound=False),
    F(zoho="created_time", local="zoho_created_time", transform="zoho_datetime", outbound=False),
]
