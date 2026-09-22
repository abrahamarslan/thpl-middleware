"""Hub module — operational hubs/branches and their zones.

A **hub** is an operational entity (warehouse, branch, dark store, transit
point or spoke) with a manager, a capacity and a daily cutoff. It is NOT a
``geo.place``: per the location hub's Design Rule Zero a place has no owner and
no telemetry, while a hub has both. A hub therefore *points at* a place (its
address/coordinates) and a geofence (its zone) rather than absorbing them.

See docs/hubs/README.md.
"""

from app.modules.hubs.model import Hub

__all__ = ["Hub"]
