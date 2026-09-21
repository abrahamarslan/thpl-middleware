"""What a module declares about how it is synced — source-neutral.

``ModuleSyncConfig`` (app/modules/zoho/sync/config.py) says *how to talk to the
API*: endpoint, pagination, strategy, budgets. ``SyncContract`` says *how the
result is stored*: which table is canonical, how a second source's record is
matched onto an existing row, and which columns this source is allowed to own.

The split matters because the second is the part SAP will reuse verbatim.

Backward compatibility: ``crosswalk`` defaults to **False**, so a module that
declares nothing keeps today's in-place mirror behaviour byte for byte. Modules
opt in one PR at a time (redesign plan §7, phases 4–8).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class OnMissing(StrEnum):
    """What to do when a referenced record has not been synced yet (§4.1)."""

    FETCH = "fetch"    # call the owner's detail endpoint now (budgeted, single-flight)
    STUB = "stub"      # insert a provisional row, link immediately, enrich later
    DEFER = "defer"    # leave the FK NULL, queue a PendingReference
    NULL = "null"      # keep only the external id; we never intend to master it


class ReferenceRule(BaseModel):
    """A payload carries only an *id* of a record another module owns.

    Distinct from ``NestedEntityRule``, where the child's whole payload is
    embedded in the parent. Here we hold an id and must resolve it through the
    crosswalk — the one query that replaces N per-table ``zoho_id`` lookups.
    """

    model_config = ConfigDict(frozen=True)

    attr: str                          # dotted path in the payload, e.g. "tax_id"
    module: str                        # registry key of the owning module
    fk: str                            # canonical column receiving the LOCAL id
    external_fk: str | None = None     # optional column keeping the source id verbatim
    on_missing: OnMissing = OnMissing.DEFER
    many: bool = False                 # attr is a list of ids

    @field_validator("attr", "module", "fk")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reference rule paths must not be blank")
        return v


class SyncContract(BaseModel):
    """How one source's records are stored for one module."""

    model_config = ConfigDict(frozen=True)

    source_system: str = "zoho"
    #: Schema-qualified canonical table, e.g. "currency.currencies". Validated
    #: against the registered model at startup — a typo dies at boot.
    entity_table: str = ""
    #: Business key used to link a NEW source id onto an EXISTING canonical row
    #: (how SAP's USD finds Zoho's). Empty = never merge; each source gets its
    #: own row until a steward says otherwise. Never invent a match.
    match_on: tuple[str, ...] = ()
    #: False = today's in-place mirror (ZohoIdentityMixin + ZohoMirrorMixin on
    #: the entity table). True = crosswalk + history.
    crosswalk: bool = False
    #: Keep the full document in sync_payloads history. False for high-volume
    #: document modules: history keeps hash + changed fields, and the current
    #: document still lives on the SyncRecord.
    history_raw: bool = True
    capture_custom_fields: bool = True
    capture_comments: bool = False
    #: Canonical columns this source may write. A lower-precedence source that
    #: does not own a field must not overwrite it.
    owned_fields: frozenset[str] = frozenset()
    references: tuple[ReferenceRule, ...] = ()

    @field_validator("source_system")
    @classmethod
    def _source_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_system must not be blank")
        return v


__all__ = ["OnMissing", "ReferenceRule", "SyncContract"]
