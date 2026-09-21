"""Zoho users — mirror of the Zoho organization's users (O1 master, package-by-feature).

Not ``app.modules.users`` (our own accounts). Sync module name: ``users``.

    model.py schema.py crud.py service.py api.py   the feature (read-only)
    zoho/  spec.py fields.py                        the Zoho adapter

HTTP: /api/zoho/users. Docs: docs/zoho-sync-implementation/adapters/users.md
"""
