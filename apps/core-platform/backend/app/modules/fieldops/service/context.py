"""The context of one device-originated action: who, the send-time clocks, tracing."""

from __future__ import annotations

import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any

from app.modules.fieldops.clock import Derived, EventClock, SendContext, derive
from app.modules.fieldops.schema import ClockIn


@dataclass(frozen=True, slots=True)
class Act:
    user: Any
    send: SendContext
    request_id: str | None = None
    idempotency_key: uuid_lib.UUID | None = None

    def when(self, clock: ClockIn | None) -> Derived:
        """Business time of an action carrying ``clock``."""
        if clock is None:
            return derive(self.send, None)
        return derive(self.send, EventClock(clock.client_timestamp, clock.elapsed_realtime_ms, clock.boot_count))


__all__ = ["Act"]
