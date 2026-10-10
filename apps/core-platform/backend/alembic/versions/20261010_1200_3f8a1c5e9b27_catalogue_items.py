"""Catalogue phase 2 — items core: products (variant templates), items (the SKU), storefront content,
variant values, the packaging hierarchy, identifiers/barcodes per level, components, channel listings,
vendors; plus the media gallery and the polymorphic registrations items need.

    catalogue.products / product_attributes      variant templates and their axes
    catalogue.items                              the SKU documents and stock reference
    catalogue.item_merchandising                 1:1 storefront / SEO content (a different owner)
    catalogue.item_attribute_values              a variant's axis values
    catalogue.item_units                         the packaging hierarchy (base_factor by trigger, structure immutable)
    catalogue.item_identifiers                   barcodes / codes, per pack level (GS1)
    catalogue.item_components                    BOM / kit / box contents (acyclic by trigger)
    catalogue.item_sales_channels                channel listings
    catalogue.item_vendors                       suppliers (party.parties vendors)
    media.items.position                         ordering inside a gallery collection
    registrations                                entity types item / product; taxes (item: one tax per context +
                                                 exemptions); accounts (sales / purchase / inventory_asset);
                                                 comments (item, product)

DDL generated verbatim from docs/implementation-plans/catalogue/catalogue_schema.sql (§2 products, §3, §5);
comments from the ORM models — so `alembic check` reports nothing for the catalogue. One statement per execute.

Revision ID: 3f8a1c5e9b27
Revises: 66d0b2e09e76
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8a1c5e9b27"
down_revision: str | None = "66d0b2e09e76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DDL = r"""
CREATE TABLE catalogue.products (
    name               text         NOT NULL,
    name_normalized    text         GENERATED ALWAYS AS (lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))) STORED,
    slug               text,
    code               varchar(40),
    description        text,
    brand_id           bigint,
    manufacturer_id    bigint,
    item_group_id      bigint,
    default_unit_id    bigint,
    zoho_id            varchar(50),
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_products PRIMARY KEY (id),
    CONSTRAINT uq_products_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_products_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_products_brand FOREIGN KEY (tenant_id, organization_id, brand_id)
        REFERENCES core.brands (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_products_manufacturer FOREIGN KEY (tenant_id, organization_id, manufacturer_id)
        REFERENCES core.manufacturers (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_products_item_group FOREIGN KEY (tenant_id, organization_id, item_group_id)
        REFERENCES catalogue.item_groups (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_products_default_unit FOREIGN KEY (tenant_id, organization_id, default_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_products_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_products_slug CHECK (slug IS NULL OR slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT ck_products_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.products IS 'Variant template grouping sellable items (Zoho Inventory item group). Optional per item.';
CREATE UNIQUE INDEX uq_products_scope_slug ON catalogue.products (tenant_id, organization_id, slug)
    WHERE deleted_at IS NULL AND slug IS NOT NULL;
CREATE UNIQUE INDEX uq_products_scope_code ON catalogue.products (tenant_id, organization_id, code)
    WHERE deleted_at IS NULL AND code IS NOT NULL;
CREATE UNIQUE INDEX uq_products_zoho_id ON catalogue.products (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
CREATE INDEX ix_products_name_trgm ON catalogue.products USING gin (name_normalized gin_trgm_ops)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_products_brand ON catalogue.products (brand_id) WHERE deleted_at IS NULL;

CREATE TABLE catalogue.product_attributes (
    product_id     bigint    NOT NULL,
    attribute_id   bigint    NOT NULL,
    position       smallint  NOT NULL DEFAULT 1,
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_product_attributes PRIMARY KEY (id),
    CONSTRAINT fk_product_attributes_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_product_attributes_product FOREIGN KEY (tenant_id, organization_id, product_id)
        REFERENCES catalogue.products (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_product_attributes_attribute FOREIGN KEY (tenant_id, organization_id, attribute_id)
        REFERENCES catalogue.attributes (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_product_attributes_position CHECK (position BETWEEN 1 AND 10)
);
COMMENT ON TABLE catalogue.product_attributes IS 'The variant axes of a product (Zoho supports three: attribute_name1..3).';
CREATE UNIQUE INDEX uq_product_attributes_axis ON catalogue.product_attributes (product_id, attribute_id)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_product_attributes_position ON catalogue.product_attributes (product_id, position)
    WHERE deleted_at IS NULL;

CREATE TABLE catalogue.items (
    -- identity ---------------------------------------------------------------
    zoho_id                   varchar(50),
    sku                       varchar(100),
    sku_normalized            varchar(100) GENERATED ALWAYS AS (upper(btrim(sku))) STORED,
    code                      varchar(40),
    name                      text         NOT NULL,
    name_normalized           text         GENERATED ALWAYS AS (lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))) STORED,
    print_name                text,
    generic_name              text,
    alias_names               text[],
    description               text,
    purchase_description      text,
    source_created_at         timestamptz,
    -- classification ---------------------------------------------------------
    product_id                bigint,
    item_group_id             bigint,
    brand_id                  bigint,
    manufacturer_id           bigint,
    product_type              varchar(32),
    composition               varchar(16)  NOT NULL DEFAULT 'none',
    -- capabilities (Zoho item_type is DERIVED from these on read/push) -------
    can_be_sold               boolean      NOT NULL DEFAULT true,
    can_be_purchased          boolean      NOT NULL DEFAULT true,
    is_inventory_tracked      boolean      NOT NULL DEFAULT true,
    is_returnable             boolean      NOT NULL DEFAULT true,
    is_fulfillable            boolean      NOT NULL DEFAULT true,
    is_taxable                boolean,
    -- lot / expiry / quality policy -----------------------------------------
    track_mode                varchar(16)  NOT NULL DEFAULT 'none',
    expiry_tracked            boolean      NOT NULL DEFAULT false,
    shelf_life_days           integer,
    requires_qc               boolean      NOT NULL DEFAULT false,
    valuation_method          varchar(24),
    -- units ------------------------------------------------------------------
    base_unit_id              bigint,
    zoho_item_unit_id         bigint,
    -- tax code (taxes themselves are tax.tax_assignments) --------------------
    hsn_or_sac                varchar(16),
    -- default commercial values, per BASE unit, organization base currency ---
    sales_rate                numeric(18,6),
    purchase_rate             numeric(18,6),
    mrp                       numeric(18,6),
    mrp_includes_tax          boolean      NOT NULL DEFAULT true,
    -- organization-wide planning defaults (per-warehouse: inventory.replenishment_policies) --
    reorder_level_base        numeric(18,6),
    minimum_order_qty_base    numeric(18,6),
    maximum_order_qty_base    numeric(18,6),
    -- physical facts of ONE base unit (each pack level has its own on item_units) --
    net_weight                numeric(18,6),
    gross_weight              numeric(18,6),
    weight_unit_id            bigint,
    length                    numeric(18,6),
    width                     numeric(18,6),
    height                    numeric(18,6),
    dimension_unit_id         bigint,
    -- storage & regulatory ---------------------------------------------------
    storage_condition         varchar(16),
    storage_temp_min_c        numeric(5,2),
    storage_temp_max_c        numeric(5,2),
    country_of_origin         char(2),
    drug_schedule             varchar(8),
    requires_prescription     boolean      NOT NULL DEFAULT false,
    -- housekeeping -----------------------------------------------------------
    internal_notes            text,
    position                  integer      NOT NULL DEFAULT 0,
    -- standard block (+ DeactivationMixin) -----------------------------------
    deactivation_date timestamptz, deactivation_reason text, deactivated_by bigint,
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_items PRIMARY KEY (id),
    CONSTRAINT uq_items_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_items_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- references -------------------------------------------------------------
    CONSTRAINT fk_items_product FOREIGN KEY (tenant_id, organization_id, product_id)
        REFERENCES catalogue.products (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_items_item_group FOREIGN KEY (tenant_id, organization_id, item_group_id)
        REFERENCES catalogue.item_groups (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_items_brand FOREIGN KEY (tenant_id, organization_id, brand_id)
        REFERENCES core.brands (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_items_manufacturer FOREIGN KEY (tenant_id, organization_id, manufacturer_id)
        REFERENCES core.manufacturers (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_items_base_unit FOREIGN KEY (tenant_id, organization_id, base_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_items_weight_unit FOREIGN KEY (tenant_id, organization_id, weight_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_items_dimension_unit FOREIGN KEY (tenant_id, organization_id, dimension_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    -- rules we own -------------------------------------------------------------
    CONSTRAINT ck_items_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_items_sku_not_blank CHECK (sku IS NULL OR btrim(sku) <> ''),
    CONSTRAINT ck_items_status CHECK (status IN ('draft','active','inactive','discontinued')),
    CONSTRAINT ck_items_composition CHECK (composition IN ('none','assembly','kit')),
    CONSTRAINT ck_items_track_mode CHECK (track_mode IN ('none','batch','serial','batch_serial')),
    -- a lot/serial policy only makes sense for stock the platform tracks
    CONSTRAINT ck_items_track_requires_inventory CHECK (track_mode = 'none' OR is_inventory_tracked),
    CONSTRAINT ck_items_expiry_requires_batch CHECK (NOT expiry_tracked OR track_mode IN ('batch','batch_serial')),
    -- a kit has no stock of its own: its components move
    CONSTRAINT ck_items_kit_not_stocked CHECK (composition <> 'kit' OR NOT is_inventory_tracked),
    CONSTRAINT ck_items_can_trade CHECK (can_be_sold OR can_be_purchased OR status IN ('inactive','discontinued')),
    CONSTRAINT ck_items_shelf_life CHECK (shelf_life_days IS NULL OR shelf_life_days > 0),
    CONSTRAINT ck_items_valuation CHECK (valuation_method IS NULL OR valuation_method IN ('fifo','weighted_average','moving_average')),
    CONSTRAINT ck_items_rates CHECK (
        (sales_rate IS NULL OR sales_rate >= 0) AND (purchase_rate IS NULL OR purchase_rate >= 0) AND (mrp IS NULL OR mrp >= 0)),
    CONSTRAINT ck_items_order_qty CHECK (
        (reorder_level_base IS NULL OR reorder_level_base >= 0)
        AND (minimum_order_qty_base IS NULL OR minimum_order_qty_base > 0)
        AND (maximum_order_qty_base IS NULL OR maximum_order_qty_base > 0)
        AND (maximum_order_qty_base IS NULL OR minimum_order_qty_base IS NULL OR maximum_order_qty_base >= minimum_order_qty_base)),
    CONSTRAINT ck_items_physical CHECK (
        (net_weight IS NULL OR net_weight >= 0) AND (gross_weight IS NULL OR gross_weight >= 0)
        AND (length IS NULL OR length >= 0) AND (width IS NULL OR width >= 0) AND (height IS NULL OR height >= 0)),
    CONSTRAINT ck_items_storage_condition CHECK (storage_condition IS NULL OR storage_condition IN ('ambient','cool','cold_chain','frozen')),
    CONSTRAINT ck_items_storage_temp CHECK (storage_temp_max_c IS NULL OR storage_temp_min_c IS NULL OR storage_temp_max_c >= storage_temp_min_c),
    CONSTRAINT ck_items_country CHECK (country_of_origin IS NULL OR country_of_origin ~ '^[A-Z]{2}$'),
    CONSTRAINT ck_items_drug_schedule CHECK (drug_schedule IS NULL OR drug_schedule IN ('G','H','H1','X','C','C1','OTC')),
    CONSTRAINT ck_items_position CHECK (position >= 0)
);
COMMENT ON TABLE catalogue.items IS
    'The item (SKU) of one organization: what documents and stock movements reference. Zoho crosswalk module `items`. Rates per base unit; stock is never stored here.';
COMMENT ON COLUMN catalogue.items.zoho_id IS 'Echo of Zoho item_id; identity of record is sync.sync_records.';
COMMENT ON COLUMN catalogue.items.print_name IS 'Name printed on documents when it differs from name (short invoice text).';
COMMENT ON COLUMN catalogue.items.product_type IS 'Zoho product_type (goods / service / digital_service / capital_*): Zoho''s open set, no CHECK.';
COMMENT ON COLUMN catalogue.items.composition IS 'none | assembly (Zoho composite, combo_type=assembly: own stock, built from components) | kit (combo_type=kit: no own stock, components move).';
COMMENT ON COLUMN catalogue.items.is_inventory_tracked IS 'Zoho track_inventory. Zoho item_type is derived: inventory if tracked, else sales / purchases / sales_and_purchases from can_be_*.';
COMMENT ON COLUMN catalogue.items.track_mode IS 'none | batch | serial | batch_serial. serial is reserved: no serial tables are built yet (plan 04 §8).';
COMMENT ON COLUMN catalogue.items.generic_name IS 'Generic / salt composition as printed (e.g. "Paracetamol 500 mg"); searchable, drives substitution lookups.';
COMMENT ON COLUMN catalogue.items.alias_names IS 'Search synonyms and trade aliases ("Crocin" for a paracetamol SKU, local-language names).';
COMMENT ON COLUMN catalogue.items.zoho_item_unit_id IS 'The pack level Zoho''s single item unit represents (NULL = the base level). Zoho rates/quantities are converted through it on pull and push.';
-- Shelf-life / expiry / negative-stock rules are NOT item columns: they are scoped, sparse
-- inventory.stock_policies (organization → warehouse → item group → item), see §7.
COMMENT ON COLUMN catalogue.items.base_unit_id IS 'The stocking unit every quantity resolves to. NULL only for thin Zoho items without a unit; such an item transacts with factor 1 until fixed.';
COMMENT ON COLUMN catalogue.items.mrp IS 'Maximum retail price per base unit (Zoho label_rate). Batches may carry their own printed MRP.';
COMMENT ON COLUMN catalogue.items.drug_schedule IS 'Drugs and Cosmetics Rules schedule (H, H1, X, G…); verify vocabulary with the compliance owner.';
CREATE UNIQUE INDEX uq_items_scope_sku ON catalogue.items (tenant_id, organization_id, sku_normalized)
    WHERE deleted_at IS NULL AND sku IS NOT NULL;
CREATE UNIQUE INDEX uq_items_scope_code ON catalogue.items (tenant_id, organization_id, code)
    WHERE deleted_at IS NULL AND code IS NOT NULL;
CREATE UNIQUE INDEX uq_items_zoho_id ON catalogue.items (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
CREATE INDEX ix_items_name_trgm ON catalogue.items USING gin (name_normalized gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX ix_items_generic_name_trgm ON catalogue.items USING gin (lower(generic_name) gin_trgm_ops)
    WHERE deleted_at IS NULL AND generic_name IS NOT NULL;
CREATE INDEX ix_items_alias_names ON catalogue.items USING gin (alias_names) WHERE deleted_at IS NULL AND alias_names IS NOT NULL;
CREATE INDEX ix_items_org_status ON catalogue.items (organization_id, status) WHERE deleted_at IS NULL;
CREATE INDEX ix_items_brand ON catalogue.items (brand_id) WHERE deleted_at IS NULL AND brand_id IS NOT NULL;
CREATE INDEX ix_items_manufacturer ON catalogue.items (manufacturer_id) WHERE deleted_at IS NULL AND manufacturer_id IS NOT NULL;
CREATE INDEX ix_items_product ON catalogue.items (product_id) WHERE deleted_at IS NULL AND product_id IS NOT NULL;
CREATE INDEX ix_items_item_group ON catalogue.items (item_group_id) WHERE deleted_at IS NULL AND item_group_id IS NOT NULL;
CREATE INDEX ix_items_hsn ON catalogue.items (organization_id, hsn_or_sac) WHERE deleted_at IS NULL AND hsn_or_sac IS NOT NULL;


-- ---------------------------------------------------------------------------
-- catalogue.item_merchandising — 1:1 storefront content. A separate row because a DIFFERENT owner
-- writes it (marketing / storefront) at a different rate than Zoho writes the item: SEO edits
-- must never 409 against a sync write on items.row_version, and Zoho never touches this row.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_merchandising (
    item_id               bigint       NOT NULL,
    display_name          text,
    tagline               text,
    slug                  text,
    short_description     text,
    long_description      text,
    is_featured           boolean      NOT NULL DEFAULT false,
    seo_title             text,
    seo_description       text,
    seo_keywords          text[],
    specifications        jsonb,
    specification_set_ref varchar(64),
    is_visible            boolean      NOT NULL DEFAULT true,
    show_in_menu          boolean      NOT NULL DEFAULT true,
    menu_position         integer      NOT NULL DEFAULT 0,
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_item_merchandising PRIMARY KEY (id),
    CONSTRAINT fk_item_merchandising_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_merchandising_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_item_merchandising_slug CHECK (slug IS NULL OR slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT ck_item_merchandising_menu_position CHECK (menu_position >= 0)
);
COMMENT ON TABLE catalogue.item_merchandising IS '1:1 storefront/SEO content of an item; locally owned, never written by the Zoho sync.';
CREATE UNIQUE INDEX uq_item_merchandising_item ON catalogue.item_merchandising (item_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_item_merchandising_slug ON catalogue.item_merchandising (tenant_id, organization_id, slug)
    WHERE deleted_at IS NULL AND slug IS NOT NULL;


-- ---------------------------------------------------------------------------
-- catalogue.item_attribute_values — the axis values of a variant item (Volume = 95 ml).
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_attribute_values (
    item_id               bigint    NOT NULL,
    attribute_id          bigint    NOT NULL,
    attribute_option_id   bigint    NOT NULL,
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_item_attribute_values PRIMARY KEY (id),
    CONSTRAINT fk_item_attribute_values_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_attribute_values_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_item_attribute_values_attribute FOREIGN KEY (tenant_id, organization_id, attribute_id)
        REFERENCES catalogue.attributes (tenant_id, organization_id, id) ON DELETE RESTRICT,
    -- the option must belong to the attribute
    CONSTRAINT fk_item_attribute_values_option FOREIGN KEY (attribute_id, attribute_option_id)
        REFERENCES catalogue.attribute_options (attribute_id, id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX uq_item_attribute_values_axis ON catalogue.item_attribute_values (item_id, attribute_id)
    WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.item_units — THE PACKAGING HIERARCHY (alternate units of measure, case-pack chain).
--
--   PCS (base, factor 1) ← BTL contains 10 PCS (factor 10) ← BOX contains 12 BTL (120)
--                        ← CTN contains 8 BOX (960)
--
-- Chained pattern (each level names the level it CONTAINS) + cached base_factor, maintained by
-- catalogue.guard_item_unit(). The structural columns (unit_id, contents_item_unit_id,
-- contents_qty, is_base) are IMMUTABLE once written: a vendor changing a carton from 8 to 10 boxes
-- RETIRES the old level (valid_to) and creates a new one. Because a level can only point at a
-- level that already exists and can never be repointed, the chain is acyclic by construction.
-- Documents reference item_unit_id AND snapshot the factor, so history never recalculates.
-- Stock is always booked in the base unit; levels never hold stock (no LPN yet — plan 02 §7).
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_units (
    item_id                 bigint        NOT NULL,
    unit_id                 bigint        NOT NULL,
    is_base                 boolean       NOT NULL DEFAULT false,
    contents_item_unit_id   bigint,
    contents_qty            numeric(18,6),
    base_factor             numeric(24,6) NOT NULL,
    label                   text,
    packaging_type_id       bigint,
    -- what the level may be used for -----------------------------------------
    is_sellable             boolean       NOT NULL DEFAULT true,
    is_purchasable          boolean       NOT NULL DEFAULT true,
    is_default_sales        boolean       NOT NULL DEFAULT false,
    is_default_purchase     boolean       NOT NULL DEFAULT false,
    allow_break             boolean       NOT NULL DEFAULT true,
    min_order_qty           numeric(18,6),
    order_multiple          numeric(18,6),
    -- pack prices (per ONE of this level, org base currency) ------------------
    sales_rate              numeric(18,6),
    purchase_rate           numeric(18,6),
    mrp                     numeric(18,6),
    derive_price            boolean       NOT NULL DEFAULT false,
    -- physical facts of one pack of this level --------------------------------
    gross_weight            numeric(18,6),
    weight_unit_id          bigint,
    length                  numeric(18,6),
    width                   numeric(18,6),
    height                  numeric(18,6),
    dimension_unit_id       bigint,
    special_instructions    text,
    valid_from              date          NOT NULL DEFAULT CURRENT_DATE,
    valid_to                date,
    position                smallint      NOT NULL DEFAULT 0,
    zoho_id                 varchar(50),
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_item_units PRIMARY KEY (id),
    CONSTRAINT uq_item_units_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_item_units_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- target of the (item_id, item_unit_id) composite FKs everywhere a unit of THIS item is meant
    CONSTRAINT uq_item_units_item_id UNIQUE (item_id, id),
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_units_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_item_units_unit FOREIGN KEY (tenant_id, organization_id, unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    -- contents must be a level of the SAME item
    CONSTRAINT fk_item_units_contents FOREIGN KEY (item_id, contents_item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_item_units_packaging_type FOREIGN KEY (tenant_id, organization_id, packaging_type_id)
        REFERENCES catalogue.packaging_types (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_item_units_weight_unit FOREIGN KEY (tenant_id, organization_id, weight_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_item_units_dimension_unit FOREIGN KEY (tenant_id, organization_id, dimension_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_item_units_shape CHECK (
        (is_base AND contents_item_unit_id IS NULL AND contents_qty IS NULL AND base_factor = 1)
        OR (NOT is_base AND contents_item_unit_id IS NOT NULL AND contents_qty > 0 AND base_factor > 0)),
    CONSTRAINT ck_item_units_no_self_contents CHECK (contents_item_unit_id IS NULL OR contents_item_unit_id <> id),
    CONSTRAINT ck_item_units_order CHECK (
        (min_order_qty IS NULL OR min_order_qty > 0) AND (order_multiple IS NULL OR order_multiple > 0)),
    CONSTRAINT ck_item_units_rates CHECK (
        (sales_rate IS NULL OR sales_rate >= 0) AND (purchase_rate IS NULL OR purchase_rate >= 0) AND (mrp IS NULL OR mrp >= 0)),
    CONSTRAINT ck_item_units_physical CHECK (
        (gross_weight IS NULL OR gross_weight >= 0) AND (length IS NULL OR length >= 0)
        AND (width IS NULL OR width >= 0) AND (height IS NULL OR height >= 0)),
    CONSTRAINT ck_item_units_default_sellable CHECK (NOT is_default_sales OR is_sellable),
    CONSTRAINT ck_item_units_default_purchasable CHECK (NOT is_default_purchase OR is_purchasable),
    CONSTRAINT ck_item_units_window CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_item_units_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.item_units IS
    'Per-item packaging hierarchy (alternate UoM): each level contains N of another level of the same item; base_factor cached. Structure immutable; changes retire and replace.';
COMMENT ON COLUMN catalogue.item_units.contents_qty IS '1 of this level = contents_qty of contents_item_unit_id. Immutable.';
COMMENT ON COLUMN catalogue.item_units.base_factor IS '1 of this level = base_factor base units. Trigger-maintained; documents snapshot it.';
COMMENT ON COLUMN catalogue.item_units.allow_break IS 'May a sealed pack of this level be opened to sell its contents loose (regulated SKUs: false).';
COMMENT ON COLUMN catalogue.item_units.derive_price IS 'false (default, the AUoM rule): a non-base level is sellable only with an explicit price (price list entry or sales_rate) — never silently prorated. true: fall back to items.sales_rate x base_factor. Ignored on the base level.';
COMMENT ON COLUMN catalogue.item_units.zoho_id IS 'Reserved for a Zoho unit-conversion id if probe P0.9 finds one; Zoho knows only the base unit today.';
-- one live current level per (item, unit); exactly one base; one default per direction
CREATE UNIQUE INDEX uq_item_units_current ON catalogue.item_units (item_id, unit_id)
    WHERE deleted_at IS NULL AND valid_to IS NULL;
CREATE UNIQUE INDEX uq_item_units_base ON catalogue.item_units (item_id)
    WHERE deleted_at IS NULL AND is_base;
CREATE UNIQUE INDEX uq_item_units_default_sales ON catalogue.item_units (item_id)
    WHERE deleted_at IS NULL AND valid_to IS NULL AND is_default_sales;
CREATE UNIQUE INDEX uq_item_units_default_purchase ON catalogue.item_units (item_id)
    WHERE deleted_at IS NULL AND valid_to IS NULL AND is_default_purchase;
CREATE INDEX ix_item_units_contents ON catalogue.item_units (contents_item_unit_id) WHERE contents_item_unit_id IS NOT NULL;

-- items ↔ item_units is circular; the item's Zoho-unit pointer is added once both tables exist
-- (use_alter in the model). Composite: the level must belong to the same item.
ALTER TABLE catalogue.items
    ADD CONSTRAINT fk_items_zoho_item_unit FOREIGN KEY (id, zoho_item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT;


-- ---------------------------------------------------------------------------
-- catalogue.item_identifiers — barcodes and codes, PER PACK LEVEL (GS1: each level has its own
-- GTIN). Scanning a carton's barcode resolves to (item, CTN level) in one index probe.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_identifiers (
    item_id            bigint       NOT NULL,
    item_unit_id       bigint,
    kind               varchar(16)  NOT NULL,
    value              text         NOT NULL,
    value_normalized   text         GENERATED ALWAYS AS (upper(regexp_replace(value, '\s+', '', 'g'))) STORED,
    is_primary         boolean      NOT NULL DEFAULT false,
    source             varchar(16)  NOT NULL DEFAULT 'local',
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_item_identifiers PRIMARY KEY (id),
    CONSTRAINT fk_item_identifiers_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_identifiers_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_item_identifiers_item_unit FOREIGN KEY (item_id, item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_item_identifiers_kind CHECK (kind IN ('gtin','ean','upc','isbn','barcode','mpn','part_number','other')),
    CONSTRAINT ck_item_identifiers_value_not_blank CHECK (btrim(value) <> ''),
    -- GS1 numeric shapes; the check digit is validated in the service (mod-10)
    CONSTRAINT ck_item_identifiers_format CHECK (CASE kind
        WHEN 'gtin' THEN value_normalized ~ '^[0-9]{8}$|^[0-9]{12,14}$'
        WHEN 'ean'  THEN value_normalized ~ '^[0-9]{8}$|^[0-9]{13}$'
        WHEN 'upc'  THEN value_normalized ~ '^[0-9]{12}$'
        WHEN 'isbn' THEN value_normalized ~ '^[0-9]{9}[0-9X]$|^[0-9]{13}$'
        ELSE true END),
    CONSTRAINT ck_item_identifiers_source CHECK (source IN ('local','zoho','import'))
);
COMMENT ON TABLE catalogue.item_identifiers IS 'Barcodes/codes of an item, optionally per pack level (item_unit_id NULL = the base unit). Zoho upc/ean/isbn/part_number land here.';
-- a SCANNABLE code resolves to exactly one (item, level) in the organization
CREATE UNIQUE INDEX uq_item_identifiers_scannable ON catalogue.item_identifiers (tenant_id, organization_id, value_normalized)
    WHERE deleted_at IS NULL AND kind IN ('gtin','ean','upc','isbn','barcode');
CREATE UNIQUE INDEX uq_item_identifiers_primary ON catalogue.item_identifiers (item_id, item_unit_id, kind) NULLS NOT DISTINCT
    WHERE deleted_at IS NULL AND is_primary;
CREATE INDEX ix_item_identifiers_lookup ON catalogue.item_identifiers (tenant_id, organization_id, kind, value_normalized)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_item_identifiers_item ON catalogue.item_identifiers (item_id) WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.item_components — bill of materials / kit contents / box contents.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_components (
    parent_item_id            bigint        NOT NULL,
    component_item_id         bigint        NOT NULL,
    component_item_unit_id    bigint,
    role                      varchar(24)   NOT NULL,
    quantity                  numeric(18,6) NOT NULL,
    wastage_pct               numeric(5,2)  NOT NULL DEFAULT 0,
    substitute_group          varchar(40),
    is_optional               boolean       NOT NULL DEFAULT false,
    position                  smallint      NOT NULL DEFAULT 0,
    valid_from                date          NOT NULL DEFAULT CURRENT_DATE,
    valid_to                  date,
    zoho_id                   varchar(50),
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_item_components PRIMARY KEY (id),
    CONSTRAINT fk_item_components_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_components_parent FOREIGN KEY (tenant_id, organization_id, parent_item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_item_components_component FOREIGN KEY (tenant_id, organization_id, component_item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_item_components_component_unit FOREIGN KEY (component_item_id, component_item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_item_components_not_self CHECK (parent_item_id <> component_item_id),
    CONSTRAINT ck_item_components_role CHECK (role IN ('assembly_component','kit_member','box_content','packaging_material')),
    CONSTRAINT ck_item_components_quantity CHECK (quantity > 0),
    CONSTRAINT ck_item_components_wastage CHECK (wastage_pct >= 0 AND wastage_pct < 100),
    CONSTRAINT ck_item_components_window CHECK (valid_to IS NULL OR valid_to > valid_from)
);
COMMENT ON TABLE catalogue.item_components IS 'Components of an assembly/kit/box (Zoho composite items mapped_items). Acyclic (trigger guard_item_component_cycle).';
CREATE UNIQUE INDEX uq_item_components_current ON catalogue.item_components (parent_item_id, component_item_id, role)
    WHERE deleted_at IS NULL AND valid_to IS NULL;
CREATE INDEX ix_item_components_component ON catalogue.item_components (component_item_id) WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.item_sales_channels — where an item is listed.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_sales_channels (
    item_id               bigint        NOT NULL,
    sales_channel_id      bigint        NOT NULL,
    is_listed             boolean       NOT NULL DEFAULT true,
    channel_sku           varchar(100),
    channel_title         text,
    price_override        numeric(18,6),
    price_item_unit_id    bigint,
    valid_from            date          NOT NULL DEFAULT CURRENT_DATE,
    valid_to              date,
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_item_sales_channels PRIMARY KEY (id),
    CONSTRAINT fk_item_sales_channels_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_sales_channels_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_item_sales_channels_channel FOREIGN KEY (tenant_id, organization_id, sales_channel_id)
        REFERENCES catalogue.sales_channels (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_item_sales_channels_price_unit FOREIGN KEY (item_id, price_item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_item_sales_channels_price CHECK (price_override IS NULL OR price_override >= 0),
    CONSTRAINT ck_item_sales_channels_window CHECK (valid_to IS NULL OR valid_to > valid_from)
);
COMMENT ON TABLE catalogue.item_sales_channels IS 'Channel listings of an item; price_override (per price_item_unit_id, NULL = base) sits below a party price list in the quote order.';
CREATE UNIQUE INDEX uq_item_sales_channels_current ON catalogue.item_sales_channels (item_id, sales_channel_id)
    WHERE deleted_at IS NULL AND valid_to IS NULL;
CREATE INDEX ix_item_sales_channels_channel ON catalogue.item_sales_channels (sales_channel_id) WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.item_vendors — who supplies an item (vendor = party.parties, role vendor).
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_vendors (
    item_id                  bigint        NOT NULL,
    vendor_id                bigint        NOT NULL,
    vendor_sku               varchar(100),
    vendor_item_name         text,
    purchase_item_unit_id    bigint,
    lead_time_days           integer,
    min_order_qty            numeric(18,6),
    last_purchase_rate       numeric(18,6),
    last_purchased_on        date,
    is_preferred             boolean       NOT NULL DEFAULT false,
    position                 smallint      NOT NULL DEFAULT 0,
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_item_vendors PRIMARY KEY (id),
    CONSTRAINT fk_item_vendors_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_vendors_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_item_vendors_vendor FOREIGN KEY (tenant_id, organization_id, vendor_id)
        REFERENCES party.parties (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_item_vendors_purchase_unit FOREIGN KEY (item_id, purchase_item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_item_vendors_lead_time CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
    CONSTRAINT ck_item_vendors_qty_rate CHECK (
        (min_order_qty IS NULL OR min_order_qty > 0) AND (last_purchase_rate IS NULL OR last_purchase_rate >= 0))
);
COMMENT ON TABLE catalogue.item_vendors IS 'Suppliers of an item (party role vendor, asserted by the service). Zoho vendor_id = the preferred one.';
CREATE UNIQUE INDEX uq_item_vendors_pair ON catalogue.item_vendors (item_id, vendor_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_item_vendors_preferred ON catalogue.item_vendors (item_id) WHERE deleted_at IS NULL AND is_preferred;
CREATE INDEX ix_item_vendors_vendor ON catalogue.item_vendors (vendor_id) WHERE deleted_at IS NULL;

CREATE OR REPLACE FUNCTION catalogue.guard_item_unit() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_contents_factor numeric(24,6);
    v_base_unit       bigint;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.item_id IS DISTINCT FROM OLD.item_id
           OR NEW.unit_id IS DISTINCT FROM OLD.unit_id
           OR NEW.is_base IS DISTINCT FROM OLD.is_base
           OR NEW.contents_item_unit_id IS DISTINCT FROM OLD.contents_item_unit_id
           OR NEW.contents_qty IS DISTINCT FROM OLD.contents_qty THEN
            RAISE EXCEPTION 'item_units structure is immutable (item_unit %); retire this level and create a new one', OLD.id
                USING ERRCODE = '23514', HINT = 'catalogue_item_unit_immutable';
        END IF;
        NEW.base_factor := OLD.base_factor;
        IF (NEW.valid_to IS NOT NULL AND OLD.valid_to IS NULL) OR (NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL) THEN
            IF EXISTS (SELECT 1 FROM catalogue.item_units c
                        WHERE c.contents_item_unit_id = OLD.id AND c.deleted_at IS NULL AND c.valid_to IS NULL) THEN
                RAISE EXCEPTION 'item_unit % is still contained by a current level; retire the outer level first', OLD.id
                    USING ERRCODE = '23503', HINT = 'catalogue_item_unit_in_use';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.is_base THEN
        SELECT base_unit_id INTO v_base_unit FROM catalogue.items WHERE id = NEW.item_id;
        IF v_base_unit IS DISTINCT FROM NEW.unit_id THEN
            RAISE EXCEPTION 'base level unit % differs from items.base_unit_id %', NEW.unit_id, v_base_unit
                USING ERRCODE = '23514', HINT = 'catalogue_base_unit_mismatch';
        END IF;
        NEW.base_factor := 1;
        RETURN NEW;
    END IF;

    SELECT base_factor INTO v_contents_factor
      FROM catalogue.item_units
     WHERE id = NEW.contents_item_unit_id AND item_id = NEW.item_id
       AND deleted_at IS NULL AND valid_to IS NULL;
    IF v_contents_factor IS NULL THEN
        RAISE EXCEPTION 'contents level % is not a current level of item %', NEW.contents_item_unit_id, NEW.item_id
            USING ERRCODE = '23503', HINT = 'catalogue_contents_not_current';
    END IF;
    NEW.base_factor := NEW.contents_qty * v_contents_factor;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_item_units_guard
    BEFORE INSERT OR UPDATE ON catalogue.item_units
    FOR EACH ROW EXECUTE FUNCTION catalogue.guard_item_unit();


-- ---------------------------------------------------------------------------
-- guard_items_base_unit — items.base_unit_id may change only while no live base level disagrees.
-- The service's "change base unit" flow (allowed only for an item with no stock and no document
-- lines) retires the hierarchy first, changes the unit, then rebuilds the base level.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION catalogue.guard_items_base_unit() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.base_unit_id IS DISTINCT FROM OLD.base_unit_id
       AND EXISTS (SELECT 1 FROM catalogue.item_units u
                    WHERE u.item_id = NEW.id AND u.is_base AND u.deleted_at IS NULL
                      AND u.unit_id IS DISTINCT FROM NEW.base_unit_id) THEN
        RAISE EXCEPTION 'item % has a live base level in another unit; retire the hierarchy first', NEW.id
            USING ERRCODE = '23514', HINT = 'catalogue_base_unit_locked';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_items_base_unit
    BEFORE UPDATE OF base_unit_id ON catalogue.items
    FOR EACH ROW EXECUTE FUNCTION catalogue.guard_items_base_unit();


-- ---------------------------------------------------------------------------
-- guard_item_component_cycle — an item may not (transitively) contain itself.
-- Serialized per organization with a transaction-scoped advisory lock so two concurrent inserts
-- cannot jointly close a cycle.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION catalogue.guard_item_component_cycle() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.deleted_at IS NOT NULL OR NEW.valid_to IS NOT NULL THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('catalogue.item_components:' || NEW.organization_id::text, 0));
    IF EXISTS (
        WITH RECURSIVE descendants(item_id, depth) AS (
            SELECT NEW.component_item_id, 1
            UNION
            SELECT c.component_item_id, d.depth + 1
              FROM catalogue.item_components c
              JOIN descendants d ON c.parent_item_id = d.item_id
             WHERE c.deleted_at IS NULL AND c.valid_to IS NULL AND d.depth < 32
        )
        SELECT 1 FROM descendants WHERE item_id = NEW.parent_item_id
    ) THEN
        RAISE EXCEPTION 'component % would make item % contain itself', NEW.component_item_id, NEW.parent_item_id
            USING ERRCODE = '23514', HINT = 'catalogue_component_cycle';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_item_components_cycle
    BEFORE INSERT OR UPDATE OF component_item_id, parent_item_id, valid_to, deleted_at ON catalogue.item_components
    FOR EACH ROW EXECUTE FUNCTION catalogue.guard_item_component_cycle();


-- ---------------------------------------------------------------------------
-- convert_quantity — pure helper used by reports and the line contract:
--   qty of level A → qty of level B of the same item (via base). NULL when either is not a level
--   of the item. Application code uses the Python twin (catalogue/units.py) inside requests.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION catalogue.convert_quantity(p_qty numeric, p_from_item_unit bigint, p_to_item_unit bigint)
RETURNS numeric LANGUAGE sql STABLE AS $$
    SELECT p_qty * f.base_factor / t.base_factor
      FROM catalogue.item_units f
      JOIN catalogue.item_units t ON t.item_id = f.item_id
     WHERE f.id = p_from_item_unit AND t.id = p_to_item_unit
$$;
"""

_COMMENTS = r"""
COMMENT ON TABLE catalogue.products IS 'Variant template grouping sellable items (Zoho Inventory item group). Optional per item.';
COMMENT ON COLUMN catalogue.products.name IS NULL;
COMMENT ON COLUMN catalogue.products.name_normalized IS NULL;
COMMENT ON COLUMN catalogue.products.slug IS NULL;
COMMENT ON COLUMN catalogue.products.code IS NULL;
COMMENT ON COLUMN catalogue.products.description IS NULL;
COMMENT ON COLUMN catalogue.products.brand_id IS NULL;
COMMENT ON COLUMN catalogue.products.manufacturer_id IS NULL;
COMMENT ON COLUMN catalogue.products.item_group_id IS NULL;
COMMENT ON COLUMN catalogue.products.default_unit_id IS NULL;
COMMENT ON COLUMN catalogue.products.zoho_id IS NULL;
COMMENT ON COLUMN catalogue.products.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.products.id IS NULL;
COMMENT ON COLUMN catalogue.products.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.products.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.products.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.products.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.products.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.products.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.products.status IS NULL;
COMMENT ON COLUMN catalogue.products.is_verified IS NULL;
COMMENT ON COLUMN catalogue.products.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.products.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.products.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.products.created_at IS NULL;
COMMENT ON COLUMN catalogue.products.updated_at IS NULL;
COMMENT ON COLUMN catalogue.products.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.products.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.products.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.product_attributes IS 'The variant axes of a product (Zoho supports three: attribute_name1..3).';
COMMENT ON COLUMN catalogue.product_attributes.product_id IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.attribute_id IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.position IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.product_attributes.id IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.product_attributes.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.product_attributes.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.product_attributes.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.product_attributes.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.product_attributes.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.product_attributes.status IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.is_verified IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.product_attributes.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.product_attributes.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.created_at IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.updated_at IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.product_attributes.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.product_attributes.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.items IS 'The item (SKU) of one organization: what documents and stock movements reference. Zoho crosswalk module `items`. Rates per base unit; stock is never stored here.';
COMMENT ON COLUMN catalogue.items.zoho_id IS 'Echo of Zoho item_id; identity of record is sync.sync_records.';
COMMENT ON COLUMN catalogue.items.sku IS NULL;
COMMENT ON COLUMN catalogue.items.sku_normalized IS NULL;
COMMENT ON COLUMN catalogue.items.code IS NULL;
COMMENT ON COLUMN catalogue.items.name IS NULL;
COMMENT ON COLUMN catalogue.items.name_normalized IS NULL;
COMMENT ON COLUMN catalogue.items.print_name IS 'Name printed on documents when it differs from name (short invoice text).';
COMMENT ON COLUMN catalogue.items.generic_name IS 'Generic / salt composition as printed (e.g. "Paracetamol 500 mg"); searchable, drives substitution lookups.';
COMMENT ON COLUMN catalogue.items.alias_names IS 'Search synonyms and trade aliases ("Crocin" for a paracetamol SKU, local-language names).';
COMMENT ON COLUMN catalogue.items.description IS NULL;
COMMENT ON COLUMN catalogue.items.purchase_description IS NULL;
COMMENT ON COLUMN catalogue.items.source_created_at IS NULL;
COMMENT ON COLUMN catalogue.items.product_id IS NULL;
COMMENT ON COLUMN catalogue.items.item_group_id IS NULL;
COMMENT ON COLUMN catalogue.items.brand_id IS NULL;
COMMENT ON COLUMN catalogue.items.manufacturer_id IS NULL;
COMMENT ON COLUMN catalogue.items.product_type IS 'Zoho product_type (goods / service / digital_service / capital_*): Zoho''s open set, no CHECK.';
COMMENT ON COLUMN catalogue.items.composition IS 'none | assembly (Zoho composite, combo_type=assembly: own stock, built from components) | kit (combo_type=kit: no own stock, components move).';
COMMENT ON COLUMN catalogue.items.can_be_sold IS NULL;
COMMENT ON COLUMN catalogue.items.can_be_purchased IS NULL;
COMMENT ON COLUMN catalogue.items.is_inventory_tracked IS 'Zoho track_inventory. Zoho item_type is derived: inventory if tracked, else sales / purchases / sales_and_purchases from can_be_*.';
COMMENT ON COLUMN catalogue.items.is_returnable IS NULL;
COMMENT ON COLUMN catalogue.items.is_fulfillable IS NULL;
COMMENT ON COLUMN catalogue.items.is_taxable IS NULL;
COMMENT ON COLUMN catalogue.items.track_mode IS 'none | batch | serial | batch_serial. serial is reserved: no serial tables are built yet (plan 04 §8).';
COMMENT ON COLUMN catalogue.items.expiry_tracked IS NULL;
COMMENT ON COLUMN catalogue.items.shelf_life_days IS NULL;
COMMENT ON COLUMN catalogue.items.requires_qc IS NULL;
COMMENT ON COLUMN catalogue.items.valuation_method IS NULL;
COMMENT ON COLUMN catalogue.items.base_unit_id IS 'The stocking unit every quantity resolves to. NULL only for thin Zoho items without a unit; such an item transacts with factor 1 until fixed.';
COMMENT ON COLUMN catalogue.items.zoho_item_unit_id IS 'The pack level Zoho''s single item unit represents (NULL = the base level). Zoho rates/quantities are converted through it on pull and push.';
COMMENT ON COLUMN catalogue.items.hsn_or_sac IS NULL;
COMMENT ON COLUMN catalogue.items.sales_rate IS NULL;
COMMENT ON COLUMN catalogue.items.purchase_rate IS NULL;
COMMENT ON COLUMN catalogue.items.mrp IS 'Maximum retail price per base unit (Zoho label_rate). Batches may carry their own printed MRP.';
COMMENT ON COLUMN catalogue.items.mrp_includes_tax IS NULL;
COMMENT ON COLUMN catalogue.items.reorder_level_base IS NULL;
COMMENT ON COLUMN catalogue.items.minimum_order_qty_base IS NULL;
COMMENT ON COLUMN catalogue.items.maximum_order_qty_base IS NULL;
COMMENT ON COLUMN catalogue.items.net_weight IS NULL;
COMMENT ON COLUMN catalogue.items.gross_weight IS NULL;
COMMENT ON COLUMN catalogue.items.weight_unit_id IS NULL;
COMMENT ON COLUMN catalogue.items.length IS NULL;
COMMENT ON COLUMN catalogue.items.width IS NULL;
COMMENT ON COLUMN catalogue.items.height IS NULL;
COMMENT ON COLUMN catalogue.items.dimension_unit_id IS NULL;
COMMENT ON COLUMN catalogue.items.storage_condition IS NULL;
COMMENT ON COLUMN catalogue.items.storage_temp_min_c IS NULL;
COMMENT ON COLUMN catalogue.items.storage_temp_max_c IS NULL;
COMMENT ON COLUMN catalogue.items.country_of_origin IS NULL;
COMMENT ON COLUMN catalogue.items.drug_schedule IS 'Drugs and Cosmetics Rules schedule (H, H1, X, G…); verify vocabulary with the compliance owner.';
COMMENT ON COLUMN catalogue.items.requires_prescription IS NULL;
COMMENT ON COLUMN catalogue.items.internal_notes IS NULL;
COMMENT ON COLUMN catalogue.items.position IS NULL;
COMMENT ON COLUMN catalogue.items.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.items.id IS NULL;
COMMENT ON COLUMN catalogue.items.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.items.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.items.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.items.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.items.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.items.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.items.status IS NULL;
COMMENT ON COLUMN catalogue.items.is_verified IS NULL;
COMMENT ON COLUMN catalogue.items.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.items.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.items.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.items.created_at IS NULL;
COMMENT ON COLUMN catalogue.items.updated_at IS NULL;
COMMENT ON COLUMN catalogue.items.deactivation_date IS NULL;
COMMENT ON COLUMN catalogue.items.deactivation_reason IS NULL;
COMMENT ON COLUMN catalogue.items.deactivated_by IS 'users.id who deactivated it';
COMMENT ON COLUMN catalogue.items.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.items.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.items.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_merchandising IS '1:1 storefront/SEO content of an item; locally owned, never written by the Zoho sync.';
COMMENT ON COLUMN catalogue.item_merchandising.item_id IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.display_name IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.tagline IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.slug IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.short_description IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.long_description IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.is_featured IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.seo_title IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.seo_description IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.seo_keywords IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.specifications IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.specification_set_ref IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.is_visible IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.show_in_menu IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.menu_position IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_merchandising.id IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_merchandising.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_merchandising.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_merchandising.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_merchandising.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_merchandising.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_merchandising.status IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_merchandising.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_merchandising.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_merchandising.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_merchandising.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_attribute_values IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.item_id IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.attribute_id IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.attribute_option_id IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_attribute_values.id IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_attribute_values.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_attribute_values.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_attribute_values.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_attribute_values.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_attribute_values.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_attribute_values.status IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_attribute_values.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_attribute_values.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_attribute_values.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_attribute_values.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_units IS 'Per-item packaging hierarchy (alternate UoM): each level contains N of another level of the same item; base_factor cached. Structure immutable; changes retire and replace.';
COMMENT ON COLUMN catalogue.item_units.item_id IS NULL;
COMMENT ON COLUMN catalogue.item_units.unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_units.is_base IS NULL;
COMMENT ON COLUMN catalogue.item_units.contents_item_unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_units.contents_qty IS '1 of this level = contents_qty of contents_item_unit_id. Immutable.';
COMMENT ON COLUMN catalogue.item_units.base_factor IS '1 of this level = base_factor base units. Trigger-maintained; documents snapshot it.';
COMMENT ON COLUMN catalogue.item_units.label IS NULL;
COMMENT ON COLUMN catalogue.item_units.packaging_type_id IS NULL;
COMMENT ON COLUMN catalogue.item_units.is_sellable IS NULL;
COMMENT ON COLUMN catalogue.item_units.is_purchasable IS NULL;
COMMENT ON COLUMN catalogue.item_units.is_default_sales IS NULL;
COMMENT ON COLUMN catalogue.item_units.is_default_purchase IS NULL;
COMMENT ON COLUMN catalogue.item_units.allow_break IS 'May a sealed pack of this level be opened to sell its contents loose (regulated SKUs: false).';
COMMENT ON COLUMN catalogue.item_units.min_order_qty IS NULL;
COMMENT ON COLUMN catalogue.item_units.order_multiple IS NULL;
COMMENT ON COLUMN catalogue.item_units.sales_rate IS NULL;
COMMENT ON COLUMN catalogue.item_units.purchase_rate IS NULL;
COMMENT ON COLUMN catalogue.item_units.mrp IS NULL;
COMMENT ON COLUMN catalogue.item_units.derive_price IS 'false (default, the AUoM rule): a non-base level is sellable only with an explicit price (price list entry or sales_rate) — never silently prorated. true: fall back to items.sales_rate x base_factor. Ignored on the base level.';
COMMENT ON COLUMN catalogue.item_units.gross_weight IS NULL;
COMMENT ON COLUMN catalogue.item_units.weight_unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_units.length IS NULL;
COMMENT ON COLUMN catalogue.item_units.width IS NULL;
COMMENT ON COLUMN catalogue.item_units.height IS NULL;
COMMENT ON COLUMN catalogue.item_units.dimension_unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_units.special_instructions IS NULL;
COMMENT ON COLUMN catalogue.item_units.valid_from IS NULL;
COMMENT ON COLUMN catalogue.item_units.valid_to IS NULL;
COMMENT ON COLUMN catalogue.item_units.position IS NULL;
COMMENT ON COLUMN catalogue.item_units.zoho_id IS 'Reserved for a Zoho unit-conversion id if probe P0.9 finds one; Zoho knows only the base unit today.';
COMMENT ON COLUMN catalogue.item_units.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_units.id IS NULL;
COMMENT ON COLUMN catalogue.item_units.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_units.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_units.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_units.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_units.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_units.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_units.status IS NULL;
COMMENT ON COLUMN catalogue.item_units.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_units.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_units.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_units.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_units.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_units.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_units.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_units.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_units.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_identifiers IS 'Barcodes/codes of an item, optionally per pack level (item_unit_id NULL = the base unit). Zoho upc/ean/isbn/part_number land here.';
COMMENT ON COLUMN catalogue.item_identifiers.item_id IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.item_unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.kind IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.value IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.value_normalized IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.is_primary IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.source IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_identifiers.id IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_identifiers.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_identifiers.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_identifiers.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_identifiers.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_identifiers.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_identifiers.status IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_identifiers.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_identifiers.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_identifiers.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_identifiers.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_components IS 'Components of an assembly/kit/box (Zoho composite items mapped_items). Acyclic (trigger guard_item_component_cycle).';
COMMENT ON COLUMN catalogue.item_components.parent_item_id IS NULL;
COMMENT ON COLUMN catalogue.item_components.component_item_id IS NULL;
COMMENT ON COLUMN catalogue.item_components.component_item_unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_components.role IS NULL;
COMMENT ON COLUMN catalogue.item_components.quantity IS NULL;
COMMENT ON COLUMN catalogue.item_components.wastage_pct IS NULL;
COMMENT ON COLUMN catalogue.item_components.substitute_group IS NULL;
COMMENT ON COLUMN catalogue.item_components.is_optional IS NULL;
COMMENT ON COLUMN catalogue.item_components.position IS NULL;
COMMENT ON COLUMN catalogue.item_components.valid_from IS NULL;
COMMENT ON COLUMN catalogue.item_components.valid_to IS NULL;
COMMENT ON COLUMN catalogue.item_components.zoho_id IS NULL;
COMMENT ON COLUMN catalogue.item_components.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_components.id IS NULL;
COMMENT ON COLUMN catalogue.item_components.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_components.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_components.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_components.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_components.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_components.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_components.status IS NULL;
COMMENT ON COLUMN catalogue.item_components.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_components.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_components.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_components.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_components.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_components.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_components.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_components.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_components.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_sales_channels IS 'Channel listings of an item; price_override (per price_item_unit_id, NULL = base) sits below a party price list in the quote order.';
COMMENT ON COLUMN catalogue.item_sales_channels.item_id IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.sales_channel_id IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.is_listed IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.channel_sku IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.channel_title IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.price_override IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.price_item_unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.valid_from IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.valid_to IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_sales_channels.id IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_sales_channels.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_sales_channels.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_sales_channels.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_sales_channels.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_sales_channels.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_sales_channels.status IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_sales_channels.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_sales_channels.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_sales_channels.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_sales_channels.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_vendors IS 'Suppliers of an item (party role vendor, asserted by the service). Zoho vendor_id = the preferred one.';
COMMENT ON COLUMN catalogue.item_vendors.item_id IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.vendor_id IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.vendor_sku IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.vendor_item_name IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.purchase_item_unit_id IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.lead_time_days IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.min_order_qty IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.last_purchase_rate IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.last_purchased_on IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.is_preferred IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.position IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_vendors.id IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_vendors.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_vendors.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_vendors.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_vendors.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_vendors.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_vendors.status IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_vendors.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_vendors.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_vendors.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_vendors.deleted_reason IS 'Why it was deleted';
"""

_TABLES = ('products', 'product_attributes', 'items', 'item_merchandising', 'item_attribute_values', 'item_units', 'item_identifiers', 'item_components', 'item_sales_channels', 'item_vendors')


def _statements(script: str) -> list[str]:
    """Split on ``;`` at line ends, never inside a ``$$`` body; drop comment-only chunks."""
    out, buf, in_body = [], [], False
    for line in script.splitlines():
        buf.append(line)
        if line.count("$$") % 2 == 1:
            in_body = not in_body
        if not in_body and line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            buf = []
            body = "\n".join(x for x in stmt.splitlines() if not x.strip().startswith("--")).strip()
            if body:
                out.append(stmt.rstrip(";"))
    tail = "\n".join(x for x in buf if not x.strip().startswith("--")).strip()
    if tail:
        out.append(tail.rstrip(";"))
    return out


def upgrade() -> None:
    for statement in _statements(_DDL) + _statements(_COMMENTS):
        op.execute(statement)
    for table in _TABLES:
        op.execute(f"CREATE UNIQUE INDEX ix_catalogue_{table}_uuid ON catalogue.{table} (uuid)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_deleted_at ON catalogue.{table} (deleted_at)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_status ON catalogue.{table} (status)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_tenant_id ON catalogue.{table} (tenant_id)")
        op.execute(f"CREATE INDEX ix_{table}_tenant_org ON catalogue.{table} (tenant_id, organization_id)")

    # Gallery collections (item images) need an order; single-image collections (avatar) keep 0.
    op.add_column("items", sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False,
                                     comment="Order inside a gallery collection (0 for single-image collections)"),
                  schema="media")

    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO core.entity_types (code, name, target_schema, target_table, description, created_by_name) VALUES "
        "('item', 'Item', 'catalogue', 'items', 'An item (SKU) of the catalogue.', 'system:migration'), "
        "('product', 'Product', 'catalogue', 'products', 'A variant template grouping items.', 'system:migration') "
        "ON CONFLICT (code) DO NOTHING"))
    from app.modules.accounting.registration import register_account_owner_type
    from app.modules.comments.registration import register_commentable_entity_type
    from app.modules.taxes.registration import register_taxable_entity_type

    register_taxable_entity_type(
        bind, code="item", name="Item", target_schema="catalogue", target_table="items",
        allows_multiple=False, allows_exemption=True,
        description="Item GST preferences (Zoho item_tax_preferences / tax_exemption_id).",
    )
    register_account_owner_type(
        bind, code="item", name="Item", target_schema="catalogue", target_table="items",
        purposes={"sales": True, "purchase": True, "inventory_asset": True},
        description="Zoho item account_id / purchase_account_id / inventory_account_id.",
    )
    register_commentable_entity_type(bind, code="item", name="Item", target_schema="catalogue",
                                     target_table="items", description="Notes on an item.")
    register_commentable_entity_type(bind, code="product", name="Product", target_schema="catalogue",
                                     target_table="products", description="Notes on a product.")

    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for statement in (
        "DELETE FROM comments.commentable_entity_types WHERE entity_type_code IN ('item', 'product')",
        "DELETE FROM accounting.account_purpose_policies WHERE entity_type_code = 'item'",
        "DELETE FROM tax.taxable_entity_types WHERE entity_type_code = 'item'",
    ):
        bind.execute(sa.text(statement))
    op.drop_column("items", "position", schema="media")
    op.execute("ALTER TABLE catalogue.items DROP CONSTRAINT IF EXISTS fk_items_zoho_item_unit")
    for table in ("item_vendors", "item_sales_channels", "item_components", "item_identifiers",
                  "item_attribute_values", "item_merchandising", "item_units", "items", "product_attributes",
                  "products"):
        op.execute(f"DROP TABLE IF EXISTS catalogue.{table}")
    for function in ("guard_item_unit()", "guard_items_base_unit()", "guard_item_component_cycle()",
                     "convert_quantity(numeric, bigint, bigint)"):
        op.execute(f"DROP FUNCTION IF EXISTS catalogue.{function}")
    for statement in (
        "DELETE FROM extfields.field_values WHERE owner_type_code IN ('item', 'product')",
        "DELETE FROM extfields.field_definitions WHERE owner_type_code IN ('item', 'product')",
        "DELETE FROM core.entity_types WHERE code IN ('item', 'product')",
    ):
        bind.execute(sa.text(statement))
