"""Reference resolution — a source id in a payload becomes a local foreign key.

``NestedEntityRule`` handles the case where a child's whole payload is embedded
in its parent. This is the other half, and the common one: the parent carries
only an **id**.

    {"invoice_id": "…", "currency_id": "982000000004012", "tax_id": "9876", …}

The goal, in the owner's words: *"I will only store `tax_id` if the tax exists
in my db or, if it doesn't, go get that `tax_id`, fetch it, insert it, and then
put that `tax_id` in invoice."* Correct per record — and catastrophic per page
if taken literally, because a page of 200 invoices naming 200 unsynced contacts
is 200 unplanned detail calls against a quota the whole fleet shares. Hence the
policies and the budget below.

**Two rules this file exists to keep apart.**

* *Policy* (which misses get FETCH / STUB / DEFER / NULL, and when the budget
  says no) is pure and lives here. It is a function of the rules, the page and
  a counter — no I/O, no engine, no session.
* *Mechanism* (actually calling Zoho, actually inserting a stub) is injected.
  That is why this module imports neither ``app.modules.zoho`` nor the engine,
  and why the policy is testable without a broker, a database or a fixture.

Resolution is **per page, not per record** (redesign §4.1): every rule across
every record in the page contributes its pairs to one
``crosswalk.resolve_many`` query. An invoice page referencing the same twelve
taxes over and over costs one round trip, not twelve hundred.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.modules.sync.contract import OnMissing, ReferenceRule

logger = structlog.get_logger("app.sync.references")

#: (module, external_id) — how the crosswalk is keyed for a lookup.
Pair = tuple[str, str]


def read_path(payload: Mapping[str, Any], path: str) -> Any:
    """Read a dotted path out of a payload. Missing segment → ``None``.

    Dotted because a reference is often one level down (``"address.country_id"``,
    ``"line_items.item_id"``); a list segment maps over its elements so
    ``many=True`` rules read naturally.
    """
    current: Any = payload
    for segment in path.split("."):
        if isinstance(current, list):
            collected = [
                item.get(segment) for item in current if isinstance(item, Mapping)
            ]
            current = [value for value in collected if value is not None]
            continue
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
        if current is None:
            return None
    return current


def external_ids_for(rule: ReferenceRule, payload: Mapping[str, Any]) -> list[str]:
    """The source ids one rule names in one payload. Always a list, possibly empty.

    Zoho sends ids as strings, integers and occasionally empty strings for "not
    set"; the crosswalk stores text. Normalising here means every comparison
    downstream is string-to-string.
    """
    value = read_path(payload, rule.attr)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    if not rule.many and len(out) > 1:
        # A single-valued rule that found several ids is a mapping bug, not data
        # to silently truncate — but dropping the record would be worse.
        logger.warning("sync.references.unexpected_list", attr=rule.attr,
                       module=rule.module, found=len(out))
        return out[:1]
    return out


def pairs_in_page(
    rules: Iterable[ReferenceRule], payloads: Iterable[Mapping[str, Any]]
) -> list[Pair]:
    """Every ``(module, external_id)`` the page needs, de-duplicated and ordered.

    Pure, and the reason the batched lookup is one query: this is the whole
    page's reference surface computed before anything is resolved.
    """
    rules = list(rules)
    seen: dict[Pair, None] = {}
    for payload in payloads:
        for rule in rules:
            for external_id in external_ids_for(rule, payload):
                seen[(rule.module, external_id)] = None
    return list(seen)


@dataclass(slots=True)
class Plan:
    """What to do with one record's references, decided but not yet done."""

    #: Canonical column → local entity id. Applied straight onto the values dict.
    values: dict[str, Any] = field(default_factory=dict)
    #: Misses to fetch now, in declaration order, already inside the budget.
    fetch: list[Pair] = field(default_factory=list)
    #: Misses to stub: a provisional canonical row, linked immediately.
    stub: list[Pair] = field(default_factory=list)
    #: Misses to queue on ``sync.pending_references`` — (rule, module, id).
    defer: list[tuple[ReferenceRule, str]] = field(default_factory=list)
    #: Misses deliberately left as an external id only.
    ignored: list[Pair] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.values or self.fetch or self.stub or self.defer or self.ignored)


@dataclass(slots=True)
class Budget:
    """A ceiling on unplanned detail calls per run.

    Without it, one page of documents naming unsynced masters turns into
    hundreds of detail calls, trips the Zoho rate limiter and spends the run's
    whole quota on references. Over budget, ``FETCH`` degrades to ``STUB`` —
    the record still links, it just links to a provisional row that the owning
    module's own sync will fill in.
    """

    limit: int
    spent: int = 0
    exhausted_logged: bool = False

    @property
    def remaining(self) -> int:
        return max(self.limit - self.spent, 0)

    def take(self) -> bool:
        if self.spent >= self.limit:
            if not self.exhausted_logged:
                logger.warning("sync.reference.budget_exhausted", limit=self.limit,
                               action="FETCH degrades to STUB for the rest of this run")
                self.exhausted_logged = True
            return False
        self.spent += 1
        return True


def plan_references(
    rules: Iterable[ReferenceRule],
    payload: Mapping[str, Any],
    resolved: Mapping[Pair, int | None],
    *,
    budget: Budget,
) -> Plan:
    """Decide one record's references against an already-resolved page.

    Pure: ``resolved`` is what the batched crosswalk lookup returned, ``budget``
    is a counter. Nothing here touches the database or Zoho — which is what
    makes the policy table testable as a table.

    **The external id is written on a hit too.** It costs nothing, and it is
    what lets a reconciler repair a bad linkage later without re-reading the
    source (redesign §4.1 step 3).
    """
    plan = Plan()
    for rule in rules:
        external_ids = external_ids_for(rule, payload)
        if not external_ids:
            continue

        if rule.external_fk:
            plan.values[rule.external_fk] = external_ids if rule.many else external_ids[0]

        hits: list[int] = []
        for external_id in external_ids:
            entity_id = resolved.get((rule.module, external_id))
            if entity_id is not None:
                hits.append(entity_id)
                continue

            match rule.on_missing:
                case OnMissing.FETCH:
                    # Budget is taken at PLAN time so the ceiling holds across
                    # the page, not per record.
                    target = plan.fetch if budget.take() else plan.stub
                    target.append((rule.module, external_id))
                case OnMissing.STUB:
                    plan.stub.append((rule.module, external_id))
                case OnMissing.DEFER:
                    plan.defer.append((rule, external_id))
                case OnMissing.NULL:
                    plan.ignored.append((rule.module, external_id))

        if hits:
            plan.values[rule.fk] = hits if rule.many else hits[0]
    return plan


__all__ = [
    "Budget",
    "Pair",
    "Plan",
    "external_ids_for",
    "pairs_in_page",
    "plan_references",
    "read_path",
]
