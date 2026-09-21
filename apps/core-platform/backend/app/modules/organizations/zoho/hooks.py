"""Apply hooks for the Zoho organization adapter.

pre_upsert   the Zoho name is the registered name of a Zoho-linked legal
             entity → ``legal_name`` follows it (org_code / org_type / tree
             position are never touched; a new node becomes a root via the
             model's ``before_insert``).
post_upsert  resolve ``currency_id`` (our FK) from the Zoho currency id once
             the currencies master holds it. A table-level query, not the
             currencies model: feature modules stay independent (.importlinter).
"""

from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text


def zoho_owned_legal_name(payload: dict, values: dict[str, Any]) -> dict[str, Any]:
    if values.get("name"):
        values["legal_name"] = values["name"]
    return values


async def link_currency(row: Any, _payload: dict) -> None:
    zoho_currency_id = getattr(row, "zoho_currency_id", None)
    if not zoho_currency_id:
        return
    session = sa_inspect(row).async_session
    if session is None:
        return
    currency_id = await session.scalar(
        text("SELECT id FROM zoho_currencies WHERE tenant_id = :t AND zoho_id = :z AND deleted_at IS NULL LIMIT 1"),
        {"t": row.tenant_id, "z": zoho_currency_id},
    )
    if currency_id and row.currency_id != currency_id:
        row.currency_id = currency_id
