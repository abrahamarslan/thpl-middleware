"""The five Phase 5 masters, end to end, through the REAL platform.

Real: ZohoClient transport (URL building, envelope parsing, page_context
contract), governor on Redis, circuit breaker, engine switches, planner tick,
leased runs, apply gate, batched page apply, sync events, the CLI.
Fake: only the HTTP wire (Zoho's *documented* responses, docs/zoho-docs-md/)
and the OAuth token.

Run with ``-s`` to see the CLI tables:
    .venv/bin/python -m pytest tests/zoho_core/test_masters_e2e.py -s
"""

import copy
import re

import httpx
import pytest
from sqlalchemy import func, select

from app.modules.zoho.control import planner
from app.modules.zoho.control.models import RunStatus, ZohoSyncEvent, ZohoSyncRun
from app.modules.zoho.control.switches import zoho_switches
from app.modules.zoho.core import transport as transport_module
from app.modules.zoho.core.governor import zoho_governor
from app.modules.organizations.model import Organization
from app.modules.zoho.sync.registry import sync_registry

# ── Zoho's documented payloads ──────────────────────────────────────────────

ORG_DETAIL = {
    "organization_id": "10229182", "name": "Zillium Inc", "is_default_org": False, "account_created_date": "2012-02-15",
    "time_zone": "PST", "language_code": "en", "date_format": "dd MMM yyyy", "field_separator": " ",
    "fiscal_year_start_month": 0, "tax_group_enabled": True, "contact_name": "John Smith",
    "industry_type": "Services", "currency_code": "INR",
    "address": {"street_address1": "14 Main St", "city": "Chennai", "country": "India", "zip": "600001"},
}
ORG_LIST_ROW = {k: ORG_DETAIL[k] for k in ("organization_id", "name", "is_default_org", "currency_code")}

CURRENCIES = [
    {"currency_id": "982000000004012", "currency_code": "AUD", "currency_name": "AUD- Australian Dollar",
     "currency_symbol": "$", "price_precision": 2, "currency_format": "1,234,567.89", "is_base_currency": False,
     "exchange_rate": 54.12, "effective_date": "2013-09-04"},
    {"currency_id": "982000000004000", "currency_code": "INR", "currency_name": "INR- Indian Rupee",
     "currency_symbol": "₹", "price_precision": 2, "currency_format": "1,23,45,678.90", "is_base_currency": True},
]
TAXES = [
    {"tax_id": "982000000566009", "tax_name": "IGST18", "tax_percentage": 18, "tax_type": "tax",
     "tax_specific_type": "igst", "is_value_added": False, "is_default_tax": True, "is_editable": True,
     "tax_account_id": "982000000567001"},          # → accounting.account_assignments (output_tax)
    {"tax_id": "982000000566010", "tax_name": "CGST9", "tax_percentage": 9, "tax_type": "tax",
     "tax_specific_type": "cgst", "is_value_added": False, "is_default_tax": False, "is_editable": True},
]
TAX_EXEMPTIONS = [
    {"tax_exemption_id": "982000000566101", "tax_exemption_code": "BILL OF SUPPLY",
     "description": "Composition dealer", "type": "item", "type_formatted": "Item",
     "exemption_name": "", "exemption_type": "exempt", "exemption_type_formatted": "Exempt"},
    {"tax_exemption_id": "982000000566102", "tax_exemption_code": "SEZ SUPPLY",
     "description": "Supply to an SEZ unit", "type": "customer", "type_formatted": "Customer",
     "exemption_name": "SEZ", "exemption_type": "exempt", "exemption_type_formatted": "Exempt"},
]
LOCATIONS = [{
    "type": "general", "email": "willsmith@bowmanfurniture.com", "phone": "+1-925-921-9201",
    "address": {"city": "New York City", "state": "New York", "country": "U.S.A", "attention": "string",
                "state_code": "NY", "street_address1": "No:234,90 Church Street", "street_address2": "McMillan Avenue"},
    "location_id": "460000000038080", "location_name": "Head Office", "tax_settings_id": "460000000038080",
    "status": "active", "is_primary": True,
    "associated_series_ids": ["982000000870911", "982000000870915"], "auto_number_generation_id": "982000000870911",
    "is_all_users_selected": False, "associated_users": [{"user_id": "460000000036868", "user_name": "John Doe"}],
}]
# Categories, shaped like the LIVE /categories response (captured 2026-09-25):
# the list is hierarchical, top-level rows name parent "-1", and — unless the
# caller passes include_root_category=false — Zoho prepends a synthetic ROOT row
# (id "-1", blank timestamps) that nobody created.
CAT_ROOT = {"category_id": "-1", "name": "ROOT", "url": "rootcategory", "parent_category_id": "-1",
            "visibility": True, "show_in_menu": True, "sibling_order": 1, "depth": 0,
            "created_time": "", "last_modified_time": "", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": False}
CAT_SKIN = {"category_id": "954919000013143071", "name": "Skin Care", "url": "skin_care",
            "parent_category_id": "-1", "visibility": True, "show_in_menu": True, "sibling_order": 2,
            "depth": 0, "created_time": "2024-10-22T16:53:19+0530",
            "last_modified_time": "2026-09-19T10:07:53+0530", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": True}
CAT_SOAP = {"category_id": "954919000061486002", "name": "Bathing Soap & Bodywash", "url": "bathing_soap_bodywash",
            "parent_category_id": "954919000013143071", "visibility": True, "show_in_menu": True,
            "sibling_order": 1, "depth": 1, "created_time": "2026-08-04T21:47:33+0530",
            "last_modified_time": "2026-09-07T16:54:23+0530", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": True}
CAT_HAIR = {"category_id": "954919000013118048", "name": "Hair Care", "url": "hair_care",
            "parent_category_id": "-1", "visibility": True, "show_in_menu": True, "sibling_order": 1,
            "depth": 0, "created_time": "2024-10-22T16:23:25+0530",
            "last_modified_time": "2026-09-19T10:07:28+0530", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": True}
#: What only the DETAIL document adds (SEO block, GST defaults) — live shape. The tax ids are the
#: ones this wire's own /settings/taxes serves, so the `taxes` module (run first) has synced them.
CAT_DETAIL_EXTRA = {
    "seo_title": "", "seo_keyword": "", "seo_description": "", "parent_category_name": "",
    "category_tax_preferences": [
        {"tax_specification": "inter", "tax_specific_type": "igst", "tax_id": "982000000566009",
         "tax_name": "IGST18", "tax_percentage": 18.0, "new_tax_type": "tax"},
        {"tax_specification": "intra", "tax_specific_type": "tax", "tax_id": "982000000566010",
         "tax_name": "CGST9", "tax_percentage": 9.0, "new_tax_type": "tax"},
    ],
    "ancestors": [], "children": [],
}
CATEGORIES = [CAT_HAIR, CAT_SKIN, CAT_SOAP]        # hierarchical order: parent before child

# Brands, shaped like the LIVE (undocumented) /brands response (captured 2026-09-28):
# a flat, unpaginated, two-field list; the detail document adds nothing.
BRANDS = [
    {"brand_id": "954919000013118046", "name": "DABUR"},
    {"brand_id": "954919000013143235", "name": "HIMALAYA"},
]

# Chart of accounts, shaped like the DOCUMENTED /chartofaccounts list (docs/zoho-docs-md/chart-of-accounts.md);
# the child is listed BEFORE its parent (the same-page parent the hook must still link), and Zoho's blank
# account_code is a real case. The detail document adds currency_id + description.
CHART = [
    {"account_id": "982000000567001", "account_name": "Output IGST", "account_code": "2101",
     "account_type": "other_current_liability", "is_user_created": False, "is_system_account": True,
     "is_active": True, "can_show_in_ze": False, "current_balance": 1520.5,
     "parent_account_id": "982000000567000", "created_time": "2013-01-17T15:27:23+0530",
     "last_modified_time": "2013-01-17T15:27:23+0530"},
    {"account_id": "982000000567000", "account_name": "Duties and Taxes", "account_code": "2100",
     "account_type": "other_current_liability", "is_user_created": True, "is_system_account": False,
     "is_active": True, "can_show_in_ze": False, "current_balance": 0, "parent_account_id": "",
     "created_time": "2013-01-17T15:27:23+0530", "last_modified_time": "2013-01-17T15:27:23+0530"},
    {"account_id": "982000000567010", "account_name": "Sales", "account_code": "",
     "account_type": "income", "is_user_created": False, "is_system_account": True, "is_active": True,
     "can_show_in_ze": False, "current_balance": 99, "parent_account_id": "",
     "created_time": "2013-01-17T15:27:23+0530", "last_modified_time": "2013-01-17T15:27:23+0530"},
]
CHART_DETAIL_EXTRA = {"currency_id": "982000000004000", "currency_code": "INR",
                      "description": "Synced from Zoho", "closing_balance": 0}

# Price lists (Zoho's API: pricebooks), shaped like the LIVE /pricebooks responses (THPL probe 2026-10-08; names anonymised). Zoho documents
# no "get a pricebook"; GET /pricebooks/{id} works live and is the only source of the items: its document drops
# last_modified_time and adds is_default, pricebook_items and products. A volume item has NO pricebook_item_id —
# its brackets do (one id per bracket); a percentage book sends currency_id "" (the base currency).
PRICEBOOKS = [
    {"pricebook_id": "982000000870001", "name": "Retail Partner A", "description": "", "currency_id": "982000000004000",
     "currency_code": "INR", "decimal_place": 0, "is_increase": False, "percentage": "", "pricebook_rate": "",
     "pricebook_type": "per_item", "pricing_scheme": "unit", "rounding_type": "no_rounding",
     "sales_or_purchase_type": "sales", "status": "active", "last_modified_time": "2025-05-15T12:23:11+0530"},
    {"pricebook_id": "982000000870002", "name": "Volume Demo", "description": "", "currency_id": "982000000004000",
     "currency_code": "INR", "decimal_place": 0, "is_increase": False, "percentage": "", "pricebook_rate": "",
     "pricebook_type": "per_item", "pricing_scheme": "volume", "rounding_type": "no_rounding",
     "sales_or_purchase_type": "sales", "status": "active", "last_modified_time": "2026-05-09T13:10:22+0530"},
    {"pricebook_id": "982000000870003", "name": "Clinic Markup", "description": "", "currency_id": "",
     "currency_code": "", "decimal_place": 0, "is_increase": True, "percentage": 35.71, "pricebook_rate": 35.71,
     "pricebook_type": "fixed_percentage", "pricing_scheme": "", "rounding_type": "round_to_dollar",
     "sales_or_purchase_type": "sales", "status": "inactive", "last_modified_time": "2024-05-04T23:48:16+0530"},
]
PRICEBOOK_ITEMS = {
    "982000000870001": [
        {"pricebook_item_id": "982000000870101", "item_id": "982000000880001", "name": "Neem Face Scrub 50GM",
         "can_be_sold": True, "can_be_purchased": True, "pricebook_discount": "", "pricebook_rate": 64.41},
        {"pricebook_item_id": "982000000870102", "item_id": "982000000880002", "name": "Aloe Gel 100GM",
         "can_be_sold": True, "can_be_purchased": False, "pricebook_discount": "", "pricebook_rate": 120},
    ],
    "982000000870002": [
        {"item_id": "982000000880001", "name": "Neem Face Scrub 50GM", "can_be_sold": True, "can_be_purchased": True,
         "price_brackets": [
             {"pricebook_item_id": "982000000870201", "start_quantity": 10.0, "end_quantity": 19.0,
              "pricebook_discount": "", "pricebook_rate": 19.0},
             {"pricebook_item_id": "982000000870202", "start_quantity": 20.0, "end_quantity": 49.0,
              "pricebook_discount": "", "pricebook_rate": 18.0},
             {"pricebook_item_id": "982000000870203", "start_quantity": 50.0, "end_quantity": "",
              "pricebook_discount": "", "pricebook_rate": 15.84},
         ]},
    ],
    "982000000870003": [],
}

# Contacts (→ parties), shaped like the LIVE /contacts documents (THPL probe 2026-10-08; anonymised). The list row is
# thin (no persons / addresses / tax_info_list / pricebook_id); every contact carries billing AND shipping objects with
# their own address ids even when empty; THPL records Zoho merges of duplicates in cf_merged_customer_ids.
_ADDR = {"attention": "Ramesh Patel", "address": "CQ92+9PC, Main Road", "street2": "", "city": "Ditwas",
         "state_code": "", "state": "Gujarat ", "zip": "389250", "country": "India", "county": "", "latitude": "",
         "longitude": "", "country_code": "IN", "phone": "+919000000001", "fax": ""}
_EMPTY_ADDR = {k: "" for k in _ADDR}
CONTACT_DETAILS = {
    "982000000990001": {
        "contact_id": "982000000990001", "contact_name": "Patel Medical Store", "company_name": "Patel Medical Store",
        "contact_type": "customer", "customer_sub_type": "business", "status": "active", "source": "api",
        "first_name": "Ramesh", "last_name": "Patel", "mobile": "+919000000001", "email": "", "language_code": "en",
        "currency_id": "982000000004000", "currency_code": "INR", "is_bcy_only_contact": True, "is_taxable": True,
        "payment_terms": 0, "payment_terms_label": "Due on Receipt", "payment_terms_id": "982000000990501",
        "pricebook_id": "982000000870002", "pricebook_name": "Volume Demo", "place_of_contact": "GJ",
        "gst_treatment": "business_gst", "contact_category": "business_gst", "gst_no": "24ABCDE1234F1Z5",
        "pan_no": "ABCDE1234F", "trader_name": "PATEL MEDICALS", "legal_name": "RAMESH PATEL",
        "tax_info_list": [{"tax_info_id": "982000000990601", "tax_registration_no": "24ABCDE1234F1Z5",
                           "place_of_supply": "GJ", "is_primary": True, "trader_name": "PATEL MEDICALS",
                           "legal_name": "RAMESH PATEL"}],
        "tax_id": "", "tax_exemption_id": "", "account_id": "", "owner_id": "", "udyam_reg_no": "",
        "primary_contact_id": "982000000990701",
        "contact_persons": [
            {"contact_person_id": "982000000990701", "first_name": "Ramesh", "last_name": "Patel",
             "mobile": "+919000000001", "is_primary_contact": True, "is_sms_enabled_for_cp": False,
             "communication_preference": {"is_email_enabled": True, "is_whatsapp_enabled": False}},
            {"contact_person_id": "982000000990702", "first_name": "Suresh", "last_name": "",
             "mobile": "+919000000002", "is_primary_contact": False,
             "communication_preference": {"is_email_enabled": True, "is_whatsapp_enabled": True}},
        ],
        "billing_address": {**_ADDR, "address_id": "982000000990801"},
        "shipping_address": {**_ADDR, "address_id": "982000000990802"},
        "addresses": [],
        "custom_fields": [{"field_id": "982000000991001", "api_name": "cf_risk_score", "label": "Credit Risk",
                           "data_type": "dropdown", "value": "Medium", "selected_option_id": "982000000991002",
                           "index": 1, "is_active": True}],
        "cf_risk_score": "Medium", "outstanding_receivable_amount": 120.0,
        "created_time": "2025-01-01T10:00:00+0530", "last_modified_time": "2026-07-08T09:49:49+0530",
    },
    "982000000990002": {
        "contact_id": "982000000990002", "contact_name": "Shreeji Traders", "company_name": "Shreeji Traders",
        "contact_type": "customer", "customer_sub_type": "business", "status": "active", "source": "csv",
        "first_name": "", "last_name": "", "mobile": "+919000000003", "email": "", "language_code": "",
        "currency_id": "982000000004000", "currency_code": "INR", "is_bcy_only_contact": True, "is_taxable": True,
        "payment_terms": -3, "payment_terms_label": "Due end of next month", "payment_terms_id": "",
        "pricebook_id": "", "place_of_contact": "GJ", "gst_treatment": "business_none",
        "contact_category": "business_none", "gst_no": "", "pan_no": "", "tax_info_list": [],
        "tax_id": "", "tax_exemption_id": "", "account_id": "", "owner_id": "", "primary_contact_id": "",
        "contact_persons": [],
        "billing_address": {**_EMPTY_ADDR, "address_id": "982000000990803", "city": "Kathlal", "state": "Gujarat"},
        "shipping_address": {**_EMPTY_ADDR, "address_id": "982000000990804", "phone": "+919000000003"},
        "addresses": [], "custom_fields": [], "cf_merged_customer_ids": "982000000990099",
        "created_time": "2025-02-01T10:00:00+0530", "last_modified_time": "2026-07-08T09:46:05+0530",
    },
    "982000000990003": {
        "contact_id": "982000000990003", "contact_name": "Gupta Distributors", "company_name": "",
        "contact_type": "vendor", "customer_sub_type": "business", "status": "inactive", "source": "user",
        "mobile": "", "email": "", "currency_id": "982000000004000", "payment_terms": 0,
        "payment_terms_label": "Due On Receipt", "payment_terms_id": "", "place_of_contact": "GJ",
        "gst_treatment": "business_registered_composition", "gst_no": "", "pan_no": "", "tax_info_list": [],
        "tds_tax_id": "", "tds_tax_name": "", "contact_persons": [], "primary_contact_id": "",
        "billing_address": {**_EMPTY_ADDR, "address_id": "982000000990805"},
        "shipping_address": {**_EMPTY_ADDR, "address_id": "982000000990806"},
        "addresses": [], "custom_fields": [],
        "created_time": "2025-03-01T10:00:00+0530", "last_modified_time": "2024-05-13T13:53:30+0530",
    },
}
_LIST_KEYS = ("contact_id", "contact_name", "company_name", "contact_type", "customer_sub_type", "status", "source",
              "mobile", "email", "currency_id", "payment_terms", "payment_terms_label", "payment_terms_id",
              "place_of_contact", "gst_treatment", "gst_no", "pan_no", "custom_fields", "cf_merged_customer_ids",
              "outstanding_receivable_amount", "created_time", "last_modified_time")
CONTACTS = [{k: d[k] for k in _LIST_KEYS if k in d} for d in CONTACT_DETAILS.values()]

USERS = [
    {"user_id": "982000000554041", "role_id": "982000000006005", "name": "Sujin Kumar",
     "email": "johndavid@zilliuminc.com", "user_role": "admin", "status": "active", "is_current_user": True,
     "photo_url": "https://contacts.zoho.com/file?ID=x&fs=thumb", "is_customer_segmented": False,
     "is_vendor_segmented": False, "user_type": "zoho"},
    {"user_id": "982000000554042", "role_id": "982000000006006", "name": "Asha Rao", "email": "asha@zilliuminc.com",
     "user_role": "staff", "status": "inactive", "is_current_user": False, "user_type": "zoho"},
]


class ZohoWire:
    """httpx handler answering like Zoho Books v3 (per the vendored docs)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.data = {"currencies": copy.deepcopy(CURRENCIES), "taxes": copy.deepcopy(TAXES),
                     "tax_exemptions": copy.deepcopy(TAX_EXEMPTIONS),
                     "locations": copy.deepcopy(LOCATIONS), "users": copy.deepcopy(USERS),
                     "categories": copy.deepcopy(CATEGORIES), "brands": copy.deepcopy(BRANDS),
                     "chartofaccounts": copy.deepcopy(CHART), "pricebooks": copy.deepcopy(PRICEBOOKS)}
        self.pricebook_items = copy.deepcopy(PRICEBOOK_ITEMS)
        self.data["contacts"] = copy.deepcopy(CONTACTS)
        self.contact_details = copy.deepcopy(CONTACT_DETAILS)
        self.contact_rate_limited: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["Authorization"] == "Zoho-oauthtoken test-token"
        assert request.url.params["organization_id"]
        path = request.url.path.removeprefix("/books/v3")
        paged = {"page_context": {"page": 1, "per_page": 200, "has_more_page": False}}
        if path == "/organizations":
            return self._ok({"organizations": [ORG_LIST_ROW]})
        if match := re.fullmatch(r"/organizations/(\d+)", path):
            assert match.group(1) == "10229182"
            return self._ok({"organization": ORG_DETAIL})
        if path == "/settings/currencies":                       # documented WITHOUT page_context
            return self._ok({"currencies": self.data["currencies"]})
        if path == "/settings/taxes":
            return self._ok({"taxes": self.data["taxes"], **paged})
        if match := re.fullmatch(r"/settings/taxes/(\d+)", path):    # index_then_detail
            detail = next((t for t in self.data["taxes"] if t["tax_id"] == match.group(1)), None)
            if detail is None:
                return httpx.Response(404, json={"code": 1001, "message": "Tax not found"})
            return self._ok({"tax": detail})
        if path == "/settings/taxexemptions":                    # documented WITHOUT page_context
            return self._ok({"tax_exemptions": self.data["tax_exemptions"]})
        if path == "/locations":                                 # documented WITHOUT page_context
            return self._ok({"locations": self.data["locations"]})
        if path == "/users":
            assert request.url.params["filter_by"] == "Status.All"
            return self._ok({"users": self.data["users"], **paged})
        if path == "/categories":
            return self._categories_list(request, paged)
        if path == "/brands":
            # live: per_page/page/last_modified_time are all silently ignored.
            return self._ok({"brands": self.data["brands"]})
        if path == "/chartofaccounts":
            assert "showbalance" not in request.url.params          # a balance is never part of the master
            return self._ok({"chartofaccounts": self.data["chartofaccounts"], **paged})
        if match := re.fullmatch(r"/chartofaccounts/(\d+)", path):    # index_then_detail
            detail = next((a for a in self.data["chartofaccounts"] if a["account_id"] == match.group(1)), None)
            if detail is None:
                return httpx.Response(404, json={"code": 1001, "message": "Account not found"})
            return self._ok({"chart_of_account": {**detail, **CHART_DETAIL_EXTRA}})
        if path == "/contacts":
            assert request.url.params["filter_by"] == "Status.All"          # inactive contacts too
            assert request.url.params["sort_column"] == "created_time"      # stable paging
            return self._ok({"contacts": self.data["contacts"], **paged})
        if match := re.fullmatch(r"/contacts/(\d+)", path):
            if match.group(1) in self.contact_rate_limited:
                return httpx.Response(429, headers={"Retry-After": "0"},
                                      json={"code": 44, "message": "Too many requests"})
            detail = self.contact_details.get(match.group(1))
            if detail is None:
                return httpx.Response(404, json={"code": 1002, "message": "Contact does not exist."})
            return self._ok({"contact": copy.deepcopy(detail)})
        if path == "/pricebooks":
            return self._ok({"pricebooks": self.data["pricebooks"], **paged})
        if match := re.fullmatch(r"/pricebooks/(\d+)", path):        # undocumented, live: index_then_detail
            book = next((b for b in self.data["pricebooks"] if b["pricebook_id"] == match.group(1)), None)
            if book is None:
                return httpx.Response(404, json={"code": 1001, "message": "Pricebook not found"})
            detail = {k: v for k, v in book.items() if k != "last_modified_time"}
            return self._ok({"pricebook": {**detail, "is_default": False, "products": [],
                                           "pricebook_items": copy.deepcopy(self.pricebook_items[book["pricebook_id"]])}})
        if match := re.fullmatch(r"/categories/(-?\d+)", path):      # index_then_detail
            rows = [CAT_ROOT, *self.data["categories"]]
            detail = next((c for c in rows if c["category_id"] == match.group(1)), None)
            if detail is None:
                return httpx.Response(404, json={"code": 1001, "message": "Category not found"})
            return self._ok({"category": {**detail, **CAT_DETAIL_EXTRA}})
        return httpx.Response(404, json={"code": 5, "message": f"Invalid URL {path}"})

    def _categories_list(self, request: httpx.Request, paged: dict) -> httpx.Response:
        """Live behaviour: ROOT unless include_root_category=false; a modified-since
        filter that only accepts the ``+0000`` spelling (``…Z`` is a 400)."""
        params = request.url.params
        rows = list(self.data["categories"])
        if params.get("include_root_category") != "false":
            rows = [CAT_ROOT, *rows]
        since = params.get("last_modified_time")
        if since is not None:
            if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", since):
                return httpx.Response(400, json={"code": 2, "message": "Invalid value passed for last_modified_time"})
            from app.modules.sync.translation import CODECS

            floor = CODECS["zoho_datetime"].decode(since)
            # Live: ROOT (blank time) is returned by every filtered call unless excluded.
            rows = [r for r in rows if not r["last_modified_time"]
                    or CODECS["zoho_datetime"].decode(r["last_modified_time"]) >= floor]
        return self._ok({"categories": rows, **paged})

    @staticmethod
    def _ok(body: dict) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "message": "success", **body})

    def calls_to(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path.endswith(path))


class StubTokens:
    async def get_token(self) -> str:
        return "test-token"

    async def invalidate(self, token: str | None = None) -> None:  # pragma: no cover
        pass


@pytest.fixture
async def wire(db, redis_available, monkeypatch):
    """Every ZohoClient the platform builds talks to the fake wire."""
    from app.core.conf import settings

    # The connection must name the organization the wire actually serves: the
    # engine attaches synced rows to the organization node whose `zoho_id` is
    # ZOHO_ORGANIZATION_ID (`zoho/control/tenancy.py`), and a canonical master
    # such as `currency.currencies` requires one. Point it at ORG_DETAIL.
    monkeypatch.setattr(settings, "ZOHO_ORGANIZATION_ID", ORG_DETAIL["organization_id"])
    wire = ZohoWire()

    # A subclass, not a factory function: modules imported lazily afterwards
    # evaluate annotations like ``ZohoClient | None`` (a function breaks `|`).
    class WiredClient(transport_module.ZohoClient):
        def __init__(self, **kwargs):
            super().__init__(http=httpx.AsyncClient(transport=httpx.MockTransport(wire)),
                             token_manager=StubTokens(), **kwargs)

    monkeypatch.setattr(transport_module, "ZohoClient", WiredClient)
    zoho_switches.invalidate()
    await zoho_governor.reset_day()
    yield wire
    await zoho_governor.reset_day()
    from app.database.db import engine

    await engine.dispose()          # the CLI/switches used the pooled engine on this test's loop


async def run_all(db) -> dict[str, dict]:
    """What the worker does for each enqueued lane — execute_leased_run.

    ``organizations`` goes first, always: it is the module that creates the
    organization node the Zoho connection points at (``ZOHO_ORGANIZATION_ID``),
    and the org-scoped masters — ``currency.currencies`` above all — cannot
    place a row until it exists. Registry order is import order, so relying on
    it made this test pass or fail depending on which test module ran before it.
    """
    from app.tasks.zoho_sync import execute_leased_run

    modules = sorted(sync_registry.all(), key=lambda d: d.name != "organizations")
    results = {}
    for defn in modules:
        client = transport_module.ZohoClient(default_module=defn.name)
        try:
            results[defn.name] = await execute_leased_run(
                db, client, module_name=defn.name, lane="scheduled", mode=None, trigger="planner")
        finally:
            await client.aclose()
    return results


async def test_the_planner_schedules_every_master_and_the_runs_mirror_them(db, wire, monkeypatch):
    from app.core.conf import settings

    monkeypatch.setattr(settings, "ZOHO_PLANNER_MAX_CONCURRENT_RUNS", 20)
    enqueued = []
    await planner.tick(db, enqueue=lambda module, lane, mode: enqueued.append((module, lane)))
    # `tax_groups` is registered DISABLED (Zoho documents no list endpoint), so
    # the planner schedules every master except that one.
    assert sorted(m for m, lane in enqueued if lane == "scheduled") == sorted(
        ("organizations", "currencies", "taxes", "tax_exemptions", "locations", "users", "categories", "brands",
         "chart_of_accounts", "price_lists", "parties")
    )
    # `categories` is the one INCREMENTAL master, so it alone also gets the weekly
    # full-reconcile lane — the only scan that can see a category Zoho deleted.
    assert [m for m, lane in enqueued if lane == "weekly_full"] == ["categories"]

    results = await run_all(db)
    assert {m: r["status"] for m, r in results.items()} == dict.fromkeys(results, RunStatus.SUCCEEDED)
    assert results["organizations"]["created"] == 1
    assert results["currencies"]["created"] == 2 and results["taxes"]["created"] == 2
    assert results["tax_exemptions"]["created"] == 2
    assert results["locations"]["created"] == 1 and results["users"]["created"] == 2
    assert results["categories"]["created"] == 3          # the synthetic ROOT is NOT one of them
    assert results["brands"]["created"] == 2
    assert results["chart_of_accounts"]["created"] == 3
    assert results["price_lists"]["created"] == 3
    assert results["parties"]["created"] == 3

    # organizations: 1 list + 1 detail. taxes: 1 list + 2 details, categories: 1 list + 3 details
    # (index_then_detail), price_lists: 1 list + 3 details (items live only in the detail), parties: 1 list + 3 details. currencies / tax_exemptions / locations / users / brands / chart_of_accounts
    # (list-only by default — a detail call per account is a request against Zoho's daily plan cap):
    # 1 list each.
    assert len(wire.requests) == 23 and wire.calls_to("/organizations/10229182") == 1
    assert wire.calls_to("/chartofaccounts/982000000567001") == 0
    assert wire.calls_to("/settings/taxes/982000000566009") == 1
    assert wire.calls_to("/categories/-1") == 0           # ROOT was never even listed
    assert wire.calls_to("/brands") == 1 and wire.calls_to("/brands/954919000013118046") == 0

    # the governor counted every call; the runs and events are recorded
    assert (await zoho_governor.snapshot())["used"] == 23
    # `run_all` executes every REGISTERED module, so `tax_groups` gets a run too
    # even though the planner never schedules it (direction=disabled).
    assert set(await db.scalars(select(ZohoSyncRun.module))) == {
        "organizations", "currencies", "taxes", "tax_groups", "tax_exemptions", "locations", "users",
        "categories", "brands", "chart_of_accounts", "price_lists", "parties",
    }
    assert await db.scalar(select(func.count()).select_from(ZohoSyncEvent)
                           .where(ZohoSyncEvent.event_type == "inserted")) == 24

    from app.modules.locations.model import ZohoLocation
    from app.modules.zoho_users.model import ZohoUser

    head_office = await db.scalar(select(ZohoLocation))
    assert head_office.address_state_code == "NY" and head_office.associated_users[0]["user_name"] == "John Doe"
    inactive = await db.scalar(select(ZohoUser).where(ZohoUser.zoho_status == "inactive"))
    assert inactive.name == "Asha Rao"                      # Status.All: inactive users are mirrored too
    assert inactive.status == "active"                      # OUR record status ≠ Zoho's (zoho_status)

    # Tenancy: everything the sync wrote belongs to the Zoho tenant and is
    # attached to the organization node the Zoho org became.
    from app.modules.organizations.model import Organization

    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    assert org.parent_id is None and org.org_type == "legal_entity" and org.org_code == "ZOHO-10229182"
    assert head_office.tenant_id == org.tenant_id and inactive.created_by_name == "system:zoho-sync"


async def test_a_second_pass_writes_nothing_and_a_zoho_change_lands(db, wire):
    await run_all(db)
    wire.data["taxes"][1]["tax_percentage"] = 6              # someone edits CGST in Zoho
    second = await run_all(db)

    # taxes is index_then_detail: each record is applied twice (the listed row,
    # then the detail document), so two taxes make four applies — the edited
    # CGST detail is the one update, the other three are unchanged.
    assert second["taxes"]["updated"] == 1 and second["taxes"]["unchanged"] == 3
    for module in ("currencies", "tax_exemptions", "locations", "users", "organizations", "categories", "brands",
                   "chart_of_accounts", "price_lists", "parties"):
        assert second[module]["created"] == second[module]["updated"] == 0, module

    # Scoped to the module: `organizations` is index-then-detail, so its own
    # first-pass detail write is an "updated" event too.
    changed = await db.scalar(select(ZohoSyncEvent).where(ZohoSyncEvent.event_type == "updated",
                                                          ZohoSyncEvent.module == "taxes"))
    assert changed.diff == {"tax_percentage": ["9.0000", "6"]}


async def test_the_cli_runs_the_same_pipeline(db, wire, capsys):
    from app.modules.zoho import cli

    assert await cli.cmd_sync(None, None) == 0
    assert await cli.cmd_status() == 0
    assert await cli.cmd_runs(10, None) == 0
    out = capsys.readouterr().out
    print(out)                                               # visible with -s
    for module in ("organizations", "currencies", "taxes", "tax_exemptions", "locations", "users", "categories",
                  "brands", "chart_of_accounts"):
        assert module in out
    assert "failed" not in out


async def test_the_read_endpoints_serve_locations_and_users(db, wire):
    from types import SimpleNamespace

    from app.database.db import get_db
    from app.main import app
    from app.modules.users.deps import get_current_user

    await run_all(db)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, email="u@x.com")
    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
            locations = (await api.get("/api/zoho/locations", params={"status": "active"})).json()["data"]
            assert [loc["location_name"] for loc in locations] == ["Head Office"]
            assert locations[0]["is_primary"] is True
            by_email = (await api.get("/api/zoho/users/JOHNDAVID@zilliuminc.com")).json()["data"]
            assert by_email["zoho_id"] == "982000000554041"
            inactive = (await api.get("/api/zoho/users", params={"status": "inactive"})).json()["data"]
            assert [u["name"] for u in inactive] == ["Asha Rao"]
            assert (await api.get("/api/zoho/locations/404404")).status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_categories_end_to_end_through_the_real_transport(db, wire, monkeypatch):
    """The live-verified behaviours of the categories adapter, on the real pipeline.

    Each assertion here is something the first cut of the adapter got wrong on
    the live API and the unit-level FakeZohoClient could not show: the synthetic
    ROOT row, the modified-since spelling, the hierarchy landing through the
    crosswalk, and a Zoho-side delete reaching the tree.
    """
    from app.core.conf import settings
    from app.modules.categories.model import Category
    from app.modules.sync.models import SyncRecord
    from app.tasks.zoho_sync import execute_leased_run

    await run_all(db)

    # 1. ROOT is asked NOT to be listed, and did not become a category.
    first_list = next(r for r in wire.requests if r.url.path.endswith("/categories"))
    assert first_list.url.params["include_root_category"] == "false"
    rows = {c.zoho_id: c for c in (await db.scalars(select(Category))).all()}
    assert set(rows) == {CAT_HAIR["category_id"], CAT_SKIN["category_id"], CAT_SOAP["category_id"]}

    # 2. The hierarchy landed through the crosswalk, with coherent bounds.
    hair, skin, soap = (rows[c["category_id"]] for c in (CAT_HAIR, CAT_SKIN, CAT_SOAP))
    assert hair.parent_id is None and hair.is_root and skin.is_root
    assert soap.parent_id == skin.id and not soap.is_root and soap.depth == 1
    assert skin.lft < soap.lft < soap.rgt < skin.rgt
    assert soap.slug == "bathing_soap_bodywash" and soap.position == 1 and soap.meta_keywords is None

    # 3. Identity, gate state and the raw DETAIL document live on the crosswalk,
    #    tax preferences included (they have no column yet).
    record = await db.scalar(select(SyncRecord).where(SyncRecord.module == "categories",
                                                       SyncRecord.external_id == CAT_SOAP["category_id"]))
    assert record.entity_id == soap.id and record.raw_source == "detail_fetch"
    assert [p["tax_specification"] for p in record.raw["category_tax_preferences"]] == ["inter", "intra"]

    # 3b. …and they are ALSO real assignments now: every category carries one tax per context, resolved
    #     through the crosswalk to the components the `taxes` module synced, marked as Zoho's.
    from app.modules.taxes.assignment import TaxAssignment
    from app.modules.taxes.component import TaxComponent

    names = {c.id: c.tax_name for c in (await db.scalars(select(TaxComponent))).all()}
    assignments = (await db.scalars(select(TaxAssignment).where(TaxAssignment.owner_type_code == "category"))).all()
    assert len(assignments) == 6 and all(a.source_system == "zoho" and not a.is_pending for a in assignments)
    assert {(a.owner_id, a.tax_specification): names[a.tax_component_id] for a in assignments} == {
        (c.id, spec): tax for c in (hair, skin, soap) for spec, tax in (("inter", "IGST18"), ("intra", "CGST9"))}

    # 4. A Zoho-side rename arrives through the modified-since filter — and only
    #    that row is rewritten. (Live: the filter takes +0000 and 400s on a "Z".)
    wire.data["categories"][2].update(name="Bath Soaps", last_modified_time="2026-09-25T10:00:00+0530")
    await run_all(db)
    filtered = [r for r in wire.requests if r.url.path.endswith("/categories") and "last_modified_time" in r.url.params]
    assert filtered and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}",
                                     filtered[-1].url.params["last_modified_time"])
    await db.refresh(soap)
    assert soap.name == "Bath Soaps"
    updated_ids = set(await db.scalars(select(ZohoSyncEvent.local_id).where(
        ZohoSyncEvent.module == "categories", ZohoSyncEvent.event_type == "updated",
        ZohoSyncEvent.zoho_id == CAT_SOAP["category_id"])))
    assert updated_ids == {soap.id}

    # 5. A category deleted in Zoho is only ever visible to a FULL scan; with the
    #    operator switch on, that scan tombstones it on BOTH sides.
    monkeypatch.setattr(settings, "ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING", True)
    del wire.data["categories"][2]
    client = transport_module.ZohoClient(default_module="categories")
    try:
        result = await execute_leased_run(db, client, module_name="categories", lane="weekly_full",
                                          mode="full", trigger="planner")
    finally:
        await client.aclose()
    assert result["status"] == RunStatus.SUCCEEDED and result["soft_deleted"] == 1
    db.expire_all()
    gone = await db.scalar(select(Category).where(Category.zoho_id == CAT_SOAP["category_id"])
                           .execution_options(include_deleted=True))
    assert gone.deleted_at is not None
    tombstone = await db.scalar(select(SyncRecord).where(SyncRecord.module == "categories",
                                                          SyncRecord.external_id == CAT_SOAP["category_id"]))
    assert tombstone.remote_deleted_at is not None
    assert await db.scalar(select(func.count()).select_from(Category)) == 2      # hair, skin live


async def test_the_chart_of_accounts_and_the_taxes_ledger_links_end_to_end(db, wire, monkeypatch):
    """The chart lands with its tree and currency; a tax synced BEFORE it waits; the reconcile lane links it.

    Runs with the opt-in DETAIL phase switched on (the control-plane override an operator would set), so
    the reference only the detail document carries (``currency_id``) goes through the single-record
    apply — the path whose DEFER waiters used to be dropped.
    """
    from app.database.tenancy import tenant_scope
    from app.modules.accounting.assignment import AccountAssignment
    from app.modules.accounting.model import Account
    from app.modules.currencies.model import Currency
    from app.modules.organizations.model import Organization
    from app.modules.resolution import Outcome, OwnerRef, Subject, resolve_many
    from app.modules.sync.models import PendingReference
    from app.modules.sync.reconcile import drain_pending_references
    from app.modules.taxes.component import TaxComponent

    from app.tasks.zoho_sync import execute_leased_run

    chart = sync_registry.get("chart_of_accounts")
    monkeypatch.setattr(chart, "config", chart.config.model_copy(update={
        "detail_required": True, "index_then_detail": True, "wait_between_calls": 0.0}))

    # The WORST order on purpose (there is no planner DAG yet, delta-v3 §6.2): the tax names an account
    # that does not exist yet, and the chart names a currency that does not exist yet — a reference only
    # the DETAIL document carries. Both must wait on sync.pending_references (regression: the detail
    # phase used to drop its DEFER waiters), and the reconcile lane links them.
    for module in ("organizations", "taxes", "chart_of_accounts", "currencies"):
        client = transport_module.ZohoClient(default_module=module)
        try:
            result = await execute_leased_run(db, client, module_name=module, lane="scheduled", mode=None,
                                              trigger="planner")
        finally:
            await client.aclose()
        assert result["status"] == RunStatus.SUCCEEDED, (module, result)
    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    waiting = {(p.module, p.waiting_column) for p in await db.scalars(select(PendingReference))}
    assert {("currencies", "currency_id"), ("chart_of_accounts", "account_id")} <= waiting
    assert (await drain_pending_references(db, tenant_id=org.tenant_id)).linked >= 4
    await db.commit()
    db.expire_all()                                 # the reconcile lane wrote with bare UPDATEs
    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    accounts = {a.zoho_id: a for a in await db.scalars(select(Account))}
    assert set(accounts) == {"982000000567000", "982000000567001", "982000000567010"}
    parent, output, sales = accounts["982000000567000"], accounts["982000000567001"], accounts["982000000567010"]
    assert output.parent_id == parent.id and output.depth == 1 and parent.depth == 0   # child listed first
    assert output.normal_balance_is_debit is False and sales.account_code is None        # "" -> NULL
    assert output.organization_id == org.id and output.description == "Synced from Zoho"
    inr = await db.scalar(select(Currency).where(Currency.currency_code == "INR"))
    assert output.currency_id == inr.id                                                   # ReferenceRule, resolved

    igst = await db.scalar(select(TaxComponent).where(TaxComponent.tax_name == "IGST18"))
    # taxes ran before the chart: the tax named its output account before it existed -> pending
    link = await db.scalar(select(AccountAssignment).where(AccountAssignment.owner_type_code == "tax_component",
                                                           AccountAssignment.owner_id == igst.id))
    assert link is not None and link.source_system == "zoho" and link.purpose_code == "output_tax"
    assert link.account_id == output.id                     # directly, or pending then linked by reconcile
    assert link.external_ref == "982000000567001"           # the Zoho account id stays on the link, always
    assert await db.scalar(select(PendingReference.id).where(PendingReference.waiting_id == link.id)) is None

    # "which account does IGST18 post to in this organization?" -- the engine answers through the tax
    with tenant_scope(org.tenant_id, org.id):
        (answer,) = await resolve_many(db, "account", "tax_line", [Subject(
            roles={"tax_component": OwnerRef("tax_component", igst.id)}, organization_id=org.id,
            context={"purpose": "output_tax"})])
    assert (answer.outcome, answer.values[0].account_id) == (Outcome.ANSWERED, output.id)

    # a balance moving in Zoho is not a change to the account
    wire.data["chartofaccounts"][0]["current_balance"] = 999999
    second = await run_all(db)
    assert second["chart_of_accounts"]["created"] == second["chart_of_accounts"]["updated"] == 0


async def test_price_lists_end_to_end_through_the_real_transport(db, wire):
    """Books land from the list, items and brackets from the detail; the age gate catches an unbumped edit."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    from app.modules.currencies.model import Currency
    from app.modules.organizations.model import Organization
    from app.modules.price_lists.model import PriceList, PriceListItem, PriceListItemBracket
    from app.modules.sync.models import SyncRecord
    from app.modules.sync.reconcile import drain_pending_references

    first = await run_all(db)
    assert first["price_lists"]["status"] == RunStatus.SUCCEEDED
    assert first["price_lists"]["created"] == 3
    assert wire.calls_to("/pricebooks") == 1
    assert all(wire.calls_to(f"/pricebooks/{b['pricebook_id']}") == 1 for b in PRICEBOOKS)

    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    # Registry order is import order: if price_lists ran before currencies, its currency waits on
    # sync.pending_references (DEFER) and the reconcile lane links it — either way it ends linked.
    await drain_pending_references(db, tenant_id=org.tenant_id)
    await db.commit()
    db.expire_all()
    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    inr = await db.scalar(select(Currency).where(Currency.currency_code == "INR"))
    books = {b.zoho_id: b for b in await db.scalars(select(PriceList))}
    unit, volume, markup = books["982000000870001"], books["982000000870002"], books["982000000870003"]
    assert {b.organization_id for b in books.values()} == {org.id}               # the connection's organization
    assert (unit.price_list_type, unit.pricing_scheme, unit.currency_id, unit.percentage) == (
        "per_item", "unit", inr.id, None)                                          # "" percentage -> NULL
    assert unit.is_default is False                                               # detail-only flag landed
    assert (markup.pricing_scheme, markup.currency_id, markup.status, markup.rounding_type) == (
        None, None, "inactive", "round_to_dollar")
    assert float(markup.percentage) == 35.71 and markup.is_increase is True

    items = {(i.price_list_id, i.item_zoho_id): i for i in await db.scalars(select(PriceListItem))}
    assert len(items) == 3
    scrub = items[(unit.id, "982000000880001")]
    assert (scrub.zoho_id, float(scrub.rate), scrub.discount) == ("982000000870101", 64.41, None)
    vol_item = items[(volume.id, "982000000880001")]
    assert vol_item.zoho_id is None and vol_item.rate is None           # volume: the brackets carry it
    brackets = list(await db.scalars(select(PriceListItemBracket).order_by(PriceListItemBracket.start_quantity)))
    assert [(b.zoho_id, float(b.start_quantity), b.end_quantity and float(b.end_quantity), float(b.rate))
            for b in brackets] == [("982000000870201", 10, 19, 19), ("982000000870202", 20, 49, 18),
                                   ("982000000870203", 50, None, 15.84)]
    assert {b.organization_id for b in brackets} == {org.id}
    middle_id = brackets[1].id                                          # captured: expire_all() below

    # Second pass: nothing moved -> the list is the only call, nothing is written.
    second = await run_all(db)
    assert second["price_lists"]["created"] == second["price_lists"]["updated"] == 0
    assert wire.calls_to("/pricebooks") == 2                                    # listed again …
    assert sum(wire.calls_to(f"/pricebooks/{b['pricebook_id']}") for b in PRICEBOOKS) == 3   # … no detail spent

    # Zoho edits a bracket and drops an item WITHOUT bumping the book's timestamp (undocumented either way).
    live = wire.pricebook_items
    live["982000000870002"][0]["price_brackets"][1]["pricebook_rate"] = 17.5
    live["982000000870001"].pop()                                  # Aloe Gel leaves the book
    await run_all(db)
    db.expire_all()
    assert (await db.get(PriceListItemBracket, middle_id)).rate == 18   # trusted timestamp: unseen

    # A day later the age gate re-confirms each detail (detail_max_age_minutes=1440) and the edits land.
    await db.execute(update(SyncRecord).where(SyncRecord.module == "price_lists")
                     .values(raw_synced_at=func.now() - func.make_interval(0, 0, 0, 2)))
    await db.commit()
    third = await run_all(db)
    assert third["price_lists"]["updated"] == 2 and third["price_lists"]["unchanged"] >= 1
    db.expire_all()
    assert float((await db.get(PriceListItemBracket, middle_id)).rate) == 17.5
    gone = await db.scalar(select(PriceListItem).where(PriceListItem.item_zoho_id == "982000000880002")
                           .execution_options(include_deleted=True))
    assert gone.deleted_at is not None and gone.deleted_reason == "zoho:removed_from_price_list"
    # the unchanged percentage book's detail was confirmed, not rewritten: its stamp moved forward
    stamp = await db.scalar(select(SyncRecord.raw_synced_at).where(SyncRecord.module == "price_lists",
                                                                   SyncRecord.external_id == "982000000870003"))
    assert stamp is not None and (datetime.now(UTC) - stamp).total_seconds() < 600


async def _run(db, module: str) -> dict:
    from app.tasks.zoho_sync import execute_leased_run

    client = transport_module.ZohoClient(default_module=module)
    try:
        return await execute_leased_run(db, client, module_name=module, lane="scheduled", mode=None, trigger="planner")
    finally:
        await client.aclose()


async def test_parties_end_to_end_through_the_real_transport(db, wire, monkeypatch):
    """Contacts land as parties (list first, detail completes them); a rate limit mid-page keeps the page's
    progress and resumes on the same page; merges redirect; a stale merged id never overwrites the survivor;
    a contact missing from a scan is only tombstoned once Zoho confirms it is gone."""
    from app.core.conf import settings
    from app.modules.currencies.model import Currency
    from app.modules.geo.model.link import PlaceLink
    from app.modules.parties.model import ContactPerson, Party, PaymentTerm
    from app.modules.price_lists.model import PriceList
    from app.modules.sync.crosswalk import resolve_many
    from app.modules.sync.models import LinkState, SyncRecord
    from app.modules.taxes.tax_registration import TaxRegistration
    from app.modules.zoho.control.runs import load_cursor

    a, b, c = "982000000990001", "982000000990002", "982000000990003"
    for module in ("organizations", "currencies", "price_lists"):
        assert (await _run(db, module))["status"] == RunStatus.SUCCEEDED

    # 1. Zoho throttles the detail of B: A's detail is kept, the page's list rows are kept, the cursor stays.
    wire.contact_rate_limited = {b}
    with pytest.raises(Exception):
        await _run(db, "parties")
    await db.rollback()
    parties = {p.zoho_id: p for p in await db.scalars(select(Party))}
    assert set(parties) == {a, b, c}                                   # the index phase was committed
    assert len(list(await db.scalars(select(ContactPerson)))) == 2   # A's detail was committed
    states = {r.external_id: r.raw_source for r in await db.scalars(select(SyncRecord).where(SyncRecord.module == "parties"))}
    assert states[a] == "detail_fetch" and states[b].startswith("list:") and states[c].startswith("list:")
    cursor = await load_cursor(db, module="parties", lane="scheduled")
    assert cursor.next_page == 1                                      # resume ON the page, not after it

    # 2. Throttle lifted: B and C complete, A's detail is not fetched again.
    wire.contact_rate_limited = set()
    result = await _run(db, "parties")
    assert result["status"] == RunStatus.SUCCEEDED, result
    assert wire.calls_to(f"/contacts/{a}") == 1 and wire.calls_to(f"/contacts/{c}") == 1
    db.expire_all()

    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    inr = await db.scalar(select(Currency).where(Currency.currency_code == "INR"))
    volume = await db.scalar(select(PriceList).where(PriceList.zoho_id == "982000000870002"))
    parties = {p.zoho_id: p for p in await db.scalars(select(Party))}
    pa, pb, pc = parties[a], parties[b], parties[c]
    pb_id, pc_id = pb.id, pc.id                       # captured: expire_all() below
    assert {p.organization_id for p in parties.values()} == {org.id}
    assert (pa.party_type, pa.currency_id, pa.price_list_id, pa.place_of_supply) == ("customer", inr.id, volume.id, "GJ")
    persons = {p.zoho_id: p for p in await db.scalars(select(ContactPerson))}
    assert pa.primary_contact_person_id == persons["982000000990701"].id and persons["982000000990701"].is_primary
    links = {link.zoho_id: link for link in await db.scalars(select(PlaceLink).where(PlaceLink.owner_type == "party"))}
    assert links["982000000990801"].place_id == links["982000000990802"].place_id     # one place, two links
    assert "982000000990804" not in links                                             # phone-only shipping: nothing
    assert links["982000000990803"].owner_id == pb.id                                 # city + state is an address
    regs = {(r.owner_id, r.registration_type): r for r in await db.scalars(select(TaxRegistration))}
    assert regs[(pa.id, "pan")].registration_number == "ABCDE1234F"
    assert regs[(pa.id, "gstin")].zoho_id == "982000000990601"
    term = await db.scalar(select(PaymentTerm))
    assert pa.payment_term_id == term.id and term.zoho_id == "982000000990501"
    assert (pb.payment_terms, pb.payment_terms_label, pb.payment_term_id) == (-3, "Due end of next month", None)
    assert (pc.party_type, pc.status, pc.gst_treatment, pc.is_taxable) == (
        "vendor", "inactive", "business_registered_composition", None)

    # 3. Merges: the retired id resolves to the survivor wherever a document names it.
    (row,) = (await db.execute(resolve_many(tenant_id=org.tenant_id, source_system="zoho",
                                            pairs=[("parties", "982000000990099")]))).all()
    assert (row.entity_id, row.link_state) == (pb.id, LinkState.MERGED)

    # 4. Zoho lists the retired id again (a stale merge record): it is ignored, never applied to the survivor.
    stale = {**CONTACTS[1], "contact_id": "982000000990099", "contact_name": "Old Duplicate",
             "created_time": "2025-04-01T10:00:00+0530", "last_modified_time": "2026-08-01T10:00:00+0530"}
    wire.data["contacts"].append(stale)
    await _run(db, "parties")
    db.expire_all()
    assert (await db.get(Party, pb_id)).name == "Shreeji Traders"
    assert await db.scalar(select(Party).where(Party.name == "Old Duplicate")) is None
    wire.data["contacts"].pop()

    # 5. C vanishes from the LIST but Zoho still returns it: a paging artefact, not a deletion.
    monkeypatch.setattr(settings, "ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING", True)
    monkeypatch.setattr(settings, "ZOHO_SYNC_MASS_DELETE_MIN", 5)
    wire.data["contacts"] = [r for r in wire.data["contacts"] if r["contact_id"] != c]
    await _run(db, "parties")
    db.expire_all()
    assert (await db.get(Party, pc_id)).deleted_at is None
    # … and once Zoho says it does not exist, it is tombstoned.
    wire.contact_details.pop(c)
    await _run(db, "parties")
    db.expire_all()
    gone = await db.scalar(select(Party).where(Party.id == pc_id).execution_options(include_deleted=True))
    assert gone.deleted_at is not None
