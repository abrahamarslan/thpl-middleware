"""Field catalog for the Zoho Books tax configuration (schema reverse-engineering
standard, R11) — the LINEAGE record, not the executable contract.

Two vocabularies, deliberately kept apart:

  * this catalog says what every source leaf path IS — its primary class
    (A–K), layer (L1/L2/L3/snapshot/drop), target, transform, error policy,
    authority, outbound posture, sensitivity and mapping version;
  * ``zoho/fields.py`` is what the sync actually RUNS — ``FieldSpec`` rows
    (``external``/``local``/``codec``/``direction``) consumed by the translation
    layer (``app.modules.sync.translation``).

The catalog's dataclass is therefore ``FieldCatalogEntry``, not ``FieldMapping``:
``app.modules.zoho.sync.config.FieldMapping`` already names the executable type,
and two unrelated things sharing a name is how one gets edited believing it is
the other. ``tests/test_tax_schema.py`` keeps them honest — every entry's target
must be a real column, and every entry the sync executes must have a matching
``FieldSpec`` — so this file cannot rot into fiction.

Source objects covered (from the captured Zoho payloads):
  * ``default_taxes[]``  → org_default_tax_preferences + the referenced component.
    (No adapter yet: the endpoint is not in docs/zoho-docs-md.)
  * ``gst_treatments[]`` / ``tax_treatments[]`` → gst_treatment_types (identical
    shapes, collapsed, deduped on ``value``). (No adapter yet, same reason.)
  * ``tax`` detail / ``tax_group`` detail → tax_components (+ tax_group_members).
  * ``tax_exemptions[]`` → tax_exemptions.

Conventions and deliberate exceptions
-------------------------------------
* **External identity (Class A) never lands on ``tax.*``.** Every ``tax_id``,
  ``tax_group_id`` and ``tax_exemption_id`` maps to the crosswalk
  (``sync.sync_records``: ``external_id``; ``last_modified_time`` →
  ``source_modified_at``). No tax table carries a source id column.
* **Context / computed columns are not leaf paths and have no entry:**
  ``tenant_id`` / ``organization_id`` come from request context,
  ``created_by`` / ``updated_by`` are app-owned, and organization access to a
  component (``organization_tax_components``) is app-owned context — the sync's
  post-hook grants it, no payload leaf says so. ``content_hash`` is not stamped
  by the sync: the crosswalk's ``raw_hash`` is the sync's hash (AP1).
* **``*_formatted`` is a documented exception to the no-Class-E rule.** Three
  formatted twins are kept as L1 display caches (``tax_name_formatted``,
  ``type_formatted``, ``exemption_type_formatted``) plus ``value_formatted`` on
  the treatment vocabulary; every other formatted key is dropped.
* **Empty-string-as-null** is the ``empty_to_null`` transform; business dates use
  ``zoho_date`` (day granularity, AP7).
* **Open vocabularies carry no CHECK** (``tax_exemptions.type`` /
  ``exemption_type``) so an unknown upstream value is stored, never halts a batch (AP8).

Transform names → executable codecs: see ``TRANSFORM_CODECS``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class FieldCatalogEntry:
    source_path: str
    capture_kinds: tuple[str, ...]
    primary_class: Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]
    layer: Literal["L1", "L2", "L3", "snapshot", "drop"]
    target: str | None
    transform: str | None
    on_error: Literal["quarantine_record", "null_and_warn", "reject_batch"]
    authority: Literal["source", "app", "shared", "computed"]
    outbound: Literal["never", "writable", "create_only", "pending_verification"]
    outbound_key: str | None
    sensitivity: Literal["P0", "P1", "P2", "P3", "S"]
    mapping_version: int


_E = FieldCatalogEntry
_ID = "sync.sync_records.external_id"
_MODIFIED = "sync.sync_records.source_modified_at"
_TC = "tax.tax_components"
_GT = "tax.gst_treatment_types"
_EX = "tax.tax_exemptions"

TAX_V1_MAPPINGS: tuple[FieldCatalogEntry, ...] = (
    # =========================================================================
    # default_taxes[]  (list) -- org default-tax preferences and the component
    #                            each default points at.
    # =========================================================================
    _E("default_taxes[].tax_id", ("list",), "A", "L3", _ID, None, "reject_batch", "source", "never", None, "P1", 1),
    _E("default_taxes[].tax_name", ("list",), "B", "L2", f"{_TC}.tax_name", "trim", "quarantine_record", "shared", "pending_verification", "tax_name", "P1", 1),
    _E("default_taxes[].tax_percentage", ("list",), "B", "L2", f"{_TC}.tax_percentage", "decimal_rate", "quarantine_record", "shared", "pending_verification", "tax_percentage", "P0", 1),
    _E("default_taxes[].tax_type", ("list",), "B", "L1", f"{_TC}.source_default_tax_type_code", "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("default_taxes[].new_tax_type", ("list",), "B", "L1", f"{_TC}.source_new_tax_type", "map_tax_type", "null_and_warn", "source", "never", None, "P1", 1),
    _E("default_taxes[].tax_specific_type", ("list",), "B", "L2", f"{_TC}.tax_specific_type", "canonical_specific_type", "null_and_warn", "shared", "pending_verification", "tax_specific_type", "P1", 1),
    _E("default_taxes[].tax_name_formatted", ("list",), "E", "L1", f"{_TC}.tax_name_formatted", "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("default_taxes[].is_non_advol_tax", ("list",), "B", "L2", f"{_TC}.is_non_advol_tax", "bool", "null_and_warn", "shared", "pending_verification", "is_non_advol_tax", "P1", 1),
    _E("default_taxes[].tax_groups_details[]", ("list",), "G", "snapshot", None, None, "null_and_warn", "source", "never", None, "P1", 1),
    _E("default_taxes[].tax_specification", ("list",), "B", "L2", "tax.org_default_tax_preferences.tax_specification", "lower|empty_to_null", "quarantine_record", "shared", "pending_verification", "tax_specification", "P1", 1),

    # =========================================================================
    # gst_treatments[] / tax_treatments[]  (list) -- identical shapes under two
    #   API key names; collapse into one reference table, dedupe on `value`.
    # =========================================================================
    _E("gst_treatment.code", ("list",), "B", "L2", f"{_GT}.code", "identity", "quarantine_record", "source", "never", None, "P1", 1),
    _E("gst_treatment.value", ("list",), "B", "L2", f"{_GT}.value", "lower|trim", "quarantine_record", "source", "never", None, "P1", 1),
    _E("gst_treatment.label", ("list",), "B", "L2", f"{_GT}.label", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("gst_treatment.value_formatted", ("list",), "E", "L1", f"{_GT}.value_formatted", "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("gst_treatment.description", ("list",), "B", "L2", f"{_GT}.description", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("gst_treatment.category", ("list",), "B", "L2", f"{_GT}.category", "lower", "quarantine_record", "source", "never", None, "P1", 1),
    _E("gst_treatment.allowed_for_sales", ("list",), "B", "L2", f"{_GT}.allowed_for_sales", "bool", "null_and_warn", "source", "never", None, "P1", 1),
    _E("gst_treatment.allowed_for_purchase", ("list",), "B", "L2", f"{_GT}.allowed_for_purchase", "bool", "null_and_warn", "source", "never", None, "P1", 1),

    _E("tax_treatment.code", ("list",), "B", "L2", f"{_GT}.code", "identity", "quarantine_record", "source", "never", None, "P1", 1),
    _E("tax_treatment.value", ("list",), "B", "L2", f"{_GT}.value", "lower|trim", "quarantine_record", "source", "never", None, "P1", 1),
    _E("tax_treatment.label", ("list",), "B", "L2", f"{_GT}.label", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_treatment.value_formatted", ("list",), "E", "L1", f"{_GT}.value_formatted", "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_treatment.description", ("list",), "B", "L2", f"{_GT}.description", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_treatment.category", ("list",), "B", "L2", f"{_GT}.category", "lower", "quarantine_record", "source", "never", None, "P1", 1),
    _E("tax_treatment.allowed_for_sales", ("list",), "B", "L2", f"{_GT}.allowed_for_sales", "bool", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_treatment.allowed_for_purchase", ("list",), "B", "L2", f"{_GT}.allowed_for_purchase", "bool", "null_and_warn", "source", "never", None, "P1", 1),

    # =========================================================================
    # tax detail (single component, tax_type = 'tax')
    # =========================================================================
    _E("tax.tax_id", ("detail",), "A", "L3", _ID, None, "reject_batch", "source", "never", None, "P1", 1),
    _E("tax.tax_display_name", ("detail",), "B", "L2", f"{_TC}.tax_display_name", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "tax_display_name", "P1", 1),
    _E("tax.tax_name", ("detail",), "B", "L2", f"{_TC}.tax_name", "trim", "quarantine_record", "shared", "pending_verification", "tax_name", "P1", 1),
    _E("tax.tax_percentage", ("detail",), "B", "L2", f"{_TC}.tax_percentage", "decimal_rate", "quarantine_record", "shared", "pending_verification", "tax_percentage", "P0", 1),
    _E("tax.tax_type", ("detail",), "B", "L2", f"{_TC}.tax_type", "map_tax_type", "quarantine_record", "shared", "pending_verification", "tax_type", "P1", 1),
    _E("tax.tax_specific_type", ("detail",), "B", "L2", f"{_TC}.tax_specific_type", "canonical_specific_type", "null_and_warn", "shared", "pending_verification", "tax_specific_type", "P1", 1),
    _E("tax.tax_authority_id", ("detail",), "C", "L2", f"{_TC}.tax_authority_id", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax.tax_authority_name", ("detail",), "C", "L2", f"{_TC}.tax_authority_name", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax.output_tax_account_name", ("detail",), "B", "L2", f"{_TC}.output_tax_account_name", "trim|empty_to_null", "null_and_warn", "source", "pending_verification", "output_tax_account_name", "P1", 1),
    _E("tax.tax_account_id", ("detail",), "C", "L2", f"{_TC}.tax_account_id", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax.is_inactive", ("detail",), "B", "L2", f"{_TC}.is_inactive", "bool", "null_and_warn", "shared", "pending_verification", "is_inactive", "P1", 1),
    _E("tax.is_default_tax", ("detail",), "B", "L2", f"{_TC}.is_default_tax", "bool", "null_and_warn", "shared", "pending_verification", "is_default_tax", "P1", 1),
    _E("tax.is_editable", ("detail",), "B", "L2", f"{_TC}.is_editable", "bool", "null_and_warn", "shared", "pending_verification", "is_editable", "P1", 1),
    _E("tax.tax_specification", ("detail",), "B", "L2", f"{_TC}.tax_specification", "lower|empty_to_null", "null_and_warn", "shared", "pending_verification", "tax_specification", "P1", 1),
    _E("tax.diff_rate_reason", ("detail",), "B", "L2", f"{_TC}.diff_rate_reason", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "diff_rate_reason", "P1", 1),
    _E("tax.start_date", ("detail",), "B", "L2", f"{_TC}.start_date", "zoho_date", "null_and_warn", "shared", "pending_verification", "start_date", "P1", 1),
    _E("tax.end_date", ("detail",), "B", "L2", f"{_TC}.end_date", "zoho_date", "null_and_warn", "shared", "pending_verification", "end_date", "P1", 1),
    _E("tax.last_modified_time", ("detail",), "A", "L3", _MODIFIED, "zoho_datetime", "reject_batch", "source", "never", None, "P1", 1),
    _E("tax.status", ("detail",), "B", "L2", f"{_TC}.status", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "status", "P1", 1),
    _E("tax.description", ("detail",), "B", "L2", f"{_TC}.description", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "description", "P1", 1),
    _E("tax.reference_id", ("detail",), "B", "L2", f"{_TC}.reference_id", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    # Present on group detail only; no canonical column (see tax.tax_name_formatted below).
    _E("tax.tax_name_formatted", ("detail",), "E", "L1", f"{_TC}.tax_name_formatted", "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax.is_state_cess", ("detail",), "B", "L2", f"{_TC}.is_state_cess", "bool", "null_and_warn", "shared", "pending_verification", "is_state_cess", "P1", 1),
    _E("tax.tds_payable_account_id", ("detail",), "C", "L2", f"{_TC}.tds_payable_account_id", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),

    # Documented by docs/zoho-docs-md/taxes.md but absent from the captured payloads:
    # kept so a tenant in that edition does not silently lose them.
    _E("tax.tax_factor", ("detail",), "B", "L2", f"{_TC}.tax_factor", "trim|empty_to_null", "null_and_warn", "shared", "writable", "tax_factor", "P1", 1),
    _E("tax.is_value_added", ("detail",), "B", "L2", f"{_TC}.is_value_added", "bool", "null_and_warn", "shared", "writable", "is_value_added", "P1", 1),
    _E("tax.country", ("detail",), "B", "L2", f"{_TC}.country", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax.country_code", ("detail",), "B", "L2", f"{_TC}.country_code", "trim|empty_to_null", "null_and_warn", "shared", "writable", "country_code", "P1", 1),
    _E("tax.purchase_tax_account_id", ("detail",), "C", "L2", f"{_TC}.purchase_tax_account_id", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax.purchase_tax_account_name", ("detail",), "B", "L2", f"{_TC}.purchase_tax_account_name", "trim|empty_to_null", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax.purchase_tax_expense_account_id", ("detail",), "C", "L2", f"{_TC}.purchase_tax_expense_account_id", "int", "null_and_warn", "shared", "writable", "purchase_tax_expense_account_id", "P1", 1),

    # =========================================================================
    # tax_group detail (composite row + its normalized member rows)
    # =========================================================================
    _E("tax_group.tax_group_id", ("detail",), "A", "L3", _ID, None, "reject_batch", "source", "never", None, "P1", 1),
    _E("tax_group.tax_type", ("detail",), "B", "L2", f"{_TC}.tax_type", "map_tax_type", "quarantine_record", "shared", "pending_verification", "tax_type", "P1", 1),
    _E("tax_group.tax_group_name", ("detail",), "B", "L2", f"{_TC}.tax_name", "trim", "quarantine_record", "shared", "pending_verification", "tax_group_name", "P1", 1),
    _E("tax_group.tax_group_percentage", ("detail",), "B", "L2", f"{_TC}.tax_percentage", "decimal_rate", "quarantine_record", "shared", "pending_verification", "tax_group_percentage", "P0", 1),
    _E("tax_group.status", ("detail",), "B", "L2", f"{_TC}.status", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "status", "P1", 1),
    _E("tax_group.start_date", ("detail",), "B", "L2", f"{_TC}.start_date", "zoho_date", "null_and_warn", "shared", "pending_verification", "start_date", "P1", 1),
    _E("tax_group.end_date", ("detail",), "B", "L2", f"{_TC}.end_date", "zoho_date", "null_and_warn", "shared", "pending_verification", "end_date", "P1", 1),
    # Owned sub-record array -> child table. `position` is derived from array index.
    _E("tax_group.taxes[]", ("detail",), "D", "L2", "tax.tax_group_members", None, "reject_batch", "shared", "pending_verification", None, "P1", 1),
    _E("tax_group.taxes[].tax_id", ("detail",), "C", "L2", "tax.tax_group_members.member_tax_id", "resolve_component_by_external", "quarantine_record", "shared", "never", None, "P1", 1),
    # Member display/rate facts are owned by the member component row -> snapshot.
    _E("tax_group.taxes[].tax_display_name", ("detail",), "C", "snapshot", None, "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_group.taxes[].tax_name", ("detail",), "C", "snapshot", None, "trim", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_group.taxes[].tax_percentage", ("detail",), "C", "snapshot", None, "decimal_rate", "null_and_warn", "source", "never", None, "P0", 1),
    _E("tax_group.taxes[].tax_type", ("detail",), "C", "snapshot", None, "map_tax_type", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_group.taxes[].tax_specific_type", ("detail",), "C", "snapshot", None, "lower", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_group.taxes[].tax_authority_id", ("detail",), "C", "snapshot", None, "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_group.taxes[].start_date", ("detail",), "C", "snapshot", None, "zoho_date", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_group.taxes[].end_date", ("detail",), "C", "snapshot", None, "zoho_date", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_group.taxes[].status", ("detail",), "C", "snapshot", None, "trim", "null_and_warn", "source", "never", None, "P1", 1),

    # =========================================================================
    # tax_exemptions[]  (list) -- P2 fields carry the person-name contamination
    #                              finding; erasure must anonymize, never drop
    #                              the row's identity here.
    # =========================================================================
    _E("tax_exemption.tax_exemption_id", ("list",), "A", "L3", _ID, None, "reject_batch", "source", "never", None, "P1", 1),
    _E("tax_exemption.tax_exemption_code", ("list",), "B", "L2", f"{_EX}.tax_exemption_code", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "tax_exemption_code", "P2", 1),
    _E("tax_exemption.description", ("list",), "B", "L2", f"{_EX}.description", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "description", "P1", 1),
    _E("tax_exemption.type", ("list",), "B", "L2", f"{_EX}.type", "lower|empty_to_null", "null_and_warn", "shared", "pending_verification", "type", "P1", 1),
    _E("tax_exemption.type_formatted", ("list",), "E", "L1", f"{_EX}.type_formatted", "identity", "null_and_warn", "source", "never", None, "P1", 1),
    _E("tax_exemption.exemption_name", ("list",), "B", "L2", f"{_EX}.exemption_name", "trim|empty_to_null", "null_and_warn", "shared", "pending_verification", "exemption_name", "P2", 1),
    _E("tax_exemption.exemption_type", ("list",), "B", "L2", f"{_EX}.exemption_type", "lower|empty_to_null", "null_and_warn", "shared", "pending_verification", "exemption_type", "P1", 1),
    _E("tax_exemption.exemption_type_formatted", ("list",), "E", "L1", f"{_EX}.exemption_type_formatted", "identity", "null_and_warn", "source", "never", None, "P1", 1),
)


#: Catalog transform → the executable codec (``zoho/codecs.py`` + the shared
#: ``CODECS``) that implements it. ``None`` = no codec needed (a pass-through, or
#: work done by an adapter hook — ``resolve_component_by_external`` is
#: ``zoho/hooks.py::project_group_members``, the only cross-entity transform: an
#: unsynced member raises ``TaxGroupError`` and the record retries, never links
#: silently — H9 / AP19).
TRANSFORM_CODECS: dict[str, str | None] = {
    "identity": None,
    "trim": "str",
    "lower": "lower_str",
    "trim|empty_to_null": "str",
    "lower|trim": "lower_str",
    "lower|empty_to_null": "lower_str",
    "empty_to_null": "str",
    "bool": "bool",
    "int": "int",
    "decimal_rate": "decimal_rate",
    "map_tax_type": "tax_type",
    "canonical_specific_type": "specific_type",
    "zoho_date": "zoho_date",
    "zoho_datetime": "zoho_datetime",
    "resolve_component_by_external": None,
}

__all__ = ["TAX_V1_MAPPINGS", "TRANSFORM_CODECS", "FieldCatalogEntry"]
