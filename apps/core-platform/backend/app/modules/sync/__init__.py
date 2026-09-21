"""Source-neutral sync core — the crosswalk between external records and ours.

This package holds everything about syncing that is **not** about Zoho: the
crosswalk tables, the per-module contract, and the SQL that reads and writes
crosswalk rows. It must never import ``app.modules.zoho`` or any feature
module (enforced by .importlinter) — the Zoho engine imports *this*, not the
other way round.

Scope discipline (docs/implementation-plan/sync-crosswalk-redesign.md §3.5):
the sync **engine** deliberately stays in ``app/modules/zoho/sync/engine.py``.
It is wired to Zoho's events, stats, exceptions, registry, config and Celery
tasks; moving it here would mean abstracting seven seams for no functional
gain. New neutral code lands here; the engine moves only when a second source
actually needs it.
"""
