"""Currencies — the canonical currency master and effective-dated rate history.

    model.py   schema ``currency``: Currency + ExchangeRate (the source of truth)
    schema.py  transport schemas
    crud.py    data access (no business logic)
    service.py the domain rules
    api.py     HTTP at /api/currencies
    scope.py   which organization a new row belongs to

This IS the Zoho sync target: the engine writes the canonical row here. (The old
*currency* mirror at ``/api/zoho/currencies``. That module records what Zoho
said; this one owns the canonical currency and the rate history.
"""