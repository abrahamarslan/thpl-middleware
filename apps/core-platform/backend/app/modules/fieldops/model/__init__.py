"""Field-operations models (schema ``fieldops``).

Imported as a package so every table is registered together (alembic/env.py, the Celery
worker boot, the conformance test). docs/fieldops/implementation-of-shift-visits-system.md §2–3.
"""

# FK targets outside this package must be in the metadata before these models are mapped.
from app.modules.geo import model as _geo_model  # noqa: F401
from app.modules.hubs import model as _hubs_model  # noqa: F401
from app.modules.idempotency.model import IdempotencyKey
from app.modules.roles import model as _roles_model  # noqa: F401
from app.modules.users import model as _users_model  # noqa: F401
from app.modules.vehicles import model as _vehicles_model  # noqa: F401
from app.modules.fieldops.model.device import Device, DeviceEvent, DeviceSession
from app.modules.fieldops.model.ledger import Anomaly, StateTransition
from app.modules.fieldops.model.policy import PolicyEpoch, PolicyLayer
from app.modules.fieldops.model.template import ShiftTemplate
from app.modules.fieldops.model.shift import Shift, ShiftMetrics, ShiftPause
from app.modules.fieldops.model.stream import LocationCheck, LocationPing, PingBatch
from app.modules.fieldops.model.visit import Visit, VisitParticipant, VisitTask

__all__ = [
    "Anomaly",
    "Device",
    "DeviceEvent",
    "DeviceSession",
    "IdempotencyKey",
    "LocationCheck",
    "LocationPing",
    "PingBatch",
    "PolicyEpoch",
    "PolicyLayer",
    "Shift",
    "ShiftMetrics",
    "ShiftPause",
    "ShiftTemplate",
    "StateTransition",
    "Visit",
    "VisitParticipant",
    "VisitTask",
]
