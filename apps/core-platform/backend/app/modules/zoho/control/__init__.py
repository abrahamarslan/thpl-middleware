"""Zoho control plane — what runs, when, whether it may, and what happened.

    switches.py   engine/direction/module kill switches + automatic auth pause
    runs.py       run leases (DB-enforced singletons) and fenced cursors
    events.py     record-level sync events with field diffs
    planner.py    the single scheduler (replaces the v1 5-minute dispatcher)
    retention.py  partition maintenance + policy-driven purges
    health.py     one snapshot for /metrics and the operator API
    models.py     the tables behind all of the above

Docs: docs/zoho-sync-implementation/control-plane.md
"""
