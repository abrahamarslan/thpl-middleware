# Zoho Real-Time Sync Architecture

**Webhooks, payload provenance, stock freshness, and snapshot semantics —
the v2 refinement of
[zoho-architecture-decision-framework.md](zoho-architecture-decision-framework.md).**

The decision framework (v1) settled *how to store* Zoho data: typed
projection over a raw document. This document settles *how the current
version of that data stays current* — and fixes one real defect in the v1
design that the following questions exposed:

1. Zoho fires a webhook when an item's rate or a contact's billing address
   changes — **how does `zoho_raw` get updated from a webhook?** (§2)
2. We want to poll items + stock availability "every few seconds" for the
   sales/delivery teams — **does that polling overwrite the payload, and
   is there a better approach?** (§4)
3. Someone flips an Estimate from `draft` to `sent` **in Zoho** — what
   exactly happens on our side? (§3)
4. **Does the architecture capture the *current version* of the data from
   Zoho, and how is `zoho_raw` kept correct?** (§1 — this is the defect
   fix)
5. Estimates/Invoices embed `line_items` with prices *as of creation*
   (discounts, free items); changing the item master later must never
   rewrite old orders. (§5)

**The defect v1 shipped with:** `engine.upsert_payload()` unconditionally
executes `row.zoho_raw = payload` on *every* upsert. A thin list-row
refresh therefore **clobbers a detail-rich `zoho_raw` with an index
payload** — the "full untouched document" doctrine silently degrades to
"whatever payload arrived last". A high-frequency stock sweep (question 2)
would destroy every item's detail document once a minute. §1 fixes this
with a payload-provenance rule; everything else in this document builds on
that fix.

---

## Table of contents

1. [Payload provenance — who may write `zoho_raw`](#1-payload-provenance)
2. [Webhook ingress — Zoho's outgoing webhooks, our inbound trigger lane](#2-webhook-ingress)
3. [Worked walkthrough: Estimate `draft` → `sent` changed in Zoho](#3-walkthrough-estimate-status)
4. [Stock freshness — the items stock lane](#4-stock-freshness)
5. [Line-item snapshot semantics — temporal correctness](#5-line-item-snapshots)
6. [Engine deltas E1–E7](#6-engine-deltas)
7. [The complete freshness topology](#7-complete-topology)
8. [Invariants](#8-invariants)

---

## 1. Payload provenance

### 1.1 The three payload classes

Every payload that reaches `upsert_payload()` comes from exactly one of
three provenances, and they are **not equal in authority**:

| Provenance | Producer | Shape | Authority |
|---|---|---|---|
| `detail` | `GET /{module}/{id}`, `GET /itemdetails?item_ids=…`, the echo of our own POST/PUT | The full document — the richest shape Zoho can produce for this entity | **Authoritative.** May write `zoho_raw`. |
| `list` | `GET /{module}` pages | The thin index row (subset of scalars + promoted duplicates; §1.2 of v1) | Column-grade only. **Never writes `zoho_raw`** on a detail-capable module. |
| `webhook` | Zoho workflow-rule webhook body | **Admin-configured** — whatever JSON template the workflow rule author built; may be full-ish, partial, or custom-shaped; can drift when someone edits the rule in Zoho's UI | A *trigger and a hint*. **Never writes `zoho_raw`, ever.** (§2.2) |

### 1.2 The provenance rule (the fix)

> **`zoho_raw` holds the last payload of the richest class this module can
> obtain — and only that class may replace it.**
>
> - Module has detail capability (`detail_required=True`, or a detail
>   endpoint exists and is ever fetched): only `detail`-provenance payloads
>   write `zoho_raw`.
> - INDEX-only module (the list row *is* the richest shape that exists —
>   e.g. currencies, payment terms): `list` payloads write `zoho_raw`.
> - `webhook` payloads never write it (they update nothing directly in the
>   default design — see §2.3's optional optimistic lane).

Mapped **columns**, by contrast, accept updates from *any* provenance —
that has always been safe, because `map_inbound()` skips missing keys (a
thin payload can refresh `rate` and `stock_on_hand` without nulling
`purchase_description`). The doctrine pair is now symmetric:

- **Columns:** any payload may update what it carries; absence never
  erases. *(v1, unchanged)*
- **`zoho_raw`:** only the richest payload class replaces it; a thinner
  payload never degrades it. *(v2, new)*

### 1.3 Engine change (E1)

`upsert_payload()` gains a `payload_kind: Literal["detail","list","webhook"]`
argument, derived automatically from the call site (`source=` already
distinguishes `detail_fetch` / `list:full` / `nested:*`):

```python
# engine.upsert_payload(), replacing the unconditional `row.zoho_raw = payload`
richest_is_list = not cfg.detail_required and cfg.detail_endpoint is None
if payload_kind == "detail" or (payload_kind == "list" and richest_is_list):
    row.zoho_raw = payload
    row.zoho_raw_synced_at = datetime.now(UTC)
```

`ZohoEntityMixin` gains one column: `zoho_raw_synced_at` (timestamptz,
nullable) — *when the authoritative document was last captured*, as
distinct from `synced_at` (*when any sync touched the row*). Ops can then
alert on "rows whose columns are fresh but whose document is stale" —
exactly the situation a high-frequency stock lane creates by design (§4).

Nested Class-C embeds (a contact's inlined `contact_tax_information`
routed to the taxes module) are upserted with `payload_kind="list"` — an
embed is a snapshot of the master, not the master's detail document, so it
refreshes the tax row's columns but never overwrites a `zoho_raw` captured
from `GET /settings/taxes`.

### 1.4 The monotonic version guard (E2)

Webhooks are unordered and can race the poller and each other: a burst of
edits in Zoho can deliver *edit #2's* fetch result before *edit #1's*.
Column writes are protected by a version fence:

```python
incoming_lmt = parse_zoho_datetime(payload.get("last_modified_time"))
if (incoming_lmt and row.zoho_last_modified_time
        and incoming_lmt < row.zoho_last_modified_time):
    # Stale snapshot arriving late — never regress. Journal and skip.
    row.append_sync_log("stale_payload_skipped", incoming=str(incoming_lmt))
    return row, False
```

`zoho_last_modified_time` becomes a standing Class-A column on every
mirror table (v1 already required persisting it; the guard makes it
load-bearing). Two boundary rules:

- **Equal timestamps are applied** (same version re-fetched — idempotent
  refresh, and Zoho's 1-second granularity makes strict-greater too
  strict).
- **Modules without `last_modified_time`** (organizations) skip the guard
  — last-writer-wins, acceptable for slow-moving O1 masters.

This guard is also the final piece of v1 §9.2's echo suppression: our own
outbound write's echo carries the new `last_modified_time`; any
concurrently-running incremental poll that listed the *pre-write* state
simply loses the fence.

### 1.5 So — does the architecture capture "the current version"?

Yes, with a precise definition per layer:

| Layer | What "current" means | Where |
|---|---|---|
| Typed columns | Latest value seen from *any* payload, fenced monotonically by `zoho_last_modified_time` | mirror row |
| `zoho_raw` | The last **authoritative full document** (richest class), stamped `zoho_raw_synced_at` | mirror row |
| Version stamp | Zoho's own `last_modified_time` — the entity's version number in all fencing | mirror row |
| **History** | Every prior version of every row — columns *and* `zoho_raw` — because Debezium streams each UPDATE to Kafka and ClickHouse retains them (`ReplacingMergeTree` keeps versions until merge; the Kafka topic and ClickHouse table are the audit trail) | CDC pipeline |

Postgres deliberately stores only the current version (mirror tables stay
lean and fast for FSA/DLP); point-in-time history is a ClickHouse query,
not a Postgres design burden. If a module ever needs *in-Postgres*
history (regulatory), that is a `zoho_raw_history` append table fed by a
trigger — a per-module opt-in, not the default.

---

## 2. Webhook ingress

### 2.1 What Zoho's outgoing webhooks actually are

Zoho Books/Inventory webhooks are configured per **workflow rule**
(Settings → Automation): *when \<module\> \<event/condition\>, POST this
JSON to this URL*. Three properties dictate the trust model:

1. **The payload is authored by a human in Zoho's UI** — a template of
   placeholders (or "all module parameters"). It is not a stable API
   contract: an admin editing the rule changes the shape with zero notice,
   and the shape can differ from the API detail document even when "all
   fields" is selected.
2. **Delivery is best-effort**: retries are limited, failures are
   eventually dropped, ordering is not guaranteed, and bursts can
   coalesce or interleave. A quiet webhook endpoint does not mean nothing
   changed (rules can be disabled, quota-limited, or mis-saved).
3. **They are near-real-time** — typically seconds after the mutation.

Hence the standing doctrine (v1 §10, now elaborated): **a webhook is a
trigger and a hint, never truth.** Truth is the API detail document; the
poller remains the guaranteed floor.

### 2.2 The ingress pipeline (E3) — and the answer to "how do I update `zoho_raw`?"

```
Zoho workflow rule fires (item rate changed / contact address edited / estimate sent)
   │  POST https://…/api/zoho/webhooks/{module}?token=…
   ▼
FastAPI ingress endpoint                      (< 100 ms, no Zoho calls, no heavy work)
   │ 1. verify shared secret (constant-time compare; 401 on mismatch)
   │ 2. extract zoho_id from the body (module's zoho_id_attr; fallback: probe
   │    common keys). No id extractable → journal 'webhook_unparseable' + 200.
   │ 3. journal zoho_queue_logs(operation="webhook_received", payload=body)
   │    — the raw webhook body is PRESERVED here for debugging/replay,
   │      which is why it never needs to pollute zoho_raw
   │ 4. debounce: Redis SET zoho:wh:{module}:{zoho_id} NX EX 3
   │    — a burst of edits coalesces into one fetch; losers of the race
   │      just return 200 (the winner's fetch captures the final state)
   │ 5. enqueue fetch_detail(module, zoho_id, queue_log_id)  ← EXISTING task
   │ 6. return 200 immediately (never let Zoho see an error for OUR bugs —
   │      failed processing is retried from the journal, not by Zoho)
   ▼
Celery fetch_detail (integrations queue — rate-limited, circuit-broken, journalled)
   │ GET /{module}/{zoho_id}            ← the AUTHORITATIVE current version
   ▼
upsert_payload(payload_kind="detail")
   │ columns updated (fenced by §1.4) · zoho_raw REPLACED · zoho_raw_synced_at,
   │ synced_at, sync_status stamped · sync_logs journalled
   ▼
Postgres commit → Debezium → Kafka → Meilisearch / ClickHouse / Soketi push
```

**So `zoho_raw` is updated by the fetch the webhook triggers, not by the
webhook body.** This one design choice buys:

- immunity to webhook-template drift (the admin can reshape the rule
  freely; we only ever needed the id);
- guaranteed provenance (`zoho_raw` is always the API document);
- ordering safety (the fetch always returns the *current* state, so even
  a late-delivered webhook for an old edit fetches fresh data — made
  harmless by the §1.4 fence);
- a single upsert path — webhook-driven, poll-driven, and echo-driven
  updates all converge on the same tested code.

Cost: one extra API call per (debounced) webhook — a few requests/min
against the 100/min budget in realistic THPL edit volumes, journalled and
rate-limited like every other call.

**Deletion events:** a workflow rule can fire on delete, but the fetch
will 404. `fetch_detail` already handles this (`ZohoNotFoundError` →
`gone_upstream` skip); extend it: on 404 for a row that exists locally →
soft-delete the row (same treatment as `soft_delete_missing`
reconciliation). A webhook-triggered 404 is *evidence of upstream
deletion*, and it arrives days before the weekly full-sync would notice.

### 2.3 The optional optimistic lane — deliberately OFF by default

Could we apply the webhook body's fields to columns immediately (mapper
skips unknown/missing keys; transforms are lenient) and let the fetch
confirm? Yes — it would shave 1–3 s of latency. It is **not the default**
because it doubles the write paths for a latency win below what FSA/DLP
can perceive, and it opens a window where columns reflect a
human-authored template while `zoho_raw` reflects the older document. If
a specific module ever justifies it (it would need sub-second
column-freshness — none currently does), it ships as
`webhook_optimistic_apply=True` module config, reusing
`upsert_payload(payload_kind="webhook")` with the §1.2 rule already
guaranteeing `zoho_raw` is untouched. Decide per module, with a stated
reason — not fleet-wide.

### 2.4 Failure modes

| Failure | Behaviour |
|---|---|
| Webhook secret wrong / URL probed | 401, no journal write beyond a rate-limited security log |
| Unparseable body / missing id | journalled `webhook_unparseable`, 200 returned; visible in queue-log admin API |
| Burst of 20 edits in 3 s | one debounced fetch captures the final state |
| Webhook dropped by Zoho | incremental poller catches the change within `sync_interval_minutes` (the floor) |
| Fetch fails (429/5xx/circuit open) | normal Celery backoff on `fetch_detail`; journal row shows `failed` + error |
| Webhook for a record we've never seen | fetch + upsert **creates** the mirror row (identity matching already handles create) |
| Zoho webhook quota exhausted / rule disabled | silent — which is why the poller is never removed and `zoho_raw_synced_at` staleness is monitorable |

---

## 3. Walkthrough: Estimate status

*Scenario: an accountant opens Zoho and flips estimate `EST-00042` from
`draft` to `sent`. What happens in the middleware?*

Preconditions from v1: estimates are **O2 (locally-authored
transactionals)** — we author commercial content (`line_items`, discounts,
notes); Zoho authors accounting consequences (`estimate_number`, computed
totals, **`status`**). In the field map, `status` is `outbound=False`:
Zoho-authored, inbound-freely-applied, never pushed.

```
 1. Accountant clicks "Mark as Sent" in Zoho.
 2. Workflow rule (estimates, on-edit/status-change) POSTs to
    /api/zoho/webhooks/estimates with whatever body the rule defines.
 3. Ingress: secret ✓ → estimate_id extracted → journal → debounce →
    fetch_detail("estimates", "954…") queued → 200 to Zoho.       [< 100 ms]
 4. Worker: GET /estimates/954…  → full document, status="sent",
    last_modified_time=T₂.
 5. upsert_payload(kind="detail"):
      - fence check: T₂ > stored T₁ → apply.
      - status column: "draft" → "sent"   (outbound=False ⇒ no conflict
        check against pending local edits — Zoho owns this field).
      - zoho_raw ← the new full document; zoho_raw_synced_at = now.
      - sync_logs += {"event":"inbound_upsert","source":"webhook_fetch"}.
 6. COMMIT → WAL → Debezium → Kafka zoho-mirror.public.zoho_estimates.
 7. Fan-out (~1–3 s total from step 1):
      - Meilisearch: estimate now facets under status=sent.
      - ClickHouse: status-transition history row (T₁→T₂ both retained).
      - Soketi consumer: publishes estimate.updated to the owning agent's
        channel → FSA badge flips to "Sent" live.
 8. If no webhook rule existed / it was dropped: the estimates incremental
    poll (last_modified_time ≥ cursor) applies the identical steps 5–7
    within one sync interval. Same code path, later arrival.
```

**Conflict case for completeness:** suppose the FSA agent had *locally*
edited the same estimate's `notes` (an `outbound=True` field) seconds
before, outbox not yet pushed. Step 5 applies `status` freely
(Zoho-authored) but the §1.4 fence + v1 §9.1 field-authority rule keeps
the locally-dirty `notes` untouched; the outbox then pushes `notes`, and
its echo (carrying T₃ > T₂) converges both sides. If Zoho had *also*
edited `notes`, the row is flagged `sync_status='conflict'` with both
values journalled — surfaced, not silently merged.

**The mirror-image flow** — FSA marks the estimate sent locally — never
PUTs the whole document: the outbox op vocabulary (v1 §7.3) uses Zoho's
sub-resource endpoint `POST /estimates/{id}/status/sent`, then the echo
fetch updates status/zoho_raw exactly as above. Status is a **state
machine Zoho owns** (`draft → sent → invoiced/accepted/declined/expired`;
invoices add `overdue/paid/void/partially_paid/viewed`); we request
transitions, we never compute states.

---

## 4. Stock freshness

*Requirement: sales/delivery teams should see what's on stock "every few
seconds".*

### 4.1 Two facts that reshape the requirement

**Fact 1 — stock is a *derived* quantity, so incremental item sync misses
it.** `stock_on_hand` changes when *transactions* happen — an invoice is
raised, a bill is received, an adjustment is made. Those transactions do
**not** edit the item record, so the item's `last_modified_time` does not
reliably bump — an incremental items sync keyed on `last_modified_time`
can sail past stock changes indefinitely. Stock freshness therefore needs
its own lanes; it cannot ride the ordinary incremental sync. (Rate edits
DO bump the item and are caught normally — your webhook in §2 covers
those.)

**Fact 2 — "every few seconds" is two different requirements in disguise.**
*The team seeing stock within seconds* is a requirement on **our** push
pipeline (Postgres → CDC → Soketi), which already operates at 1–3 s and
costs Zoho nothing. *Postgres learning about a Zoho-side change within
seconds* is a requirement on the **Zoho-facing lanes**, where the 100
req/min budget rules. Solve them separately and the problem gets cheap.

### 4.2 Why literal fast polling is not the answer

Budget math for sweeping `GET /items` (200 rows/page):

| Catalog size | Requests/sweep | Every 10 s | Every 60 s | Every 5 min |
|---|---|---|---|---|
| ≤ 200 items | 1 | 6/min (6%) | 1/min (1%) | 0.2/min |
| 1 000 items | 5 | 30/min (30%) | 5/min (5%) | 1/min |
| 5 000 items | 25 | **150/min — over budget alone** | 25/min (25%) | 5/min (5%) |

A "every few seconds" sweep is already impossible at 1k items and
consumes the whole org budget at 5k — starving every other module's sync
and all outbound pushes. Polling *harder* is a dead end; polling
*smarter* (targeted, event-driven, with a modest sweep as the floor) is
the design.

### 4.3 The three-layer stock design

```
Layer 1 — event-driven, targeted (seconds, precise)
  Zoho webhook on stock-AFFECTING transactions (invoices, sales orders,
  credit notes, bills, purchase receives, inventory adjustments)
     → ingress (§2) fetches the TRANSACTION document
     → its line_items[] name exactly which item_ids moved
     → enqueue refresh_item_stock(item_ids) — debounced per item (Redis set,
       flushed every few seconds)
     → ONE call: GET /itemdetails?item_ids=id1,id2,…   (bulk detail, items.md)
     → upsert each returned item (payload_kind="detail" — full document,
       zoho_raw legitimately refreshed)
  Cost: 1–2 requests per business transaction, regardless of how many items
  it touched. An invoice with 30 line items = one /itemdetails call.

Layer 2 — the stock sweep, the guaranteed floor (minutes, exhaustive)
  A SECOND registered module over the SAME table (E4):
      module="items_stock", endpoint="/items", strategy=INDEX,
      sync_interval_minutes=2–5, field_map = zoho_id + stock_on_hand +
      available_stock + actual_available_stock (+ per-location via the
      list row's locations[] when present), soft_delete_missing=False
  INDEX strategy ⇒ list-only, never N+1; payload_kind="list" ⇒ under §1.2
  it updates stock COLUMNS and never touches zoho_raw. This is exactly the
  "periodically fetch items with stock" you asked for — priced at
  items/200 requests per sweep, catching anything Layer 1's webhooks
  dropped, and structurally incapable of degrading the item documents.

Layer 3 — the team-facing push (sub-second, free)
  zoho_items UPDATE → WAL → Debezium → Kafka → a thin FastStream consumer
  (sibling of the search indexer) diffs stock fields and publishes
  item.stock_changed {item_id, sku, stock_on_hand, location_breakdown}
  to Soketi channels; FSA/DLP subscribe per beat/route. Sales agents see
  stock move without ANY polling — of Zoho or of us. (Clients that prefer
  polling hit OUR /api endpoints backed by Postgres: unlimited, cheap.)
```

Net freshness: **seconds** when a transaction fires a webhook (the normal
case — stock changes are caused by transactions), **≤ sweep interval**
worst case, and the Zoho budget spend is a few requests/min at THPL scale
— leaving the budget to the other 38 modules and the outbox.

### 4.4 Direct answers to your questions

- *"Will the periodic fetch update the payload?"* — It updates the stock
  **columns** on every sweep. It does **not** overwrite `zoho_raw`
  (list-provenance, §1.2) — before this v2 rule, it would have, and that
  was a defect, not a feature you were missing. The item's `zoho_raw`
  refreshes whenever a detail-class payload flows (webhook-triggered
  fetch, `/itemdetails` bulk refresh, ordinary detail sync, outbound
  echo).
- *"Is there a better approach?"* — Yes: §4.3. Poll our Postgres/WebSockets
  as hard as you like; touch Zoho only when events say something moved,
  plus a cheap exhaustive sweep as the floor.

---

## 5. Line-item snapshots

*An Estimate/Invoice records its line items with the prices as sold —
discounted rates, free items, the item's cost at that moment. Later
changes to the item master must never rewrite history.*

### 5.1 Zoho already works this way — mirror it, don't fight it

When you `POST /invoices`, each line item's `rate`, `discount`, `tax_id`
is **copied into the document** at creation; the line item stores values,
not references to live item fields. Proof from the vendored docs that
propagation is opt-in and *forward-only*: updating a **tax**
(`taxes.md`) exposes explicit flags — `update_draft_invoice`,
`update_recurring_invoice`, `update_draft_so`, … — i.e. even Zoho only
propagates master changes into *drafts and recurring templates* when
explicitly asked, and **never** into issued documents. The item master's
`rate` is merely the *default* offered at composition time.

### 5.2 The child-table contract (E7, refining v1's G1)

`zoho_estimate_line_items` / `zoho_invoice_line_items`:

```python
class ZohoEstimateLineItem(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "zoho_estimate_line_items"

    estimate_id:  Mapped[int]        # FK -> zoho_estimates.id (CASCADE with parent)
    zoho_line_item_id: Mapped[str | None]   # Zoho's line_item_id (NULL until echo)

    # ── Reference (navigation & analytics ONLY — never re-derivation) ──
    item_id:      Mapped[int | None]        # FK -> zoho_items.id
    item_zoho_id: Mapped[str | None]

    # ── SNAPSHOT columns — copied at composition, immutable thereafter ──
    name:         Mapped[str | None]        # item name as sold
    description:  Mapped[str | None]
    rate:         Mapped[Decimal | None]    # price CHARGED (0 for free items)
    quantity:     Mapped[Decimal | None]
    unit:         Mapped[str | None]
    discount:     Mapped[str | None]        # Zoho semantics: "10%" or amount
    discount_amount: Mapped[Decimal | None]
    tax_zoho_id:  Mapped[str | None]        # tax AS APPLIED then — the tax
    tax_name:     Mapped[str | None]        #   master may change % later;
    tax_percentage: Mapped[Decimal | None]  #   this row keeps the truth as billed
    item_total:   Mapped[Decimal | None]    # Zoho-computed, from the echo
    item_order:   Mapped[int | None]
    hsn_or_sac:   Mapped[str | None]

    # ── LOCAL-ONLY enrichment (never sent to Zoho, never overwritten by sync) ──
    purchase_rate_snapshot: Mapped[Decimal | None]  # item cost at composition —
                                                    # margin analytics per order;
                                                    # Zoho has no such field on
                                                    # line items at all
    list_rate_snapshot: Mapped[Decimal | None]      # undiscounted rate offered
    pricing_source: Mapped[str | None]              # 'pricebook:<id>' | 'item_master' | 'manual'
```

**The four rules that make history immutable:**

1. **Composition copies, never links.** When FSA builds an estimate, the
   service reads the *current* item master (and the contact's pricebook —
   contacts carry `pricebook_id`) to *propose* `rate`, then **copies** the
   final values (after agent discounts, free-item zeroing) into the child
   rows, including the local-only `purchase_rate_snapshot` /
   `list_rate_snapshot` captured in the same transaction. A free item is
   simply `rate=0` (or 100% discount) — data, not a special case.
2. **Item sync never touches line items.** The items module's inbound
   upsert (any lane: incremental, stock sweep, webhook fetch) writes
   `zoho_items` only. Nothing recomputes or cascades into
   `zoho_*_line_items`. There is deliberately **no ORM relationship-driven
   write path** from item → line items; `item_id` exists for
   `selectinload` navigation and "sales of item X" analytics.
3. **Line items refresh only from their own parent's document.** When an
   estimate's detail payload arrives (echo, webhook fetch, poll), the
   child-collection upsert (v1 G1) replace-sets the children **from that
   document's `line_items[]`**, diffing by `line_item_id` — Zoho's
   document is authoritative *for the document's own content* (an
   accountant may legitimately edit a draft's line items in Zoho).
   Local-only snapshot columns (`purchase_rate_snapshot`, …) are, by
   definition, absent from Zoho payloads — the mapper's missing-key rule
   preserves them through every refresh.
4. **Outbound sends the snapshot.** The estimate's outbound builder (v1
   G5) emits `line_items: [{item_id: <zoho_id>, rate, quantity, discount,
   tax_id, hsn_or_sac}]` from the child rows — the *charged* rate, not the
   master's current rate. Zoho computes totals; the echo back-fills
   `line_item_id`, `item_total`, and authoritative totals on the parent.

Temporal-correctness result: *"what did we sell it for, what did it cost
us, what tax applied"* is answered forever by the child row, regardless
of how many times the item master's `rate`, the tax's percentage, or the
pricebook change afterwards. The tax master (`zoho_taxes`) can even be
soft-deleted upstream — the line item's `tax_name`/`tax_percentage`
columns keep the billed truth.

---

## 6. Engine deltas

Consolidated change list, mapped to v1's roadmap gaps:

| # | Change | Touches | v1 gap |
|---|---|---|---|
| **E1** | `payload_kind` provenance + `zoho_raw` write rule + `zoho_raw_synced_at` column | `engine.upsert_payload`, `mixins.py` (1 column), all call sites pass kind | *(new — defect fix)* |
| **E2** | Monotonic fence on `zoho_last_modified_time` (standing Class-A column on every module's field map) | `engine.upsert_payload` | closes §9.2 echo suppression |
| **E3** | Webhook ingress: `POST /api/zoho/webhooks/{module}` (secret, id-extraction, journal, Redis debounce, `fetch_detail` enqueue, 404→soft-delete) + `webhook_secret`/`webhook_optimistic_apply` config knobs | new `zoho/webhooks/` package + config | G4 |
| **E4** | Multi-lane modules: allow a second `ZohoModuleDefinition` over the same model (`items_stock`) — requires only relaxing the registry's one-definition-per-model assumption; INDEX strategy + E1 already make the lane safe | `registry.py` | *(new)* |
| **E5** | Bulk detail fetch: `bulk_detail_endpoint`/`bulk_detail_param` config + `fetch_details_bulk` task chunking ids (`/itemdetails?item_ids=…`) | config, tasks | *(new)* |
| **E6** | Stock propagation: transactional modules declare `stock_touching=True`; after their upsert, line-item `item_zoho_id`s land in a Redis debounce set flushed by a beat task into `fetch_details_bulk` | engine post-upsert hook + small beat entry | *(new)* |
| **E7** | Child-collection replace-set upsert (line items, addresses, persons) with local-only column preservation | engine + per-module child configs | G1 |
| **E8** | Soketi push consumer (`stock_changed`, `estimate.updated`) — FastStream sibling of the search indexer, same CDC topics | new consumer service | G4b |

Build order (revised v1 §12.2): **E1+E2 first** (they fix a live defect
and everything else depends on the provenance/fencing semantics), then O1
masters → E7+contacts → items + E3/E4/E5/E6 (the full stock stack) → E8 →
estimates end-to-end → conflict machinery → long tail.

Testing per doctrine: E1/E2 are pure engine-behaviour tests
(FakeZohoClient + scratch Postgres: *list upsert must not overwrite
detail-provenance `zoho_raw`*; *stale payload must not regress columns*);
E3 gets route tests with `dependency_overrides` + a signature-failure
case; E7 gets replace-set diff tests including the local-only-column
preservation case; E8 through `TestKafkaBroker`.

---

## 7. Complete topology

```
                        ZOHO BOOKS / INVENTORY
      │ ▲                      │                        │
      │ │ outbox pushes        │ webhooks (trigger+id)  │ polls (floor)
      │ │ (write contract,     ▼                        ▼
      │ │  sub-resource ops) ┌──────────────┐   ┌───────────────────────────┐
      │ │                    │ /api/zoho/   │   │ Beat dispatcher            │
      │ │                    │ webhooks/{m} │   │  · incremental (per module)│
      │ │                    │ verify·journal│  │  · items_stock INDEX sweep │
      │ │                    │ ·debounce    │   │  · weekly FULL safety net  │
      │ │                    └──────┬───────┘   └────────────┬──────────────┘
      │ │                           │ fetch_detail /         │ list pages
      │ │                           │ fetch_details_bulk     │
      │ │                           ▼                        ▼
      │ │                ┌─────────────────────────────────────────────┐
      │ └────────────────┤            upsert_payload(payload_kind)      │
      │      echo        │  mapper (skip-missing) · E2 version fence ·  │
      │   (detail kind)  │  E1 zoho_raw provenance · nested routing ·   │
      │                  │  E7 child replace-set · custom_fields hstore │
      │                  └──────────────────┬──────────────────────────┘
      │                                     ▼
      │            ┌─────────────────  PostgreSQL  ─────────────────────┐
      │            │ zoho_items (+stock cols)   zoho_estimates          │
   FSA/DLP ───────►│ zoho_contacts (+PostGIS)   zoho_*_line_items(snap) │
   writes          │ zoho_taxes/currencies…     queue_logs/sync_stats   │
   (local-first,   └───────────────┬────────────────────────────────────┘
    outbox in txn)                 │ WAL
                                   ▼
                          Debezium → Kafka ─┬─► search-indexer → Meilisearch
                                            ├─► ClickHouse (current + HISTORY)
                                            └─► E8 push consumer → Soketi
                                                        │
   FSA / DLP  ◄── live stock & status badges ───────────┘
   (reads: Postgres API + WebSockets only — never Zoho)
```

---

## 8. Invariants

Additions to v1 §13's never-do list — these are the load-bearing rules of
this document:

1. **`zoho_raw` is written only by the richest payload class the module
   can obtain** — never by list rows on detail-capable modules, never by
   webhook bodies, never by nested embeds. (§1.2)
2. **Never apply a payload older than the row's
   `zoho_last_modified_time`.** Journal it, skip it. (§1.4)
3. **Webhook bodies are triggers, not data.** Verify, journal, debounce,
   fetch, upsert. Always return 200 for our own processing failures — the
   journal retries, Zoho doesn't. (§2)
4. **Never remove the poller because webhooks exist**, and never tighten a
   poll below what the budget table (§4.2) justifies. Freshness for
   *people* comes from Soketi/CDC, not from Zoho-facing polling.
5. **Stock never rides ordinary incremental sync** — it moves without
   bumping the item's `last_modified_time`. Stock has its own lanes:
   transaction-webhook → `/itemdetails` bulk, plus the INDEX sweep.
   (§4.1, §4.3)
6. **Snapshot columns are written exactly once, at composition.** No sync
   lane, relationship cascade, or master update may rewrite a line item's
   charged rate, applied tax, or cost snapshot; document children refresh
   only from their own parent's payload, and local-only columns survive
   every refresh by the missing-key rule. (§5.2)
7. **Status is a Zoho-owned state machine.** We mirror states inbound
   (`outbound=False`) and request transitions outbound via sub-resource
   endpoints — we never compute or force a state locally. (§3)
8. **One upsert path.** Poll, webhook-fetch, bulk-fetch, and outbound echo
   all converge on `upsert_payload` — never add a side channel that
   writes mirror rows around the engine.

---

*Supersedes/refines:* [zoho-architecture-decision-framework.md](zoho-architecture-decision-framework.md)
§10 (freshness — now §2/§4 here) and the v1 assumption that every upsert
refreshes `zoho_raw` (now governed by §1). Storage doctrine, field
taxonomy, ownership classes, and the outbound write contract are
unchanged and remain in v1.
