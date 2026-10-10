"""Commercial parties — customers and vendors (Zoho "contacts") — and the people who speak for them.

    Party           one customer or vendor of one organization (Zoho crosswalk module ``parties``)
    ContactPerson   a person of a party (Zoho ``contact_persons[]``; crosswalk module ``contact_persons``)
    PaymentTerm     a payment term as Zoho names it, learned from party payloads (Zoho id = identity)

Zoho provenance. ``Party`` is a crosswalk module: identity, the gate's fence and hash and the raw
document live in ``sync.sync_records``; the row carries business columns plus the engine-maintained
``zoho_id`` echo. Persons are projected from the DETAIL document by the adapter's hook and each gets
its own crosswalk row, because invoices and sales orders name contact persons by id.

Everything that is not a column lives in the hub that owns it (one truth each):

    addresses          geo.place_links (owner ``party`` / ``contact_person``) → geo.places (coordinates)
    GSTIN, PAN, Udyam  tax.tax_registrations (owner ``party``)
    default tax        tax.tax_assignments (owner ``party``)       — HasTaxesMixin
    control accounts   accounting.account_assignments              — HasAccountsMixin
    custom fields      extfields.field_values                       — HasCustomFieldsMixin
    sub-category       core.categorizables (taxonomy ``customer_sub_category``) — HasCategoriesMixin
    media / avatar     media.items                                  — HasMediaMixin
    documents          documents.document_links                     — HasDocumentsMixin
    comments           comments.comments                            — HasCommentsMixin

Balances are never stored: a balance moving is not the party changing (finance read models own them).

Scoping: ``OrgEntityMixin`` everywhere; persons pin their party's tenant AND organization through a
composite FK, so a person can never hang under another organization's party.

Loaders (stated): every relationship is ``lazy="raise"`` / ``raise_on_sql``; crud loads explicitly.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.accounting.mixins import HasAccountsMixin
from app.modules.categories.mixins import HasCategoriesMixin
from app.modules.comments.mixins import HasCommentsMixin
from app.modules.currencies.mixins import HasCurrencyMixin
from app.modules.custom_fields.mixins import HasCustomFieldsMixin
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.geo.mixins import HasAddressesMixin
from app.modules.media.mixins import HasMediaMixin
from app.modules.parties.enums import (
    CONTACT_PERSON_ENTITY_TYPE,
    PARTY_ENTITY_TYPE,
    PARTY_SCHEMA,
    CustomerSubType,
    PartyStatus,
    PartyType,
    values,
)
# FK targets mapped wherever a party is (a Celery worker importing only this module).
from app.modules.price_lists import model as _price_list_model  # noqa: F401
from app.modules.taxes.mixins import HasTaxesMixin
from app.modules.zoho_users import model as _zoho_user_model  # noqa: F401

_LIVE = text("deleted_at IS NULL")
_ACTIVE_INACTIVE = f"status IN ({values(PartyStatus)})"


class PaymentTerm(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A payment term as Zoho names it (learned from party payloads; no Zoho endpoint is documented)."""

    __tablename__ = "payment_terms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_payment_terms_scope_id"),
        CheckConstraint("btrim(label) <> ''", name="ck_payment_terms_label_not_blank"),
        CheckConstraint(_ACTIVE_INACTIVE, name="ck_payment_terms_status"),
        Index("uq_payment_terms_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        {"schema": PARTY_SCHEMA,
         "comment": "Payment terms as Zoho names them (Zoho id = identity; code < 0 = a rule, not days)."},
    )

    zoho_id: Mapped[str | None] = mapped_column(String(50), comment="Zoho payment_terms_id; NULL = a local term")
    payment_terms: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Zoho code: >= 0 = net days; < 0 = a rule (-3 = 'Due end of next month', observed live)",
    )
    label: Mapped[str] = mapped_column(Text, nullable=False, comment="Zoho payment_terms_label, verbatim")
    net_days: Mapped[int | None] = mapped_column(
        Integer, Computed("CASE WHEN payment_terms >= 0 THEN payment_terms END", persisted=True),
        comment="Net days when the code is a day count (generated)",
    )
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
        comment="When a party payload first named it",
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<PaymentTerm {self.label!r} code={self.payment_terms} zoho={self.zoho_id}>"


class Party(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, VerificationMixin, HasCurrencyMixin, HasAddressesMixin,
    HasTaxesMixin, HasAccountsMixin, HasCustomFieldsMixin, HasCategoriesMixin, HasDocumentsMixin,
    HasMediaMixin, HasCommentsMixin, SoftDeleteFilteredMixin, Base,
):
    """One customer or vendor of one organization."""

    __tablename__ = "parties"
    custom_fields_owner_type = PARTY_ENTITY_TYPE
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_parties_scope_id"),
        HasCurrencyMixin.currency_fk("parties"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "price_list_id"],
            ["pricing.price_lists.tenant_id", "pricing.price_lists.organization_id", "pricing.price_lists.id"],
            name="fk_parties_price_list", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "payment_term_id"],
            [f"{PARTY_SCHEMA}.payment_terms.tenant_id", f"{PARTY_SCHEMA}.payment_terms.organization_id",
             f"{PARTY_SCHEMA}.payment_terms.id"],
            name="fk_parties_payment_term", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "merged_into_party_id"],
            [f"{PARTY_SCHEMA}.parties.tenant_id", f"{PARTY_SCHEMA}.parties.organization_id",
             f"{PARTY_SCHEMA}.parties.id"],
            name="fk_parties_merged_into", ondelete="RESTRICT",
        ),
        # The party → primary person pointer closes a cycle with contact_persons.party_id: created after
        # both tables (use_alter) and checked at COMMIT, so the hook can insert persons and point at one
        # in a single flush.
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "primary_contact_person_id"],
            [f"{PARTY_SCHEMA}.contact_persons.tenant_id", f"{PARTY_SCHEMA}.contact_persons.organization_id",
             f"{PARTY_SCHEMA}.contact_persons.id"],
            name="fk_parties_primary_person", ondelete="RESTRICT",
            use_alter=True, deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_parties_name_not_blank"),
        CheckConstraint(f"party_type IN ({values(PartyType)})", name="ck_parties_type"),
        CheckConstraint(f"customer_sub_type IS NULL OR customer_sub_type IN ({values(CustomerSubType)})",
                        name="ck_parties_customer_sub_type"),
        CheckConstraint(_ACTIVE_INACTIVE, name="ck_parties_status"),
        CheckConstraint("credit_limit IS NULL OR credit_limit >= 0", name="ck_parties_credit_limit"),
        CheckConstraint("merged_into_party_id IS NULL OR merged_into_party_id <> id",
                        name="ck_parties_not_merged_into_self"),
        CheckConstraint("verification_status IN ('unverified','geocoded_only','field_verified','disputed')",
                        name="ck_parties_verification_status"),
        Index("uq_parties_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_parties_org_type_status", "organization_id", "party_type", "status", postgresql_where=_LIVE),
        Index("ix_parties_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"},
              postgresql_where=_LIVE),
        Index("ix_parties_company_trgm", "company_name", postgresql_using="gin",
              postgresql_ops={"company_name": "gin_trgm_ops"},
              postgresql_where=text("deleted_at IS NULL AND company_name IS NOT NULL")),
        # Phone search the way people type it: the last 10 digits, whatever the formatting.
        Index("ix_parties_mobile_last10", "organization_id",
              text("right(regexp_replace(mobile, '\\D', '', 'g'), 10)"),
              postgresql_where=text("deleted_at IS NULL AND mobile IS NOT NULL")),
        Index("ix_parties_email_lower", "organization_id", text("lower(email)"),
              postgresql_where=text("deleted_at IS NULL AND email IS NOT NULL")),
        Index("ix_parties_price_list", "price_list_id",
              postgresql_where=text("deleted_at IS NULL AND price_list_id IS NOT NULL")),
        Index("ix_parties_merged_into", "merged_into_party_id",
              postgresql_where=text("merged_into_party_id IS NOT NULL")),
        {"schema": PARTY_SCHEMA,
         "comment": "Customers and vendors of one organization (Zoho contacts); Zoho crosswalk module parties."},
    )

    # identity (Zoho)
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Engine-maintained echo of Zoho contact_id (not the identity of record)",
    )
    contact_number: Mapped[str | None] = mapped_column(Text, comment="Zoho contact_number (optional)")
    source_created_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Zoho created_time (party since)",
    )

    # names
    name: Mapped[str] = mapped_column(Text, nullable=False, comment="Display name (Zoho contact_name)")
    company_name: Mapped[str | None] = mapped_column(Text)
    legal_name: Mapped[str | None] = mapped_column(Text, comment="Legal name (GST registration)")
    trade_name: Mapped[str | None] = mapped_column(Text, comment="Trade name (Zoho trader_name)")
    salutation: Mapped[str | None] = mapped_column(String(25), comment="Zoho contact_salutation")
    first_name: Mapped[str | None] = mapped_column(String(100), comment="Zoho's party-level echo of the primary person")
    last_name: Mapped[str | None] = mapped_column(String(100))
    designation: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))

    # classification
    party_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="customer | vendor (Zoho contact_type)")
    customer_sub_type: Mapped[str | None] = mapped_column(String(16), comment="business | individual")
    source: Mapped[str | None] = mapped_column(String(32), comment="Zoho source: api | csv | user …")
    sales_channel: Mapped[str | None] = mapped_column(
        String(32), comment="Zoho sales_channel (route to market, e.g. direct_sales); no CHECK — Zoho's open set",
    )
    language_code: Mapped[str | None] = mapped_column(String(10))

    # commercial (currency_id from HasCurrencyMixin)
    is_base_currency_only: Mapped[bool | None] = mapped_column(Boolean, comment="Zoho is_bcy_only_contact")
    price_list_id: Mapped[int | None] = mapped_column(BigInteger, comment="Zoho pricebook_id → pricing.price_lists")
    payment_term_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Zoho payment_terms_id → party.payment_terms; NULL when Zoho sends ''",
    )
    payment_terms: Mapped[int | None] = mapped_column(Integer, comment="Zoho payment-terms code (always carried)")
    payment_terms_label: Mapped[str | None] = mapped_column(Text)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), comment="Customers")
    is_taxable: Mapped[bool | None] = mapped_column(Boolean, comment="Absent on vendors → NULL, not false")
    place_of_supply: Mapped[str | None] = mapped_column(String(4), comment="GST state code (Zoho place_of_contact)")
    gst_treatment: Mapped[str | None] = mapped_column(
        String(40), comment="tax.gst_treatment_types.value (no CHECK: Zoho sends undocumented values)",
    )
    contact_category: Mapped[str | None] = mapped_column(String(40), comment="Zoho contact_category")

    # communication (party level)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    mobile: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(Text)
    facebook: Mapped[str | None] = mapped_column(String(100))
    twitter: Mapped[str | None] = mapped_column(String(100))
    is_sms_enabled: Mapped[bool | None] = mapped_column(Boolean)
    payment_reminder_enabled: Mapped[bool | None] = mapped_column(Boolean)
    portal_status: Mapped[str | None] = mapped_column(String(16), comment="Zoho portal_status")

    # relations
    primary_contact_person_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Zoho primary_contact_id → party.contact_persons",
    )
    owner_zoho_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("zoho_users.id", ondelete="SET NULL", name="fk_parties_owner_zoho_user"),
        comment="Zoho owner_id → zoho_users",
    )
    merged_into_party_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The survivor after a Zoho merge of duplicates (cf_merged_customer_ids)",
    )

    # compliance / flags
    consent_agreed: Mapped[bool | None] = mapped_column(Boolean, comment="Zoho is_consent_agreed (DPDP)")
    consent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), comment="Zoho consent_date")
    has_transaction: Mapped[bool | None] = mapped_column(Boolean)
    is_associated_to_branch: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text, comment="Zoho notes (internal discussion = comments)")

    persons: Mapped[list[ContactPerson]] = relationship(
        "ContactPerson",
        primaryjoin="and_(Party.id == foreign(ContactPerson.party_id), ContactPerson.deleted_at.is_(None))",
        viewonly=True, lazy="raise", order_by="(ContactPerson.position, ContactPerson.id)",
    )
    payment_term: Mapped[PaymentTerm | None] = relationship(
        PaymentTerm, primaryjoin="foreign(Party.payment_term_id) == PaymentTerm.id", viewonly=True, lazy="raise",
    )

    @property
    def is_customer(self) -> bool:
        return self.party_type == PartyType.CUSTOMER.value

    @property
    def is_vendor(self) -> bool:
        return self.party_type == PartyType.VENDOR.value

    def __repr__(self) -> str:
        return f"<Party id={self.id} {self.party_type} {self.name!r}>"


class ContactPerson(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasAddressesMixin, HasCustomFieldsMixin, HasDocumentsMixin,
    HasMediaMixin, HasCommentsMixin, SoftDeleteFilteredMixin, Base,
):
    """A person who speaks for a party. Where they are = their addresses (places carry coordinates);
    their avatar = media collection ``avatar``."""

    __tablename__ = "contact_persons"
    custom_fields_owner_type = CONTACT_PERSON_ENTITY_TYPE
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_contact_persons_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "party_id"],
            [f"{PARTY_SCHEMA}.parties.tenant_id", f"{PARTY_SCHEMA}.parties.organization_id",
             f"{PARTY_SCHEMA}.parties.id"],
            name="fk_contact_persons_party", ondelete="RESTRICT",
        ),
        CheckConstraint(_ACTIVE_INACTIVE, name="ck_contact_persons_status"),
        Index("uq_contact_persons_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        # Zoho allows exactly one primary person per contact.
        Index("uq_contact_persons_one_primary", "party_id", unique=True,
              postgresql_where=text("is_primary AND deleted_at IS NULL")),
        Index("ix_contact_persons_party", "party_id", "position", postgresql_where=_LIVE),
        Index("ix_contact_persons_mobile_last10", "organization_id",
              text("right(regexp_replace(mobile, '\\D', '', 'g'), 10)"),
              postgresql_where=text("deleted_at IS NULL AND mobile IS NOT NULL")),
        Index("ix_contact_persons_email_lower", "organization_id", text("lower(email)"),
              postgresql_where=text("deleted_at IS NULL AND email IS NOT NULL")),
        Index("ix_contact_persons_user", "user_id", postgresql_where=text("user_id IS NOT NULL")),
        {"schema": PARTY_SCHEMA,
         "comment": "People of a party (Zoho contact_persons[]); Zoho crosswalk module contact_persons."},
    )

    party_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zoho_id: Mapped[str | None] = mapped_column(String(50), comment="Zoho contact_person_id")
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_contact_persons_user"),
        comment="LOCAL: the platform user this person signs in as (portal / app), when they have one",
    )
    salutation: Mapped[str | None] = mapped_column(String(25))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    display_name: Mapped[str | None] = mapped_column(
        Text,
        Computed("NULLIF(btrim(coalesce(btrim(first_name), '') || ' ' || coalesce(btrim(last_name), '')), '')",
                 persisted=True),
        comment="first + last (generated)",
    )
    designation: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    mobile: Mapped[str | None] = mapped_column(String(50))
    mobile_country_code: Mapped[str | None] = mapped_column(String(8))
    fax: Mapped[str | None] = mapped_column(String(50))
    skype: Mapped[str | None] = mapped_column(String(100))

    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), comment="Zoho is_primary_contact",
    )
    is_email_enabled: Mapped[bool | None] = mapped_column(Boolean, comment="communication_preference.is_email_enabled")
    is_whatsapp_enabled: Mapped[bool | None] = mapped_column(
        Boolean, comment="communication_preference.is_whatsapp_enabled",
    )
    is_sms_enabled: Mapped[bool | None] = mapped_column(Boolean, comment="Zoho is_sms_enabled_for_cp")
    is_whatsapp_disabled_by_customer: Mapped[bool | None] = mapped_column(Boolean)
    can_invite: Mapped[bool | None] = mapped_column(Boolean)
    is_added_in_portal: Mapped[bool | None] = mapped_column(Boolean)
    is_portal_invitation_accepted: Mapped[bool | None] = mapped_column(Boolean)
    is_portal_mfa_enabled: Mapped[bool | None] = mapped_column(Boolean)
    portal_enabled_via: Mapped[str | None] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"),
                                          comment="Order in Zoho's array")

    def __repr__(self) -> str:
        return f"<ContactPerson id={self.id} party={self.party_id} {self.display_name!r}>"


__all__ = ["ContactPerson", "Party", "PaymentTerm"]
