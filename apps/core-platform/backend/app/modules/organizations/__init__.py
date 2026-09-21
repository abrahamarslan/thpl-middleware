"""Organizations — the tenant's legal / hierarchy tree (``org_management.organizations``).

    model.py schema.py service.py api.py   the feature (/api/organizations)
    zoho/  spec.py fields.py hooks.py      Zoho adapter: a Zoho organization is a root node of this tree

Replaces the v1 ``zoho_organizations`` mirror (migration moves its rows here).
Docs: docs/tenancy/README.md §5, docs/zoho-sync-implementation/adapters/organizations.md
"""
