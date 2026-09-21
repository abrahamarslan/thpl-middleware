"""The apply gate — the single decision for every Zoho payload we write.

Every mirror write from Zoho data asks :func:`decide` first. The function is
pure (no I/O) so its whole decision table is unit-tested; the engine performs
what it returns (docs/zoho-sync-implementation/apply-gate.md).

| # | Check | Outcome |
|---|---|---|
| 1 | no local row | ``inserted`` |
| 2 | row carries a sync tombstone and the payload is not newer than it | ``stale_ignored`` |
| 3 | row carries a sync tombstone and the payload is newer (or undated) | ``resurrected`` |
| 4 | payload older than the stored ``zoho_last_modified_time`` | ``stale_ignored`` (monotonic fence) |
| 5 | same version and same hash | ``unchanged`` (no UPDATE → no WAL, no CDC churn) |
| 6 | same version, thinner payload than the one stored | ``unchanged`` (nothing new) |
| 7 | otherwise | ``updated``; ``zoho_raw`` replaced only if the payload is at least as rich |

A row soft-deleted **locally** (``deleted_at`` set, no sync tombstone) is
refreshed but never revived — a user's delete is not the sync's to undo.

Provenance ranks (``zoho_raw`` is written only by the richest class seen):
``nested:*`` 0 < ``list:*`` 1 < ``detail_fetch`` / ``webhook`` 2.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    RESURRECTED = "resurrected"
    UNCHANGED = "unchanged"
    STALE_IGNORED = "stale_ignored"

    @property
    def writes(self) -> bool:
        return self in (Outcome.INSERTED, Outcome.UPDATED, Outcome.RESURRECTED)


def provenance_rank(source: str | None) -> int:
    """How complete a payload from ``source`` is (higher = richer)."""
    if not source:
        return 0
    if source.startswith("nested:"):
        return 0
    if source.startswith("list:"):
        return 1
    return 2                     # detail_fetch, webhook, push write-back


@dataclass(frozen=True, slots=True)
class RowState:
    """What the gate needs from the stored row."""

    zoho_last_modified_time: datetime | None = None
    zoho_raw_hash: bytes | None = None
    sync_source: str | None = None
    remote_deleted_at: datetime | None = None
    deleted_at: datetime | None = None
    legacy_tombstone: bool = False        # v1 soft_delete_missing: sync_status='deleted'

    @property
    def tombstone_at(self) -> datetime | None:
        """When the sync concluded Zoho deleted the record, if it did."""
        if self.remote_deleted_at is not None:
            return self.remote_deleted_at
        if self.legacy_tombstone and self.deleted_at is not None:
            return self.deleted_at
        return None


@dataclass(frozen=True, slots=True)
class Incoming:
    modified: datetime | None
    payload_hash: bytes
    source: str

    @property
    def rank(self) -> int:
        return provenance_rank(self.source)


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: Outcome
    write_raw: bool = False
    revive: bool = False
    reason: str | None = None


def decide(row: RowState | None, incoming: Incoming) -> Decision:
    """Apply-gate decision table (module docstring)."""
    if row is None:
        return Decision(Outcome.INSERTED, write_raw=True)

    tombstone = row.tombstone_at
    if tombstone is not None:
        if incoming.modified is not None and incoming.modified <= tombstone:
            return Decision(Outcome.STALE_IGNORED, reason="older_than_tombstone")
        # Zoho lists it again (or it changed after we tombstoned it): it exists.
        return Decision(Outcome.RESURRECTED, write_raw=True, revive=True)

    stored = row.zoho_last_modified_time
    if incoming.modified is not None and stored is not None:
        if incoming.modified < stored:
            return Decision(Outcome.STALE_IGNORED, reason="older_than_stored")
        if incoming.modified == stored:
            if row.zoho_raw_hash is not None and row.zoho_raw_hash == incoming.payload_hash:
                return Decision(Outcome.UNCHANGED, reason="same_hash")
            if incoming.rank < provenance_rank(row.sync_source):
                return Decision(Outcome.UNCHANGED, reason="richer_payload_stored")
    elif row.zoho_raw_hash is not None and row.zoho_raw_hash == incoming.payload_hash:
        # Undated modules (e.g. organizations): the hash alone proves nothing changed.
        return Decision(Outcome.UNCHANGED, reason="same_hash")

    write_raw = incoming.rank >= provenance_rank(row.sync_source)
    return Decision(Outcome.UPDATED, write_raw=write_raw)


# ── canonical hashing ───────────────────────────────────────────────────────

def _strip(value: Any, patterns: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip(item, patterns)
            for key, item in value.items()
            if not any(fnmatch.fnmatchcase(str(key), pattern) for pattern in patterns)
        }
    if isinstance(value, list):
        return [_strip(item, patterns) for item in value]
    return value


def payload_hash(payload: dict[str, Any], volatile_keys: Iterable[str] = ()) -> bytes:
    """sha256 of the canonical payload minus volatile keys (any depth).

    Canonical = sorted keys, no whitespace, non-JSON values stringified — so
    key order and formatting never look like a change, and Zoho's display
    strings (``*_formatted``) changing alone is not a business change.
    """
    canonical = json.dumps(
        _strip(payload, tuple(volatile_keys)),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).digest()


__all__ = [
    "Decision",
    "Incoming",
    "Outcome",
    "RowState",
    "decide",
    "payload_hash",
    "provenance_rank",
]
