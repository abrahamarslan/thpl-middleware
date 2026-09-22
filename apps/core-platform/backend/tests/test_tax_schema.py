"""The ``tax`` schema: column coverage, catalog honesty, codecs, and the DB's own guarantees.

Three layers:
  * hermetic — the redesign paste's column ledger, the field catalog vs the
    executable ``FieldSpec`` maps, the codecs, the outbound payload;
  * integration (``db`` fixture, skips when the scratch DB is absent) — CHECK
    constraints, the ``NULLS NOT DISTINCT`` default, and the composite tenant FKs.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.db import Base
from app.database.tenancy import tenant_scope
from app.modules.organizations.model import Organization
from app.modules.sync.models import SyncRecord
from app.modules.sync.translation import CODECS, PayloadShape, TranslationError
from app.modules.taxes import mappings
from app.modules.taxes.component import TaxComponent, TaxGroupMember
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.preference import OrgDefaultTaxPreference
from app.modules.taxes.reference import GstTreatmentType
from app.modules.taxes.zoho import fields as zoho_fields
from app.modules.taxes.zoho.translator import EXEMPTION_TRANSLATOR, TAX_GROUP_TRANSLATOR, TAX_TRANSLATOR
from app.modules.tenants.model import Tenant

# ── the paste's column ledger ────────────────────────────────────────────────
#
# Every column of the seven-file redesign, by table. ``RENAMED`` is the only
# place a column changed name: the repo's mixins spell the audit / deactivation
# columns differently and docs/tenancy/README.md §2 says to use ours.

RENAMED = {
    "created_by_id": "created_by",
    "updated_by_id": "updated_by",
    "deleted_by_id": "deleted_by",
    "deactivated_by_id": "deactivated_by",
    "deactivated_reason": "deactivation_reason",
}

_BASE = ["id", "uuid", "created_at", "updated_at", "created_by_id", "updated_by_id", "created_by_name",
         "deleted_at", "deleted_by_id", "deleted_reason", "app_version", "app_metadata"]

PASTE_COLUMNS: dict[type, list[str]] = {
    TaxComponent: [*_BASE, "tenant_id", "tax_name", "tax_display_name", "tax_percentage", "tax_type",
                   "tax_specific_type", "tax_authority_id", "tax_authority_name", "output_tax_account_name",
                   "tax_account_id", "tds_payable_account_id", "is_state_cess", "is_inactive", "is_default_tax",
                   "is_editable", "is_non_advol_tax", "tax_specification", "diff_rate_reason", "start_date",
                   "end_date", "status", "description", "reference_id", "tax_name_formatted",
                   "source_default_tax_type_code", "source_new_tax_type", "deactivated_reason",
                   "deactivation_date", "deactivated_by_id", "content_hash"],
    TaxGroupMember: [*_BASE, "tenant_id", "tax_group_id", "member_tax_id", "position"],
    TaxExemption: [*_BASE, "tenant_id", "organization_id", "tax_exemption_code", "description", "type",
                   "type_formatted", "exemption_name", "exemption_type", "exemption_type_formatted",
                   "content_hash"],
    OrganizationTaxComponent: [*_BASE, "tenant_id", "organization_id", "tax_component_id", "is_active"],
    OrgDefaultTaxPreference: [*_BASE, "tenant_id", "organization_id", "tax_specification", "default_tax_id"],
    GstTreatmentType: [*_BASE, "owner_type", "owner_id", "code", "value", "label", "value_formatted",
                       "description", "category", "allowed_for_sales", "allowed_for_purchase", "content_hash"],
}

#: What this repo's doctrine adds on top of the paste, and why (asserted, so the
#: extras are a decision on record and not an accident).
DOCUMENTED_EXTRAS = {
    TaxComponent: {
        # docs/zoho-docs-md/taxes.md attributes the paste's schema does not carry —
        # kept so a tenant in that edition does not silently lose them.
        "tax_factor", "is_value_added", "country", "country_code", "purchase_tax_account_id",
        "purchase_tax_account_name", "purchase_tax_expense_account_id",
        # TenantEntityMixin bundle (docs/tenancy/README.md §3)
        "organization_id", "is_verified", "row_version", "updated_by_name",
    },
}


@pytest.mark.parametrize("model", list(PASTE_COLUMNS), ids=lambda m: m.__tablename__)
def test_every_paste_column_exists(model):
    have = set(model.__table__.c.keys())
    missing = [c for c in PASTE_COLUMNS[model] if RENAMED.get(c, c) not in have]
    assert missing == [], f"{model.__tablename__} lost paste columns: {missing}"


def test_the_extras_on_the_component_are_exactly_the_documented_ones():
    have = set(TaxComponent.__table__.c.keys())
    paste = {RENAMED.get(c, c) for c in PASTE_COLUMNS[TaxComponent]}
    assert have - paste == DOCUMENTED_EXTRAS[TaxComponent]


def test_all_six_tables_live_in_the_tax_schema_and_no_table_carries_a_source_id():
    tables = {t.name: t for t in Base.metadata.tables.values() if t.schema == "tax"}
    assert set(tables) == {"tax_components", "tax_group_members", "tax_exemptions",
                           "organization_tax_components", "org_default_tax_preferences",
                           "gst_treatment_types"}
    for table in tables.values():
        assert not {"zoho_id", "external_id", "zoho_raw"} & set(table.c.keys()), table.fullname


def test_tax_rows_pass_the_tenancy_classes():
    """Everything but the global vocabulary carries the tenant columns."""
    for model in (TaxComponent, TaxGroupMember, TaxExemption, OrganizationTaxComponent, OrgDefaultTaxPreference):
        assert {"tenant_id", "organization_id", "app_version", "app_metadata"} <= set(model.__table__.c.keys())
    assert "tenant_id" not in GstTreatmentType.__table__.c
    assert OrganizationTaxComponent.__table__.c.organization_id.nullable is False


# ── the catalog is the lineage record, and it must not rot ───────────────────

_TABLES = {f"tax.{t.name}": t for t in Base.metadata.tables.values() if t.schema == "tax"}
_TABLES["sync.sync_records"] = SyncRecord.__table__
_FIELD_MAPS = {"tax": zoho_fields.TAX_FIELDS, "tax_group": zoho_fields.TAX_GROUP_FIELDS,
               "tax_exemption": zoho_fields.EXEMPTION_FIELDS}


def _split(target: str) -> tuple[str, str | None]:
    for table in _TABLES:
        if target == table:
            return table, None
        if target.startswith(f"{table}."):
            return table, target[len(table) + 1:]
    raise AssertionError(f"catalog target {target!r} names no known table")


def test_catalog_source_paths_are_unique():
    paths = [e.source_path for e in mappings.TAX_V1_MAPPINGS]
    assert len(paths) == len(set(paths))


def test_every_catalog_target_is_a_real_column():
    for entry in mappings.TAX_V1_MAPPINGS:
        if entry.target is None:
            assert entry.layer in ("snapshot", "drop"), entry.source_path
            continue
        table, column = _split(entry.target)
        if column is not None:
            assert column in _TABLES[table].c, f"{entry.source_path} → {entry.target}"


def test_class_a_identity_lands_on_the_crosswalk_never_on_tax_tables():
    identity = [e for e in mappings.TAX_V1_MAPPINGS if e.primary_class == "A"]
    assert identity and all(e.layer == "L3" and e.target.startswith("sync.sync_records.") for e in identity)


def test_every_catalog_transform_is_known_and_its_codec_registered():
    for entry in mappings.TAX_V1_MAPPINGS:
        if entry.transform is None:
            continue
        assert entry.transform in mappings.TRANSFORM_CODECS, f"{entry.source_path}: {entry.transform}"
        codec = mappings.TRANSFORM_CODECS[entry.transform]
        assert codec is None or codec in CODECS, f"{entry.transform} → unregistered codec {codec}"


def _executable(entry) -> bool:
    prefix, _, rest = entry.source_path.partition(".")
    return (prefix in _FIELD_MAPS and "[]" not in entry.source_path and entry.layer in ("L1", "L2")
            and entry.target is not None and _split(entry.target)[0] in ("tax.tax_components", "tax.tax_exemptions"))


def test_every_executable_catalog_row_has_a_matching_field_spec():
    for entry in filter(_executable, mappings.TAX_V1_MAPPINGS):
        prefix, _, external = entry.source_path.partition(".")
        _, column = _split(entry.target)
        assert any(s.external == external and s.local == column for s in _FIELD_MAPS[prefix]), (
            f"{entry.source_path} → {entry.target} has no FieldSpec")


def test_every_field_spec_is_in_the_catalog():
    """Nothing runs undocumented: a FieldSpec with no catalog row is lineage nobody wrote down."""
    known = {(e.source_path.partition(".")[0], e.source_path.partition(".")[2]) for e in mappings.TAX_V1_MAPPINGS}
    for prefix, specs in _FIELD_MAPS.items():
        for spec in specs:
            assert (prefix, spec.external) in known, f"{prefix}.{spec.external} is executed but not catalogued"


def test_p2_columns_are_classified_p2():
    p2 = {e.target for e in mappings.TAX_V1_MAPPINGS if e.sensitivity == "P2"}
    assert p2 == {"tax.tax_exemptions.tax_exemption_code", "tax.tax_exemptions.exemption_name"}


# ── codecs ───────────────────────────────────────────────────────────────────

def test_tax_type_codec_maps_the_three_shapes_and_refuses_the_rest():
    decode = CODECS["tax_type"].decode
    assert [decode(v) for v in ("tax", " Compound_Tax ", "TAX_GROUP")] == ["tax", "compound_tax", "tax_group"]
    assert decode("") is None
    for bad in ("vat", 0, 2, True):
        with pytest.raises(ValueError):
            decode(bad)                 # the legacy 0/2 has no verified mapping — never guessed


def test_specific_type_codec_drops_the_generic_sentinel():
    decode = CODECS["specific_type"].decode
    assert (decode("CGST"), decode(" igst "), decode("tax"), decode(""), decode("nil")) == \
        ("cgst", "igst", None, None, "nil")


def test_tax_specification_codec_is_inter_or_intra():
    decode = CODECS["tax_specification"].decode
    assert (decode("Inter"), decode("intra"), decode(" ")) == ("inter", "intra", None)
    with pytest.raises(ValueError):
        decode("interstate")


def test_decimal_rate_codec_rejects_what_numeric_7_4_cannot_hold():
    decode = CODECS["decimal_rate"].decode
    assert decode("18") == Decimal("18") and decode(0) == 0 and decode("999.9999") == Decimal("999.9999")
    for bad in (-0.01, 1000, "NaN"):
        with pytest.raises(Exception):  # noqa: B017, PT011 — ValueError or InvalidOperation, both refusals
            decode(bad)


# ── translation ──────────────────────────────────────────────────────────────

DETAIL = {
    "tax_id": "982000000566009", "tax_display_name": "GST 18%", "tax_name": "GST18", "tax_percentage": 18,
    "tax_type": "tax", "tax_specific_type": "tax", "tax_authority_id": "460000000066001",
    "tax_authority_name": "CBIC", "output_tax_account_name": "Output GST", "tax_account_id": "1",
    "tds_payable_account_id": "2", "is_inactive": False, "is_default_tax": True, "is_editable": True,
    "tax_specification": "Intra", "diff_rate_reason": "", "start_date": "2017-07-01", "end_date": "",
    "status": "", "description": "Standard rate", "reference_id": "", "tax_name_formatted": "GST18 (18%)",
    "is_state_cess": False, "tax_factor": "rate", "is_value_added": True, "country": "India",
    "country_code": "IN", "purchase_tax_account_id": "3", "purchase_tax_account_name": "Input GST",
    "purchase_tax_expense_account_id": 982000000000392,
}


def test_a_detail_payload_decodes_into_every_column_it_names():
    decoded = TAX_TRANSLATOR.decode(DETAIL, shape=PayloadShape.DETAIL)
    v = decoded.values
    assert decoded.warnings == []
    assert v["tax_specific_type"] is None                    # the generic sentinel
    assert v["end_date"] is None and v["start_date"].isoformat() == "2017-07-01"   # "" → NULL, AP7
    assert v["reference_id"] is None and v["diff_rate_reason"] is None             # empty_to_null
    assert v["status"] == "active"                            # empty status → the NOT NULL default
    assert v["tax_specification"] == "intra" and v["tax_percentage"] == Decimal("18")
    assert v["purchase_tax_expense_account_id"] == 982000000000392
    assert "tax_id" not in v                                  # identity is the crosswalk's
    assert set(v) == {s.local for s in zoho_fields.TAX_FIELDS}


def test_a_thin_index_row_never_decodes_to_nulls():
    v = TAX_TRANSLATOR.decode({"tax_id": "1", "tax_name": "X", "tax_percentage": 5, "tax_type": "tax"},
                              shape=PayloadShape.INDEX).values
    assert set(v) == {"tax_name", "tax_percentage", "tax_type"}


def test_a_refused_value_is_a_warning_not_a_lost_record():
    decoded = TAX_TRANSLATOR.decode({"tax_name": "X", "tax_percentage": -3, "tax_type": 2,
                                     "tax_specification": "weird"})
    assert decoded.values == {"tax_name": "X"}
    assert len(decoded.warnings) == 3


def test_group_translator_turns_taxes_array_into_positioned_members():
    payload = {"tax_group_id": "9", "tax_group_name": "GST18", "tax_group_percentage": 18,
               "taxes": [{"tax_id": "11", "tax_name": "CGST9"}, {"tax_id": 12}, {"tax_name": "no id"}]}
    decoded = TAX_GROUP_TRANSLATOR.decode(payload)
    assert decoded.values == {"tax_name": "GST18", "tax_percentage": Decimal("18")}
    assert decoded.children["members"] == [{"tax_id": "11", "position": 0}, {"tax_id": "12", "position": 1}]
    assert "members" not in TAX_GROUP_TRANSLATOR.decode({"tax_group_name": "x"}).children   # says nothing


def test_exemption_translator_covers_the_paste_leaves():
    decoded = EXEMPTION_TRANSLATOR.decode({
        "tax_exemption_id": "1", "tax_exemption_code": " BILL OF SUPPLY ", "description": "",
        "type": "Item", "type_formatted": "Item", "exemption_name": "", "exemption_type": "Exempt",
        "exemption_type_formatted": "Exempt"})
    assert decoded.values == {
        "tax_exemption_code": "BILL OF SUPPLY", "description": None, "type": "item", "type_formatted": "Item",
        "exemption_name": None, "exemption_type": "exempt", "exemption_type_formatted": "Exempt"}


def test_outbound_never_sends_an_unverified_or_read_only_attribute():
    component = TaxComponent(tax_name="GST5", tax_percentage=Decimal("5"), tax_type="tax", tax_specific_type="igst",
                             status="active", tax_display_name="x", is_default_tax=True, is_inactive=False)
    payload = TAX_TRANSLATOR.encode(component)
    assert payload == {"tax_name": "GST5", "tax_percentage": 5, "tax_type": "tax", "tax_specific_type": "igst"}


def test_create_without_the_required_arguments_is_refused_before_a_call_is_spent():
    from app.modules.taxes.service import to_zoho_payload

    with pytest.raises(TranslationError, match="tax_name"):
        to_zoho_payload(TaxComponent(tax_type="tax"), create=True)


def test_a_group_is_never_pushed_through_the_taxes_endpoint():
    from app.common.exception.errors import AppError
    from app.modules.taxes.service import to_zoho_payload

    with pytest.raises(AppError, match="taxgroups"):
        to_zoho_payload(TaxComponent(tax_name="G", tax_percentage=Decimal(1), tax_type="tax_group"))


# ── database guarantees ──────────────────────────────────────────────────────

async def _world(db, code="TAXW"):
    tenant = Tenant(tenant_code=code, name=f"{code} Ltd", primary_contact_email=f"ops@{code.lower()}.example",
                    status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code=f"{code}-HQ", legal_name=f"{code} HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    return tenant, org


def _component(tenant, name="GST18", **kw) -> TaxComponent:
    kw.setdefault("tax_type", "tax")
    return TaxComponent(tenant_id=tenant.id, tax_name=name, tax_percentage=Decimal("18"), **kw)


async def _rejects(db, row, constraint: str):
    db.add(row)
    with pytest.raises(IntegrityError, match=constraint):
        await db.flush()
    await db.rollback()


async def test_check_constraints_refuse_what_the_codecs_would_have_dropped(db):
    tenant, _ = await _world(db)
    await _rejects(db, _component(tenant, tax_type="vat"), "chk_tax_components_tax_type")
    tenant, _ = await _world(db, "TAXW2")
    await _rejects(db, _component(tenant, tax_type="tax_group", tax_specific_type="cgst"),
                   "chk_tax_components_group_no_specific_type")
    tenant, _ = await _world(db, "TAXW3")
    await _rejects(db, _component(tenant, tax_specification="both"), "chk_tax_components_tax_specification")
    tenant, _ = await _world(db, "TAXW4")
    row = _component(tenant)
    row.tax_percentage = Decimal("-1")
    await _rejects(db, row, "chk_tax_components_tax_percentage")


async def test_a_new_component_gets_a_time_ordered_uuid_and_the_defaults(db):
    tenant, _ = await _world(db)
    with tenant_scope(tenant.id):
        first, second = _component(tenant, "A"), _component(tenant, "B")
        db.add_all([first, second])
        await db.flush()
    assert first.uuid.version == 7 and second.uuid.version == 7
    assert first.uuid < second.uuid                       # uuidv7 sorts by creation time
    assert first.status == "active" and first.is_verified is False and first.row_version == 1
    assert first.organization_id is None                  # tenant-wide unless a context says otherwise


async def test_a_tenant_wide_default_is_still_unique_per_context(db):
    """NULLS NOT DISTINCT: a plain unique index would let two tenant-wide defaults coexist."""
    tenant, _ = await _world(db)
    with tenant_scope(tenant.id):
        igst, other = _component(tenant, "IGST18"), _component(tenant, "IGST12")
        db.add_all([igst, other])
        await db.flush()
        db.add(OrgDefaultTaxPreference(tenant_id=tenant.id, organization_id=None,
                                       tax_specification="inter", default_tax_id=igst.id))
        await db.flush()
        db.add(OrgDefaultTaxPreference(tenant_id=tenant.id, organization_id=None,
                                       tax_specification="intra", default_tax_id=other.id))
        await db.flush()                                   # a different context is fine
        db.add(OrgDefaultTaxPreference(tenant_id=tenant.id, organization_id=None,
                                       tax_specification="inter", default_tax_id=other.id))
        with pytest.raises(IntegrityError, match="uq_org_default_tax_preferences_org_spec"):
            await db.flush()
        await db.rollback()


async def test_a_membership_can_never_pair_components_of_two_tenants(db):
    acme, _ = await _world(db, "ACMEX")
    globex, _ = await _world(db, "GLOBEX")
    with tenant_scope(acme.id):
        group = _component(acme, "GST18", )
        group.tax_type = "tax_group"
        db.add(group)
        await db.flush()
    with tenant_scope(globex.id):
        foreign = _component(globex, "CGST9")
        db.add(foreign)
        await db.flush()
    with tenant_scope(acme.id):
        db.add(TaxGroupMember(tenant_id=acme.id, tax_group_id=group.id, member_tax_id=foreign.id, position=0))
        with pytest.raises(IntegrityError, match="fk_tax_group_members_member"):
            await db.flush()
        await db.rollback()


async def test_a_group_cannot_contain_itself_and_a_member_is_listed_once(db):
    tenant, _ = await _world(db)
    with tenant_scope(tenant.id):
        group, leaf = _component(tenant, "G"), _component(tenant, "L")
        group.tax_type = "tax_group"
        db.add_all([group, leaf])
        await db.flush()
        db.add(TaxGroupMember(tenant_id=tenant.id, tax_group_id=group.id, member_tax_id=group.id))
        with pytest.raises(IntegrityError, match="chk_tax_group_members_not_self"):
            await db.flush()
        await db.rollback()

    tenant, _ = await _world(db, "TAXW9")
    with tenant_scope(tenant.id):
        group, leaf = _component(tenant, "G"), _component(tenant, "L")
        group.tax_type = "tax_group"
        db.add_all([group, leaf])
        await db.flush()
        db.add(TaxGroupMember(tenant_id=tenant.id, tax_group_id=group.id, member_tax_id=leaf.id))
        await db.flush()
        db.add(TaxGroupMember(tenant_id=tenant.id, tax_group_id=group.id, member_tax_id=leaf.id))
        with pytest.raises(IntegrityError, match="uq_tax_group_members_group_member"):
            await db.flush()
        await db.rollback()


async def test_a_grant_needs_a_real_organization_of_the_same_tenant(db):
    acme, acme_org = await _world(db, "ACMEY")
    globex, _ = await _world(db, "GLOBEY")
    with tenant_scope(globex.id):
        leaf = _component(globex, "L")
        db.add(leaf)
        await db.flush()
    db.add(OrganizationTaxComponent(tenant_id=globex.id, organization_id=acme_org.id, tax_component_id=leaf.id))
    with pytest.raises(IntegrityError, match="fk_organization_tax_components_tenant_org"):
        await db.flush()
    await db.rollback()


async def test_the_treatment_vocabulary_is_global_unique_on_value_and_code(db):
    db.add(GstTreatmentType(code=1, value="business_gst", category="business", allowed_for_sales=True))
    await db.flush()
    db.add(GstTreatmentType(code=2, value="business_gst"))
    with pytest.raises(IntegrityError, match="uq_gst_treatment_types_value"):
        await db.flush()
    await db.rollback()

    db.add(GstTreatmentType(code=3, value="overseas", category="nonsense"))
    with pytest.raises(IntegrityError, match="chk_gst_treatment_types_category"):
        await db.flush()
    await db.rollback()

    db.add(GstTreatmentType(code=4, value="sez", owner_type="connection", owner_id=7))
    await db.flush()
    assert await db.scalar(select(GstTreatmentType.owner_id).where(GstTreatmentType.value == "sez")) == 7
    db.add(GstTreatmentType(code=5, value="x", owner_type="galaxy", owner_id=1))
    with pytest.raises(IntegrityError, match="chk_gst_treatment_types_owner_type"):
        await db.flush()
    await db.rollback()


async def test_exemptions_take_open_vocabularies_without_a_check(db):
    tenant, _ = await _world(db)
    with tenant_scope(tenant.id):
        db.add(TaxExemption(tenant_id=tenant.id, tax_exemption_code="BILL OF SUPPLY",
                            type="something-zoho-invents-next-year", exemption_type="???"))
        await db.flush()
