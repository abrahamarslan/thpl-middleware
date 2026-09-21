"""Zoho currencies mirror (O1 master, package-by-feature, read-only).

    model.py schema.py crud.py service.py api.py   the mirror (read-only)
    zoho/  spec.py fields.py                        the Zoho adapter

The CANONICAL currency master lives in ``app.modules.currencies`` (schema
``currency``); this module only records what Zoho said.
HTTP: /api/zoho/currencies. Docs: docs/zoho-sync-implementation/adapters/currencies.md
"""