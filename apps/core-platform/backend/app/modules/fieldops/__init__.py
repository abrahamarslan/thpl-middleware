"""Field operations — shifts, pauses, visits, tasks and the location stream.

Schema ``fieldops``. Design and rationale: docs/fieldops/README.md (overview),
docs/fieldops/implementation-of-shift-visits-system.md (spec) and
docs/fieldops/improvement-document.md (review of the original proposal).

Layout: ``model/`` (tables), ``schema.py`` (transport), ``crud.py`` (SQL), ``service/``
(business rules), ``api_me.py`` (the field app, /api/me/…), ``api.py`` (managers,
/api/fieldops/…). Pure, table-tested logic lives in ``clock.py``, ``verification.py``,
``trackmath.py``, ``state.py`` and ``task_types.py``.

Nothing else in the platform imports this package (``.importlinter``: fieldops is a leaf).
"""
