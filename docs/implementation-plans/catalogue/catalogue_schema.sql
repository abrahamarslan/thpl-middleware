-- ============================================================================
-- Catalogue · Batches · Inventory · Pack pricing & Offers — target schema
-- PostgreSQL 18 (native uuidv7()), th-middleware conventions
-- ============================================================================
--
-- Companion to docs/implementation-plans/catalogue/README.md (read §2 "Decisions" first).
--
-- WHAT THIS FILE IS
--   The design source of truth for the tables the catalogue programme adds. It is written so it RUNS
--   on a migrated th-middleware database (after migration 5b8d2e71c4a9), but the production path is
--   SQLAlchemy models + hand-checked Alembic migrations per build phase (plan 08-build-plan.md). Each
--   phase's migration must produce exactly the DDL below for its tables; tests/test_catalogue_schema.py
--   holds the column ledger.
--
-- SCHEMAS
--   catalogue   item master data: units, packaging, item groups, products (variant templates),
--               items (the SKU), packaging hierarchy, identifiers, components, channel listings,
--               vendors, batches (lot master) and batch holds.
--   inventory   where stock is and how it moved: storage locations, stock movements, the
--               append-only stock ledger, balances, reservations, stock policies, Zoho stock
--               snapshots.
--   pricing     (exists: price lists) + pack-level prices on price-list items + offers (schemes).
--   core/geo    small additive changes (manufacturer zoho_id, FSSAI importer licence kind,
--               places scope key) — §8.
--
-- HOUSE CONVENTIONS (do not "fix")
--   * Every operational table is OrgEntityMixin + SoftDeleteFilteredMixin: the "standard block"
--     columns below, written out in full per table. tenant_id + organization_id NOT NULL, composite
--     FK to org_management.organizations(tenant_id, id). Children pin their parent's tenant AND
--     organization with composite FKs to the parent's (tenant_id, organization_id, id) unique key.
--   * Column names follow the mixins: created_by (not created_by_id), deleted_by, deleted_reason,
--     row_version, app_version, app_metadata. Never a column attribute named `metadata`.
--   * Uniqueness on soft-deletable tables is ALWAYS a partial unique index (deleted_at IS NULL).
--   * Vocabularies WE own: text + CHECK. Vocabularies Zoho owns: text, no CHECK (validated in the
--     service for local writes only).
--   * Zoho identity of record = sync.sync_records (crosswalk). Tables carry only a `zoho_id` echo.
--   * Money numeric(18,6); quantities numeric(18,6); conversion factors numeric(24,6).
--   * The mixin-generated indexes (ix_<schema>_<table>_uuid UNIQUE, _deleted_at, _status,
--     _tenant_id, ix_<table>_tenant_org) are created for every table by the DO block in §9, with
--     the exact names Alembic autogenerate emits.
--   * pg_partman is deliberately NOT used (zoho/control/retention.py, fieldops/partitions.py):
--     the ledger's monthly partitions are app-managed (§7.4).
-- ============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS catalogue;
CREATE SCHEMA IF NOT EXISTS inventory;
CREATE SCHEMA IF NOT EXISTS pricing;      -- exists since 02b470ed2792
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- already installed on the house image


-- ============================================================================
-- §1. GLOBAL reference: GST Unit Quantity Codes
-- ============================================================================
-- GLOBAL table (no tenant): the GSTN-prescribed UQC list is national law, not one tenant's data.
-- Needs a reasoned entry in tests/test_tenancy.py GLOBAL_TABLES. Seeded in §10; never edited
-- through the API (a new code is a migration).

CREATE TABLE catalogue.uqc_codes (
    code          varchar(3)   NOT NULL,
    description   text         NOT NULL,
    quantity_kind varchar(16)  NOT NULL,
    is_active     boolean      NOT NULL DEFAULT true,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_uqc_codes PRIMARY KEY (code),
    CONSTRAINT ck_uqc_codes_code CHECK (code ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_uqc_codes_quantity_kind
        CHECK (quantity_kind IN ('count','mass','volume','length','area','other'))
);
COMMENT ON TABLE catalogue.uqc_codes IS
    'GLOBAL: GST Unit Quantity Codes (GSTN list). Snapshotted on every invoice line for GSTR-1 HSN summaries and e-invoices.';


-- ============================================================================
-- §2. Catalogue masters (organization-scoped)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- catalogue.units — ONE table for every unit: trade/count units (PCS, BOX, CTN, BTL) AND physical
-- measure units (g, kg, ml, l, cm, in). `unit_class` is the "type" the request asked for.
-- Zoho units (unit_id, unit, name, uqc) land here; Zoho's item `weight_unit` / `dimension_unit`
-- strings resolve to rows of class mass / length by code.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.units (
    code              varchar(32)  NOT NULL,
    code_normalized   varchar(32)  GENERATED ALWAYS AS (lower(btrim(code))) STORED,
    name              text         NOT NULL,
    plural_name       text,
    unit_class        varchar(16)  NOT NULL,
    uqc_code          varchar(3),
    decimal_places    smallint     NOT NULL DEFAULT 0,
    si_factor         numeric(24,12),
    is_system         boolean      NOT NULL DEFAULT false,
    zoho_id           varchar(50),
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
    CONSTRAINT pk_units PRIMARY KEY (id),
    CONSTRAINT uq_units_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_units_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_units_uqc FOREIGN KEY (uqc_code) REFERENCES catalogue.uqc_codes (code) ON DELETE RESTRICT,
    CONSTRAINT ck_units_code_not_blank CHECK (btrim(code) <> ''),
    CONSTRAINT ck_units_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_units_class CHECK (unit_class IN ('count','mass','volume','length','area','time','other')),
    CONSTRAINT ck_units_decimal_places CHECK (decimal_places BETWEEN 0 AND 6),
    -- si_factor converts to the class base (mass: g, volume: ml, length: mm, area: mm2, time: s).
    -- Count units have none: a "box" has no universal size — that is what item_units is for.
    CONSTRAINT ck_units_si_factor CHECK (
        (unit_class IN ('count','other') AND si_factor IS NULL)
        OR (unit_class NOT IN ('count','other') AND (si_factor IS NULL OR si_factor > 0))),
    CONSTRAINT ck_units_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.units IS
    'Units of measure of one organization: count/trade units and physical measure units (unit_class). Zoho crosswalk module `units`.';
COMMENT ON COLUMN catalogue.units.si_factor IS 'Multiplier to the class base unit (g / ml / mm / mm2 / s); NULL for count units.';
COMMENT ON COLUMN catalogue.units.uqc_code IS 'GST UQC this unit reports as (e.g. BTL, PCS, MLT). NULL = OTH at filing time.';
COMMENT ON COLUMN catalogue.units.zoho_id IS 'Echo of Zoho unit_id; identity of record is sync.sync_records.';
CREATE UNIQUE INDEX uq_units_scope_code ON catalogue.units (tenant_id, organization_id, code_normalized)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_units_zoho_id ON catalogue.units (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
CREATE INDEX ix_units_class ON catalogue.units (organization_id, unit_class) WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.packaging_types — physical packaging characteristics (EACH, MONOCARTON, INNER_BOX,
-- SHIPPER_CASE, DANGLER…). Describes the PACKAGING, not the quantity: "how many" lives on
-- item_units, per item.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.packaging_types (
    code                   varchar(40)   NOT NULL,
    name                   text          NOT NULL,
    description            text,
    is_container           boolean       NOT NULL DEFAULT false,
    is_dangler             boolean       NOT NULL DEFAULT false,
    is_display_unit        boolean       NOT NULL DEFAULT false,
    is_stackable           boolean       NOT NULL DEFAULT false,
    stack_limit            integer,
    handling_instructions  text,
    storage_requirements   text,
    standard_weight        numeric(18,6),
    weight_unit_id         bigint,
    standard_length        numeric(18,6),
    standard_width         numeric(18,6),
    standard_height        numeric(18,6),
    dimension_unit_id      bigint,
    icon                   varchar(64),
    properties             jsonb,
    valid_from             date,
    valid_to               date,
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
    CONSTRAINT pk_packaging_types PRIMARY KEY (id),
    CONSTRAINT uq_packaging_types_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_packaging_types_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_packaging_types_weight_unit FOREIGN KEY (tenant_id, organization_id, weight_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_packaging_types_dimension_unit FOREIGN KEY (tenant_id, organization_id, dimension_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_packaging_types_code CHECK (code ~ '^[A-Z0-9_]+$'),
    CONSTRAINT ck_packaging_types_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_packaging_types_stack_limit CHECK (stack_limit IS NULL OR stack_limit > 0),
    CONSTRAINT ck_packaging_types_measures CHECK (
        (standard_weight IS NULL OR standard_weight >= 0) AND (standard_length IS NULL OR standard_length >= 0)
        AND (standard_width IS NULL OR standard_width >= 0) AND (standard_height IS NULL OR standard_height >= 0)),
    CONSTRAINT ck_packaging_types_window CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_packaging_types_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.packaging_types IS 'Packaging characteristics (carton, monocarton, shipper case, dangler). Quantities live on catalogue.item_units.';
COMMENT ON COLUMN catalogue.packaging_types.properties IS 'Free-form material facts (board_gsm, flute, recyclable). The pasted metadata_ column; renamed to avoid the SQLAlchemy `metadata` trap.';
CREATE UNIQUE INDEX uq_packaging_types_scope_code ON catalogue.packaging_types (tenant_id, organization_id, code)
    WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.sales_channels — route-to-market vocabulary (general trade storefront, distributor,
-- modern trade, e-commerce…). `zoho_code` maps Zoho's contact `sales_channel` string
-- (party.parties.sales_channel, e.g. 'direct_sales') so offers can target a channel.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.sales_channels (
    code           varchar(40)  NOT NULL,
    name           text         NOT NULL,
    description    text,
    channel_kind   varchar(24),
    zoho_code      varchar(32),
    position       smallint     NOT NULL DEFAULT 0,
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
    CONSTRAINT pk_sales_channels PRIMARY KEY (id),
    CONSTRAINT uq_sales_channels_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_sales_channels_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT ck_sales_channels_code CHECK (code ~ '^[A-Z0-9_]+$'),
    CONSTRAINT ck_sales_channels_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_sales_channels_kind CHECK (channel_kind IS NULL OR channel_kind IN
        ('general_trade','modern_trade','distributor','ecommerce','institutional','direct','other')),
    CONSTRAINT ck_sales_channels_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.sales_channels IS 'Sales channels (route to market). Local master; zoho_code maps the Zoho contact sales_channel string.';
CREATE UNIQUE INDEX uq_sales_channels_scope_code ON catalogue.sales_channels (tenant_id, organization_id, code)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_sales_channels_zoho_code ON catalogue.sales_channels (tenant_id, organization_id, zoho_code)
    WHERE deleted_at IS NULL AND zoho_code IS NOT NULL;


-- ---------------------------------------------------------------------------
-- catalogue.item_groups — MERCHANDISING groups (Oral Care, Men's Grooming): menus, catalogues,
-- reporting lines, offer targets. Not the category taxonomy (core.categories, Zoho-fed) and NOT
-- Zoho's "item groups" (variant templates → catalogue.products). Optional one-level-or-deeper tree.
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.item_groups (
    code             varchar(40)  NOT NULL,
    name             text         NOT NULL,
    description      text,
    parent_id        bigint,
    is_visible       boolean      NOT NULL DEFAULT true,
    show_in_menu     boolean      NOT NULL DEFAULT true,
    display_order    integer      NOT NULL DEFAULT 0,
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
    CONSTRAINT pk_item_groups PRIMARY KEY (id),
    CONSTRAINT uq_item_groups_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_item_groups_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_item_groups_parent FOREIGN KEY (tenant_id, organization_id, parent_id)
        REFERENCES catalogue.item_groups (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_item_groups_code CHECK (code ~ '^[A-Z0-9_]+$'),
    CONSTRAINT ck_item_groups_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_item_groups_no_self_parent CHECK (parent_id IS NULL OR parent_id <> id),
    CONSTRAINT ck_item_groups_display_order CHECK (display_order >= 0),
    CONSTRAINT ck_item_groups_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.item_groups IS 'Merchandising groups (menus, catalogues, offer targets). Distinct from core.categories and from Zoho item groups (= catalogue.products).';
CREATE UNIQUE INDEX uq_item_groups_scope_code ON catalogue.item_groups (tenant_id, organization_id, code)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_item_groups_parent ON catalogue.item_groups (parent_id) WHERE parent_id IS NOT NULL AND deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.attributes / attribute_options — variant axes (Volume, Pack size, Flavour, Shade).
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.attributes (
    code           varchar(40)  NOT NULL,
    name           text         NOT NULL,
    input_type     varchar(16)  NOT NULL DEFAULT 'select',
    unit_id        bigint,
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
    CONSTRAINT pk_attributes PRIMARY KEY (id),
    CONSTRAINT uq_attributes_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_attributes_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_attributes_unit FOREIGN KEY (tenant_id, organization_id, unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_attributes_code CHECK (code ~ '^[a-z0-9_]+$'),
    CONSTRAINT ck_attributes_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_attributes_input_type CHECK (input_type IN ('select','swatch','number','text')),
    CONSTRAINT ck_attributes_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.attributes IS 'Variant axes (volume, pack size, flavour). Values in attribute_options.';
CREATE UNIQUE INDEX uq_attributes_scope_code ON catalogue.attributes (tenant_id, organization_id, code)
    WHERE deleted_at IS NULL;

CREATE TABLE catalogue.attribute_options (
    attribute_id      bigint       NOT NULL,
    value             text         NOT NULL,
    value_normalized  text         GENERATED ALWAYS AS (lower(btrim(value))) STORED,
    numeric_value     numeric(18,6),
    swatch            varchar(32),
    position          smallint     NOT NULL DEFAULT 0,
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
    CONSTRAINT pk_attribute_options PRIMARY KEY (id),
    CONSTRAINT uq_attribute_options_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_attribute_options_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_attribute_options_attribute FOREIGN KEY (tenant_id, organization_id, attribute_id)
        REFERENCES catalogue.attributes (tenant_id, organization_id, id) ON DELETE CASCADE,
    -- target of the (attribute_id, option_id) composite FK on item_attribute_values: an item can
    -- never carry a "Volume" axis with a "Flavour" option.
    CONSTRAINT uq_attribute_options_attribute_id UNIQUE (attribute_id, id),
    CONSTRAINT ck_attribute_options_value_not_blank CHECK (btrim(value) <> ''),
    CONSTRAINT ck_attribute_options_status CHECK (status IN ('active','inactive'))
);
CREATE UNIQUE INDEX uq_attribute_options_value ON catalogue.attribute_options (attribute_id, value_normalized)
    WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- catalogue.products — the variant TEMPLATE ("Dabur Almond Hair Oil") whose items are the sellable
-- SKUs (50 ml, 95 ml, 200 ml). Optional: a stand-alone item has product_id NULL. Zoho Inventory's
-- "item group" (/itemgroups, attribute_name1..3) maps HERE — the Zoho spelling stays on the Zoho
-- side of the field map (naming rule from the price-lists module).
-- ---------------------------------------------------------------------------
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


-- ============================================================================
-- §3. Items — the SKU every estimate, invoice, credit note, sales return and stock movement names
-- ============================================================================
-- One row = one Zoho item (crosswalk module `items`). Rates are per BASE unit. Stock is never a
-- column here (inventory.stock_balances is the cache, inventory.stock_ledger_entries the truth;
-- Zoho's stock figures are snapshots in inventory.external_stock_levels).
-- Opt-in polymorphic capabilities (registered in §11): taxes (tax.tax_assignments — GST intra/
-- inter, exemptions), accounts (sales / purchase / inventory_asset), categories, documents, media
-- (gallery), comments, custom fields, tags.
-- ---------------------------------------------------------------------------
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


-- ============================================================================
-- §4. Batches — the lot master (identity of a lot of an item)
-- ============================================================================
-- The audited `wms.batches` (92 columns) is replaced by a SLIM identity row. What it owned
-- elsewhere now lives where it belongs:
--   quantities           → inventory.stock_ledger_entries (truth) / stock_balances (cache)
--   quarantine/approval  → catalogue.batch_holds (effective-dated) + batches.qc_status
--   CoA / compliance docs→ documents.document_links (HasDocumentsMixin, roles coa / compliance)
--   custom fields        → extfields (HasCustomFieldsMixin; Zoho batch_custom_fields)
--   containers           → deferred handling units (plan 04 §8)
--   schemes              → pricing.scheme_targets (target_type 'batch')
--   temperature logs     → deferred (no sensor feed exists)
--   Zoho ids / sync state→ sync.sync_records (crosswalk module `batches`) + zoho_id echo
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.batches (
    item_id                     bigint        NOT NULL,
    batch_number                varchar(100)  NOT NULL,
    batch_number_normalized     varchar(100)  GENERATED ALWAYS AS (upper(regexp_replace(batch_number, '\s+', '', 'g'))) STORED,
    manufacturer_batch_number   varchar(100),
    supplier_batch_number       varchar(100),
    manufactured_on             date,
    expires_on                  date,
    expiry_precision            varchar(8)    NOT NULL DEFAULT 'day',
    -- the LAST day the lot is in date: end of month for "EXP 03/2027" packs
    effective_expires_on        date          GENERATED ALWAYS AS (
                                    CASE WHEN expiry_precision = 'month' AND expires_on IS NOT NULL
                                         THEN (date_trunc('month', expires_on::timestamp) + interval '1 month' - interval '1 day')::date
                                         ELSE expires_on END) STORED,
    best_before_on              date,
    manufacturer_id             bigint,
    supplier_id                 bigint,
    mrp                         numeric(18,6),
    sales_rate                  numeric(18,6),
    qc_status                   varchar(16)   NOT NULL DEFAULT 'not_required',
    qc_decided_at               timestamptz,
    qc_decided_by               bigint,
    country_of_origin           char(2),
    first_received_on           date,
    notes                       text,
    zoho_id                     varchar(50),
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
    CONSTRAINT pk_batches PRIMARY KEY (id),
    CONSTRAINT uq_batches_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_batches_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- target of (item_id, batch_id) composite FKs: a ledger row can never pair an item with
    -- another item's batch
    CONSTRAINT uq_batches_item_id UNIQUE (item_id, id),
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_batches_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_batches_manufacturer FOREIGN KEY (tenant_id, organization_id, manufacturer_id)
        REFERENCES core.manufacturers (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_batches_supplier FOREIGN KEY (tenant_id, organization_id, supplier_id)
        REFERENCES party.parties (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_batches_number_not_blank CHECK (btrim(batch_number) <> ''),
    CONSTRAINT ck_batches_expiry_after_manufacture CHECK (expires_on IS NULL OR manufactured_on IS NULL OR expires_on >= manufactured_on),
    CONSTRAINT ck_batches_expiry_precision CHECK (expiry_precision IN ('day','month')),
    CONSTRAINT ck_batches_best_before CHECK (best_before_on IS NULL OR manufactured_on IS NULL OR best_before_on >= manufactured_on),
    CONSTRAINT ck_batches_rates CHECK ((mrp IS NULL OR mrp >= 0) AND (sales_rate IS NULL OR sales_rate >= 0)),
    CONSTRAINT ck_batches_qc_status CHECK (qc_status IN ('not_required','pending','passed','failed')),
    CONSTRAINT ck_batches_qc_decided CHECK (qc_status IN ('not_required','pending') OR qc_decided_at IS NOT NULL),
    CONSTRAINT ck_batches_country CHECK (country_of_origin IS NULL OR country_of_origin ~ '^[A-Z]{2}$'),
    CONSTRAINT ck_batches_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE catalogue.batches IS
    'Lot master: one lot of one item. Quantities are never stored here (inventory ledger/balances). Zoho crosswalk module `batches` (Inventory /items/batches).';
COMMENT ON COLUMN catalogue.batches.batch_number IS 'The lot number printed on the pack, exactly as received. Zoho batch_number.';
COMMENT ON COLUMN catalogue.batches.manufactured_on IS 'Zoho manufactured_date. The audited input had both manufacturer_date and manufactured_date: one business fact, one column.';
COMMENT ON COLUMN catalogue.batches.mrp IS 'MRP printed on this lot (Zoho label_rate). Overrides items.mrp for this lot.';
COMMENT ON COLUMN catalogue.batches.status IS 'Zoho active/inactive. Holds (quarantine, recall) are catalogue.batch_holds; exhaustion is a balance fact, not a status.';
CREATE UNIQUE INDEX uq_batches_item_number ON catalogue.batches (item_id, batch_number_normalized) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_batches_zoho_id ON catalogue.batches (tenant_id, zoho_id) WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
COMMENT ON COLUMN catalogue.batches.expiry_precision IS 'day: expires_on is exact. month: the pack prints month/year; effective_expires_on is the month''s last day.';
COMMENT ON COLUMN catalogue.batches.effective_expires_on IS 'STORED: the last day the lot is in date. Every expiry rule, view and report reads this, never expires_on.';
CREATE INDEX ix_batches_expiry ON catalogue.batches (organization_id, effective_expires_on)
    WHERE deleted_at IS NULL AND effective_expires_on IS NOT NULL;
CREATE INDEX ix_batches_number_trgm ON catalogue.batches USING gin (batch_number_normalized gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX ix_batches_supplier ON catalogue.batches (supplier_id) WHERE deleted_at IS NULL AND supplier_id IS NOT NULL;


-- ---------------------------------------------------------------------------
-- catalogue.batch_holds — effective-dated holds on a lot (quarantine, QC, regulatory, recall,
-- complaint). A lot is BLOCKED for allocation while it has any open hold. History is the rows:
-- "was it quarantined last Tuesday?" = a range query. One open hold per (batch, type).
-- ---------------------------------------------------------------------------
CREATE TABLE catalogue.batch_holds (
    batch_id          bigint        NOT NULL,
    hold_type         varchar(24)   NOT NULL,
    reason_code_id    bigint,
    reason            text,
    placed_at         timestamptz   NOT NULL DEFAULT now(),
    placed_by         bigint,
    placed_by_name    varchar(255),
    released_at       timestamptz,
    released_by       bigint,
    released_by_name  varchar(255),
    release_note      text,
    external_ref      text,
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
    CONSTRAINT pk_batch_holds PRIMARY KEY (id),
    CONSTRAINT fk_batch_holds_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_batch_holds_batch FOREIGN KEY (tenant_id, organization_id, batch_id)
        REFERENCES catalogue.batches (tenant_id, organization_id, id) ON DELETE CASCADE,
    -- reason_code_id → inventory.reason_codes is added in §7 (table created there)
    CONSTRAINT ck_batch_holds_type CHECK (hold_type IN ('quarantine','qc','regulatory','recall','customer_complaint','other')),
    CONSTRAINT ck_batch_holds_window CHECK (released_at IS NULL OR released_at >= placed_at),
    CONSTRAINT ck_batch_holds_status CHECK (status IN ('active','released'))
);
COMMENT ON TABLE catalogue.batch_holds IS 'Effective-dated holds on a lot; any open hold blocks allocation. Released holds stay as history (never deleted).';
CREATE UNIQUE INDEX uq_batch_holds_open ON catalogue.batch_holds (batch_id, hold_type)
    WHERE deleted_at IS NULL AND released_at IS NULL;
CREATE INDEX ix_batch_holds_batch_time ON catalogue.batch_holds (batch_id, placed_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_batch_holds_open ON catalogue.batch_holds (organization_id, hold_type)
    WHERE deleted_at IS NULL AND released_at IS NULL;


-- ============================================================================
-- §5. Catalogue integrity functions & triggers
-- ============================================================================

-- ---------------------------------------------------------------------------
-- guard_item_unit — maintains base_factor and the hierarchy's invariants.
--   INSERT: base level ⇒ factor 1 and unit = items.base_unit_id; other levels ⇒
--           factor = contents_qty × contents.base_factor, contents must be live and current.
--   UPDATE: the structure (unit_id, is_base, contents_item_unit_id, contents_qty, item_id) is
--           immutable; retiring a level (valid_to / deleted_at) is refused while a current level
--           still contains it.
-- ---------------------------------------------------------------------------
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


-- ============================================================================
-- §6. Pricing — pack-level prices on price lists, and offers (schemes)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- §6.1 pricing.price_list_items gains a real item FK and an optional pack level.
--   * item_id: resolved from item_zoho_id through the items crosswalk (backfill + the items
--     hook), and set directly by local price lists.
--   * item_unit_id: NULL = the item's base unit (Zoho's only shape); a local list may price a
--     carton directly (negotiated carton rate ≠ base rate × 960).
--   * item_zoho_id becomes nullable: a local price list has no Zoho item id.
-- ---------------------------------------------------------------------------
ALTER TABLE pricing.price_list_items
    ADD COLUMN item_id bigint,
    ADD COLUMN item_unit_id bigint,
    ADD COLUMN valid_from date,
    ADD COLUMN valid_to date,
    ALTER COLUMN item_zoho_id DROP NOT NULL,
    ADD CONSTRAINT ck_price_list_items_window CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
    ADD CONSTRAINT fk_price_list_items_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    ADD CONSTRAINT fk_price_list_items_item_unit FOREIGN KEY (item_id, item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    ADD CONSTRAINT ck_price_list_items_item_known CHECK (num_nonnulls(item_id, item_zoho_id) >= 1),
    ADD CONSTRAINT ck_price_list_items_unit_needs_item CHECK (item_unit_id IS NULL OR item_id IS NOT NULL);
COMMENT ON COLUMN pricing.price_list_items.item_id IS 'catalogue.items; resolved from item_zoho_id via the items crosswalk, or set by a local list.';
COMMENT ON COLUMN pricing.price_list_items.item_unit_id IS 'Pack level the rate is quoted in; NULL = base unit (the only shape Zoho has).';
COMMENT ON COLUMN pricing.price_list_items.valid_from IS 'First day the rate applies; NULL = always (Zoho rows). Half-open [valid_from, valid_to).';
CREATE INDEX ix_price_list_items_item_id ON pricing.price_list_items (item_id, item_unit_id) WHERE deleted_at IS NULL AND item_id IS NOT NULL;
-- The old (price_list_id, item_zoho_id) unique index cannot hold once a Zoho item may have several
-- dated rates in one list: it becomes Zoho-rows-only (Zoho has no windows).
-- (name as renamed by migration 7c3e91a05d24, verified on the dev database)
DROP INDEX pricing.uq_price_list_items_list_item;
CREATE UNIQUE INDEX uq_price_list_items_list_item ON pricing.price_list_items (price_list_id, item_zoho_id)
    WHERE deleted_at IS NULL AND item_zoho_id IS NOT NULL AND valid_from IS NULL AND valid_to IS NULL;

-- One rate per (list, item, level) on any day. Windows may not overlap (btree_gist is not installed,
-- so a trigger serialized per list replaces an EXCLUDE constraint).
CREATE OR REPLACE FUNCTION pricing.guard_price_list_item_window() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.deleted_at IS NOT NULL OR NEW.item_id IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('pricing.price_list_items:' || NEW.price_list_id::text, 0));
    IF EXISTS (
        SELECT 1 FROM pricing.price_list_items p
         WHERE p.price_list_id = NEW.price_list_id AND p.item_id = NEW.item_id
           AND p.item_unit_id IS NOT DISTINCT FROM NEW.item_unit_id
           AND p.id <> NEW.id AND p.deleted_at IS NULL
           AND daterange(p.valid_from, p.valid_to) && daterange(NEW.valid_from, NEW.valid_to)
    ) THEN
        RAISE EXCEPTION 'overlapping price window for item % level % in price list %', NEW.item_id, NEW.item_unit_id, NEW.price_list_id
            USING ERRCODE = '23P01', HINT = 'pricing_price_window_overlap';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_price_list_items_window
    BEFORE INSERT OR UPDATE OF item_id, item_unit_id, valid_from, valid_to, deleted_at ON pricing.price_list_items
    FOR EACH ROW EXECUTE FUNCTION pricing.guard_price_list_item_window();


-- ---------------------------------------------------------------------------
-- §6.2 pricing.schemes — trade offers: "10+1 on cartons", "5% off Dabur oral care",
-- "flat ₹20 per box", near-expiry clearance on a batch. Local only (Zoho has no scheme concept;
-- plan 03 §6 says how an applied scheme is expressed when a document is pushed).
-- Usage counters are NOT stored here (AP2): they are counted from the document modules'
-- scheme applications.
-- ---------------------------------------------------------------------------
CREATE TABLE pricing.schemes (
    code                 varchar(40)   NOT NULL,
    name                 text          NOT NULL,
    description          text,
    scheme_type          varchar(24)   NOT NULL,
    applies_on           varchar(16)   NOT NULL DEFAULT 'line',
    is_stackable         boolean       NOT NULL DEFAULT false,
    priority             integer       NOT NULL DEFAULT 100,
    valid_from           date          NOT NULL,
    valid_to             date,
    max_applications     integer,
    max_per_party        integer,
    budget_amount        numeric(18,6),
    terms                text,
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'draft', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_schemes PRIMARY KEY (id),
    CONSTRAINT uq_schemes_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_schemes_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT ck_schemes_code CHECK (code ~ '^[A-Z0-9_+-]+$'),
    CONSTRAINT ck_schemes_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_schemes_type CHECK (scheme_type IN
        ('free_goods','percent_discount','flat_discount','fixed_price','cash_discount')),
    CONSTRAINT ck_schemes_applies_on CHECK (applies_on IN ('line','document')),
    CONSTRAINT ck_schemes_window CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CONSTRAINT ck_schemes_limits CHECK (
        (max_applications IS NULL OR max_applications > 0) AND (max_per_party IS NULL OR max_per_party > 0)
        AND (budget_amount IS NULL OR budget_amount > 0)),
    CONSTRAINT ck_schemes_status CHECK (status IN ('draft','active','paused','expired','archived'))
);
COMMENT ON TABLE pricing.schemes IS 'Trade offers/schemes (free goods, % / flat discounts, fixed price), scoped by scheme_targets and scheme_eligibility, rewarded by scheme_slabs.';
COMMENT ON COLUMN pricing.schemes.priority IS 'Lower applies first; among non-stackable matches only the best-priority one applies.';
CREATE UNIQUE INDEX uq_schemes_scope_code ON pricing.schemes (tenant_id, organization_id, code) WHERE deleted_at IS NULL;
CREATE INDEX ix_schemes_active_window ON pricing.schemes (organization_id, valid_from, valid_to)
    WHERE deleted_at IS NULL AND status = 'active';


-- ---------------------------------------------------------------------------
-- pricing.scheme_targets — WHAT a scheme applies to. A target can be any level of the catalogue,
-- INCLUDING a pack level (item_unit): "10+1 on cartons" does not mean "10+1 on loose pieces".
-- Exclusions (is_excluded) carve exceptions out of a wide target ("all Dabur except DB-ALM-050").
-- target_id is polymorphic by design; the service validates it against target_type and the
-- organization (orphan finder in plan 03 §5.4).
-- ---------------------------------------------------------------------------
CREATE TABLE pricing.scheme_targets (
    scheme_id            bigint        NOT NULL,
    target_type          varchar(24)   NOT NULL,
    target_id            bigint,
    threshold_unit_id    bigint,
    is_excluded          boolean       NOT NULL DEFAULT false,
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
    CONSTRAINT pk_scheme_targets PRIMARY KEY (id),
    CONSTRAINT fk_scheme_targets_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_scheme_targets_scheme FOREIGN KEY (tenant_id, organization_id, scheme_id)
        REFERENCES pricing.schemes (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_scheme_targets_threshold_unit FOREIGN KEY (tenant_id, organization_id, threshold_unit_id)
        REFERENCES catalogue.units (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_scheme_targets_type CHECK (target_type IN
        ('all_items','item','item_unit','product','item_group','brand','manufacturer','category','batch')),
    CONSTRAINT ck_scheme_targets_id CHECK ((target_type = 'all_items') = (target_id IS NULL))
);
COMMENT ON TABLE pricing.scheme_targets IS 'What a scheme applies to (any catalogue level incl. a pack level or a batch); is_excluded carves exceptions.';
COMMENT ON COLUMN pricing.scheme_targets.threshold_unit_id IS 'Count slab quantities in this unit (e.g. CTN across all Dabur items); an item without that level does not count. NULL = the line''s own unit for item_unit/item targets, base unit otherwise.';
CREATE UNIQUE INDEX uq_scheme_targets_target ON pricing.scheme_targets (scheme_id, target_type, target_id) NULLS NOT DISTINCT
    WHERE deleted_at IS NULL;
CREATE INDEX ix_scheme_targets_lookup ON pricing.scheme_targets (organization_id, target_type, target_id)
    WHERE deleted_at IS NULL AND NOT is_excluded;


-- ---------------------------------------------------------------------------
-- pricing.scheme_slabs — the rule ladder: buy-quantity / order-value bands → reward.
-- ---------------------------------------------------------------------------
CREATE TABLE pricing.scheme_slabs (
    scheme_id            bigint        NOT NULL,
    min_quantity         numeric(18,6),
    max_quantity         numeric(18,6),
    min_value            numeric(18,6),
    max_value            numeric(18,6),
    discount_percent     numeric(7,4),
    discount_amount      numeric(18,6),
    fixed_price          numeric(18,6),
    free_item_id         bigint,
    free_item_unit_id    bigint,
    free_quantity        numeric(18,6),
    is_repeating         boolean       NOT NULL DEFAULT false,
    position             smallint      NOT NULL DEFAULT 0,
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
    CONSTRAINT pk_scheme_slabs PRIMARY KEY (id),
    CONSTRAINT fk_scheme_slabs_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_scheme_slabs_scheme FOREIGN KEY (tenant_id, organization_id, scheme_id)
        REFERENCES pricing.schemes (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_scheme_slabs_free_item FOREIGN KEY (tenant_id, organization_id, free_item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_scheme_slabs_free_item_unit FOREIGN KEY (free_item_id, free_item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_scheme_slabs_threshold CHECK (num_nonnulls(min_quantity, min_value) >= 1),
    CONSTRAINT ck_scheme_slabs_ranges CHECK (
        (min_quantity IS NULL OR min_quantity > 0) AND (min_value IS NULL OR min_value > 0)
        AND (max_quantity IS NULL OR min_quantity IS NULL OR max_quantity >= min_quantity)
        AND (max_value IS NULL OR min_value IS NULL OR max_value >= min_value)),
    -- exactly one reward kind per slab; the scheme_type ↔ reward pairing is checked by the service
    CONSTRAINT ck_scheme_slabs_one_reward CHECK (
        num_nonnulls(discount_percent, discount_amount, fixed_price, free_quantity) = 1),
    CONSTRAINT ck_scheme_slabs_reward_values CHECK (
        (discount_percent IS NULL OR (discount_percent > 0 AND discount_percent <= 100))
        AND (discount_amount IS NULL OR discount_amount > 0) AND (fixed_price IS NULL OR fixed_price >= 0)
        AND (free_quantity IS NULL OR free_quantity > 0)),
    CONSTRAINT ck_scheme_slabs_free_item_needs_qty CHECK (free_item_id IS NULL OR free_quantity IS NOT NULL),
    CONSTRAINT ck_scheme_slabs_repeat_needs_qty CHECK (NOT is_repeating OR min_quantity IS NOT NULL)
);
COMMENT ON TABLE pricing.scheme_slabs IS 'Scheme ladder: quantity/value bands → one reward (percent, amount, fixed price or free goods). is_repeating = "every N get M".';
COMMENT ON COLUMN pricing.scheme_slabs.free_item_id IS 'NULL with free_quantity = the same item (and the same level unless free_item_unit_id names another).';
CREATE INDEX ix_scheme_slabs_scheme ON pricing.scheme_slabs (scheme_id, position) WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- pricing.scheme_eligibility — WHO gets a scheme. No rows = everyone. Exclusions work
-- exactly like targets.
-- ---------------------------------------------------------------------------
CREATE TABLE pricing.scheme_eligibility (
    scheme_id            bigint        NOT NULL,
    eligibility_type     varchar(24)   NOT NULL,
    ref_id               bigint,
    ref_code             varchar(64),
    is_excluded          boolean       NOT NULL DEFAULT false,
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
    CONSTRAINT pk_scheme_eligibility PRIMARY KEY (id),
    CONSTRAINT fk_scheme_eligibility_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_scheme_eligibility_scheme FOREIGN KEY (tenant_id, organization_id, scheme_id)
        REFERENCES pricing.schemes (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_scheme_eligibility_type CHECK (eligibility_type IN
        ('party','party_category','price_list','sales_channel','gst_treatment','place_of_supply','hub')),
    -- ids for entities, codes for vocabularies (gst_treatment 'business_gst', place_of_supply 'GJ')
    CONSTRAINT ck_scheme_eligibility_ref CHECK (
        (eligibility_type IN ('gst_treatment','place_of_supply') AND ref_code IS NOT NULL AND ref_id IS NULL)
        OR (eligibility_type NOT IN ('gst_treatment','place_of_supply') AND ref_id IS NOT NULL AND ref_code IS NULL))
);
COMMENT ON TABLE pricing.scheme_eligibility IS 'Who a scheme applies to (party, party category, price list, channel, GST treatment, state, hub). No rows = everyone.';
CREATE UNIQUE INDEX uq_scheme_eligibility_ref ON pricing.scheme_eligibility (scheme_id, eligibility_type, ref_id, ref_code) NULLS NOT DISTINCT
    WHERE deleted_at IS NULL;


-- ============================================================================
-- §7. Inventory — where stock is, how it moved, what is free to sell
-- ============================================================================
--
--   storage_locations (warehouse → zone → rack → shelf → bin)
--        │
--   stock_movements ─< stock_movement_lines          (internal documents: opening, adjustment,
--        │                                             transfer, write-off, count, assembly)
--        ▼  post (one transaction)
--   stock_ledger_entries  (append-only, signed base qty, partitioned by business_date)
--        │  same transaction, same statement batch
--        ▼
--   stock_balances  (item × batch × location × stock_status) ── v_item_availability
--   stock_reservations (allocations by open sales documents)  ─┘
--
-- Sales/purchase documents (invoices, credit notes, bills …) post to the SAME ledger with
-- source_type = their core.entity_types code — they do not get a movement header here.
-- Until an organization's stock is cut over (inventory ledger_mode 'authoritative', plan 04 §2),
-- Zoho is the stock master and its figures are mirrored in external_stock_levels only.

-- geo.places has no (tenant, organization, id) key yet; every org-scoped child needs one for its
-- composite FK (additive; places are MultiTenantMixin, organization_id NOT NULL).
ALTER TABLE geo.places
    ADD CONSTRAINT uq_places_scope_id UNIQUE (tenant_id, organization_id, id);

-- ---------------------------------------------------------------------------
-- inventory.storage_locations — the physical location tree. A warehouse root projects a Zoho
-- location (zoho_locations, by the locations post_upsert hook) and points at its geo.places row.
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.storage_locations (
    parent_id            bigint,
    path                 text,
    depth                smallint      NOT NULL DEFAULT 0,
    code                 varchar(40)   NOT NULL,
    name                 text          NOT NULL,
    location_type        varchar(16)   NOT NULL,
    place_id             bigint,
    zoho_location_id     varchar(50),
    is_receivable        boolean       NOT NULL DEFAULT true,
    is_pickable          boolean       NOT NULL DEFAULT true,
    counts_as_available  boolean       NOT NULL DEFAULT true,
    temperature_zone     varchar(16),
    barcode              varchar(64),
    position             smallint      NOT NULL DEFAULT 0,
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
    CONSTRAINT pk_storage_locations PRIMARY KEY (id),
    CONSTRAINT uq_storage_locations_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_storage_locations_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_storage_locations_parent FOREIGN KEY (tenant_id, organization_id, parent_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_storage_locations_place FOREIGN KEY (tenant_id, organization_id, place_id)
        REFERENCES geo.places (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_storage_locations_code CHECK (code ~ '^[A-Z0-9_-]+$'),
    CONSTRAINT ck_storage_locations_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT ck_storage_locations_type CHECK (location_type IN
        ('warehouse','zone','aisle','rack','shelf','bin','staging','virtual')),
    -- only a warehouse (or a virtual root such as "in transit") is a root
    CONSTRAINT ck_storage_locations_root CHECK ((parent_id IS NULL) = (location_type IN ('warehouse','virtual'))),
    CONSTRAINT ck_storage_locations_no_self_parent CHECK (parent_id IS NULL OR parent_id <> id),
    CONSTRAINT ck_storage_locations_temperature_zone CHECK (temperature_zone IS NULL OR temperature_zone IN ('ambient','cool','cold_chain','frozen')),
    CONSTRAINT ck_storage_locations_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE inventory.storage_locations IS 'Physical location tree (warehouse → zone → rack → shelf → bin). Materialized path, house style (no ltree).';
COMMENT ON COLUMN inventory.storage_locations.path IS '/<root id>/…/<id>/ maintained by trigger; subtree = path LIKE parent.path || ''%''.';
COMMENT ON COLUMN inventory.storage_locations.counts_as_available IS 'false for return/damage/QC areas: stock there is never offered for sale.';
CREATE UNIQUE INDEX uq_storage_locations_code ON inventory.storage_locations (tenant_id, organization_id, parent_id, code) NULLS NOT DISTINCT
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_storage_locations_zoho ON inventory.storage_locations (tenant_id, organization_id, zoho_location_id)
    WHERE deleted_at IS NULL AND zoho_location_id IS NOT NULL;
CREATE UNIQUE INDEX uq_storage_locations_barcode ON inventory.storage_locations (tenant_id, organization_id, barcode)
    WHERE deleted_at IS NULL AND barcode IS NOT NULL;
CREATE INDEX ix_storage_locations_path ON inventory.storage_locations (path text_pattern_ops) WHERE deleted_at IS NULL;

CREATE OR REPLACE FUNCTION inventory.maintain_storage_location_path() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_parent_path text;
    v_parent_depth smallint;
BEGIN
    IF NEW.parent_id IS NULL THEN
        NEW.path := '/' || NEW.id || '/';
        NEW.depth := 0;
    ELSE
        SELECT path, depth INTO v_parent_path, v_parent_depth
          FROM inventory.storage_locations WHERE id = NEW.parent_id;
        IF v_parent_path LIKE '%/' || NEW.id || '/%' THEN
            RAISE EXCEPTION 'moving location % under its own descendant', NEW.id
                USING ERRCODE = '23514', HINT = 'inventory_location_cycle';
        END IF;
        NEW.path := v_parent_path || NEW.id || '/';
        NEW.depth := v_parent_depth + 1;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.path IS DISTINCT FROM OLD.path THEN
        -- re-root the subtree (Core UPDATE: no row_version bump, house rule from teams/_recompute)
        UPDATE inventory.storage_locations
           SET path = NEW.path || substr(path, length(OLD.path) + 1),
               depth = depth + (NEW.depth - OLD.depth)
         WHERE path LIKE OLD.path || '%' AND id <> NEW.id;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_storage_locations_path
    BEFORE INSERT OR UPDATE OF parent_id ON inventory.storage_locations
    FOR EACH ROW EXECUTE FUNCTION inventory.maintain_storage_location_path();
-- NB: on INSERT the bigserial id is already assigned when a BEFORE ROW trigger runs.


-- ---------------------------------------------------------------------------
-- inventory.reason_codes — why stock changed (adjustment, write-off, hold, return, count).
-- Organization-scoped and extendable; defaults seeded per organization (seed function §10).
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.reason_codes (
    code                 varchar(40)   NOT NULL,
    name                 text          NOT NULL,
    applies_to           varchar(16)   NOT NULL,
    direction            varchar(8)    NOT NULL DEFAULT 'either',
    requires_document    boolean       NOT NULL DEFAULT false,
    is_system            boolean       NOT NULL DEFAULT false,
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
    CONSTRAINT pk_reason_codes PRIMARY KEY (id),
    CONSTRAINT uq_reason_codes_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_reason_codes_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT ck_reason_codes_code CHECK (code ~ '^[a-z0-9_]+$'),
    CONSTRAINT ck_reason_codes_applies_to CHECK (applies_to IN ('adjustment','write_off','hold','return','transfer','count')),
    CONSTRAINT ck_reason_codes_direction CHECK (direction IN ('in','out','either')),
    CONSTRAINT ck_reason_codes_status CHECK (status IN ('active','inactive'))
);
CREATE UNIQUE INDEX uq_reason_codes_scope_code ON inventory.reason_codes (tenant_id, organization_id, code) WHERE deleted_at IS NULL;

ALTER TABLE catalogue.batch_holds
    ADD CONSTRAINT fk_batch_holds_reason_code FOREIGN KEY (tenant_id, organization_id, reason_code_id)
        REFERENCES inventory.reason_codes (tenant_id, organization_id, id) ON DELETE RESTRICT;


-- ---------------------------------------------------------------------------
-- inventory.stock_policies — the organization's configurable stock rules, as SPARSE scoped layers
-- (the fieldops policy-layer pattern): one row per scope, every rule column nullable, and the
-- EFFECTIVE value of each rule is the most specific non-NULL one:
--     item  >  item_group  >  warehouse  >  organization  >  built-in default
-- Typed columns (not the generic settings store) because the database itself enforces two of them
-- (negative stock — trigger on stock_balances; ledger_mode — the posting function), and a trigger
-- must read them without the application.
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.stock_policies (
    scope_type                     varchar(16)   NOT NULL,
    warehouse_id                   bigint,
    item_group_id                  bigint,
    item_id                        bigint,
    -- organization scope only ------------------------------------------------
    ledger_mode                    varchar(16),
    -- negative stock ----------------------------------------------------------
    allow_negative_stock           boolean,
    allow_negative_batch_stock     boolean,
    -- expiry & shelf life ----------------------------------------------------
    expired_sale_policy            varchar(16),
    near_expiry_days               integer,
    min_remaining_shelf_life_days  integer,
    min_remaining_shelf_life_pct   numeric(5,2),
    receipt_min_shelf_life_days    integer,
    auto_mark_expired              boolean,
    -- allocation & ageing ----------------------------------------------------
    allocation_strategy            varchar(16),
    ageing_bucket_days             integer[],
    notes                          text,
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
    CONSTRAINT pk_stock_policies PRIMARY KEY (id),
    CONSTRAINT fk_stock_policies_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_stock_policies_warehouse FOREIGN KEY (tenant_id, organization_id, warehouse_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_stock_policies_item_group FOREIGN KEY (tenant_id, organization_id, item_group_id)
        REFERENCES catalogue.item_groups (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_stock_policies_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_stock_policies_scope CHECK (
        (scope_type = 'organization' AND num_nonnulls(warehouse_id, item_group_id, item_id) = 0)
        OR (scope_type = 'warehouse'  AND warehouse_id IS NOT NULL AND num_nonnulls(item_group_id, item_id) = 0)
        OR (scope_type = 'item_group' AND item_group_id IS NOT NULL AND num_nonnulls(warehouse_id, item_id) = 0)
        OR (scope_type = 'item'       AND item_id IS NOT NULL AND num_nonnulls(warehouse_id, item_group_id) = 0)),
    -- the stock master is an organization-wide fact
    CONSTRAINT ck_stock_policies_ledger_mode CHECK (
        ledger_mode IS NULL OR (scope_type = 'organization' AND ledger_mode IN ('mirror','authoritative'))),
    CONSTRAINT ck_stock_policies_expired_sale CHECK (
        expired_sale_policy IS NULL OR expired_sale_policy IN ('block','override','warn','allow')),
    CONSTRAINT ck_stock_policies_days CHECK (
        (near_expiry_days IS NULL OR near_expiry_days >= 0)
        AND (min_remaining_shelf_life_days IS NULL OR min_remaining_shelf_life_days >= 0)
        AND (receipt_min_shelf_life_days IS NULL OR receipt_min_shelf_life_days >= 0)),
    CONSTRAINT ck_stock_policies_pct CHECK (
        min_remaining_shelf_life_pct IS NULL OR (min_remaining_shelf_life_pct >= 0 AND min_remaining_shelf_life_pct <= 100)),
    CONSTRAINT ck_stock_policies_allocation CHECK (
        allocation_strategy IS NULL OR allocation_strategy IN ('fefo','fifo','manual')),
    CONSTRAINT ck_stock_policies_buckets CHECK (
        ageing_bucket_days IS NULL OR (cardinality(ageing_bucket_days) BETWEEN 1 AND 12 AND 0 < ALL (ageing_bucket_days))),
    CONSTRAINT ck_stock_policies_status CHECK (status IN ('active','inactive'))
);
COMMENT ON TABLE inventory.stock_policies IS
    'Configurable stock rules as sparse scoped layers (organization > warehouse > item_group > item; most specific non-NULL wins per rule). Resolved by inventory.effective_stock_policy().';
COMMENT ON COLUMN inventory.stock_policies.ledger_mode IS 'Organization only. mirror = Zoho is the stock master (default); authoritative = our ledger is (plan 04 §2).';
COMMENT ON COLUMN inventory.stock_policies.allow_negative_stock IS 'May an issue drive a non-batch position below zero (stock booked later, e.g. paperwork lag). Default false.';
COMMENT ON COLUMN inventory.stock_policies.allow_negative_batch_stock IS 'Same for a NAMED lot. Default false even when allow_negative_stock is true: a lot cannot physically go below zero; it means the wrong lot was picked.';
COMMENT ON COLUMN inventory.stock_policies.expired_sale_policy IS 'block (default): expired lots never sold. override: sellable with permission catalogue.batch:use + reason. warn: sellable, flagged on the line. allow: sellable silently.';
COMMENT ON COLUMN inventory.stock_policies.near_expiry_days IS 'A lot within this many days of effective expiry is near-expiry (dashboards, warnings, clearance schemes). Default 90.';
COMMENT ON COLUMN inventory.stock_policies.min_remaining_shelf_life_days IS 'Do not SELL a lot with fewer days left. The stricter of _days and _pct applies.';
COMMENT ON COLUMN inventory.stock_policies.min_remaining_shelf_life_pct IS 'Do not SELL a lot with less than this % of its total shelf life left.';
COMMENT ON COLUMN inventory.stock_policies.receipt_min_shelf_life_days IS 'Refuse (or flag) RECEIVING a lot with fewer days left (supplier short-dated stock).';
COMMENT ON COLUMN inventory.stock_policies.auto_mark_expired IS 'Daily task moves expired lots'' available stock to status expired (authoritative mode). Default true.';
COMMENT ON COLUMN inventory.stock_policies.ageing_bucket_days IS 'Upper bounds of ageing buckets in days, ascending (default {30,60,90,180,365}); used by expiry and stock-ageing reports.';
CREATE UNIQUE INDEX uq_stock_policies_scope ON inventory.stock_policies
    (tenant_id, organization_id, scope_type, warehouse_id, item_group_id, item_id) NULLS NOT DISTINCT
    WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- effective_stock_policy — the merged rule set for (organization, warehouse, item). One row.
-- Built-in defaults close the chain so callers never see NULL.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION inventory.effective_stock_policy(
    p_tenant_id bigint, p_organization_id bigint, p_warehouse_id bigint, p_item_id bigint)
RETURNS TABLE (
    ledger_mode varchar, allow_negative_stock boolean, allow_negative_batch_stock boolean,
    expired_sale_policy varchar, near_expiry_days integer, min_remaining_shelf_life_days integer,
    min_remaining_shelf_life_pct numeric, receipt_min_shelf_life_days integer, auto_mark_expired boolean,
    allocation_strategy varchar, ageing_bucket_days integer[])
LANGUAGE sql STABLE AS $$
    WITH layers AS (
        SELECT p.*,
               CASE p.scope_type WHEN 'item' THEN 1 WHEN 'item_group' THEN 2
                                 WHEN 'warehouse' THEN 3 ELSE 4 END AS rank
          FROM inventory.stock_policies p
         WHERE p.tenant_id = p_tenant_id AND p.organization_id = p_organization_id
           AND p.deleted_at IS NULL AND p.status = 'active'
           AND (p.scope_type = 'organization'
                OR (p.scope_type = 'warehouse' AND p.warehouse_id = p_warehouse_id)
                OR (p.scope_type = 'item' AND p.item_id = p_item_id)
                OR (p.scope_type = 'item_group' AND p.item_group_id =
                        (SELECT i.item_group_id FROM catalogue.items i WHERE i.id = p_item_id)))
    )
    SELECT
        COALESCE((SELECT ledger_mode FROM layers WHERE ledger_mode IS NOT NULL ORDER BY rank LIMIT 1), 'mirror'),
        COALESCE((SELECT allow_negative_stock FROM layers WHERE allow_negative_stock IS NOT NULL ORDER BY rank LIMIT 1), false),
        COALESCE((SELECT allow_negative_batch_stock FROM layers WHERE allow_negative_batch_stock IS NOT NULL ORDER BY rank LIMIT 1), false),
        COALESCE((SELECT expired_sale_policy FROM layers WHERE expired_sale_policy IS NOT NULL ORDER BY rank LIMIT 1), 'block'),
        COALESCE((SELECT near_expiry_days FROM layers WHERE near_expiry_days IS NOT NULL ORDER BY rank LIMIT 1), 90),
        COALESCE((SELECT min_remaining_shelf_life_days FROM layers WHERE min_remaining_shelf_life_days IS NOT NULL ORDER BY rank LIMIT 1), 0),
        COALESCE((SELECT min_remaining_shelf_life_pct FROM layers WHERE min_remaining_shelf_life_pct IS NOT NULL ORDER BY rank LIMIT 1), 0),
        COALESCE((SELECT receipt_min_shelf_life_days FROM layers WHERE receipt_min_shelf_life_days IS NOT NULL ORDER BY rank LIMIT 1), 0),
        COALESCE((SELECT auto_mark_expired FROM layers WHERE auto_mark_expired IS NOT NULL ORDER BY rank LIMIT 1), true),
        COALESCE((SELECT allocation_strategy FROM layers WHERE allocation_strategy IS NOT NULL ORDER BY rank LIMIT 1), 'fefo'),
        COALESCE((SELECT ageing_bucket_days FROM layers WHERE ageing_bucket_days IS NOT NULL ORDER BY rank LIMIT 1),
                 ARRAY[30,60,90,180,365])
$$;
COMMENT ON FUNCTION inventory.effective_stock_policy(bigint, bigint, bigint, bigint) IS
    'Merged stock rules (item > item_group > warehouse > organization > defaults). The Python twin (inventory/policy.py) resolves the same layers in batch for a whole document.';


-- ---------------------------------------------------------------------------
-- inventory.stock_movements / stock_movement_lines — INTERNAL stock documents. Draft → posted
-- (writes the ledger) → optionally cancelled (posts the exact reversal; never edits history).
-- Breaking a carton into boxes is NOT a movement: stock is held in base units, so re-denominating
-- changes nothing (plan 02 §6). 'assembly' / 'disassembly' change WHICH item exists.
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.stock_movements (
    movement_number          varchar(40)   NOT NULL,
    movement_type            varchar(16)   NOT NULL,
    business_date            date          NOT NULL,
    from_location_id         bigint,
    to_location_id           bigint,
    reason_code_id           bigint,
    reference                text,
    notes                    text,
    posted_at                timestamptz,
    posted_by                bigint,
    cancelled_at             timestamptz,
    cancelled_by             bigint,
    cancellation_reason      text,
    zoho_id                  varchar(50),
    -- standard block ---------------------------------------------------------
    id bigserial NOT NULL, uuid uuid NOT NULL DEFAULT uuidv7(),
    tenant_id bigint NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id bigint NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'draft', is_verified boolean NOT NULL DEFAULT false,
    row_version integer NOT NULL DEFAULT 1,
    created_by bigint, created_by_name varchar(255), updated_by bigint, updated_by_name varchar(255),
    app_version varchar(32), app_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz, deleted_by bigint, deleted_reason text,
    CONSTRAINT pk_stock_movements PRIMARY KEY (id),
    CONSTRAINT uq_stock_movements_scope_id UNIQUE (tenant_id, organization_id, id),
    CONSTRAINT fk_stock_movements_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_stock_movements_from FOREIGN KEY (tenant_id, organization_id, from_location_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movements_to FOREIGN KEY (tenant_id, organization_id, to_location_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movements_reason FOREIGN KEY (tenant_id, organization_id, reason_code_id)
        REFERENCES inventory.reason_codes (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_stock_movements_type CHECK (movement_type IN
        ('opening','adjustment','transfer','write_off','cycle_count','status_change','assembly','disassembly')),
    CONSTRAINT ck_stock_movements_status CHECK (status IN ('draft','posted','cancelled')),
    CONSTRAINT ck_stock_movements_posted CHECK (status = 'draft' OR posted_at IS NOT NULL),
    CONSTRAINT ck_stock_movements_cancelled CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
    CONSTRAINT ck_stock_movements_transfer CHECK (movement_type <> 'transfer'
        OR (from_location_id IS NOT NULL AND to_location_id IS NOT NULL AND from_location_id <> to_location_id))
);
COMMENT ON TABLE inventory.stock_movements IS 'Internal stock documents (opening, adjustment, transfer, write-off, count, status change, assembly). Posting writes the ledger; cancelling posts the reversal.';
CREATE UNIQUE INDEX uq_stock_movements_number ON inventory.stock_movements (tenant_id, organization_id, movement_number)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_stock_movements_zoho_id ON inventory.stock_movements (tenant_id, zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;
CREATE INDEX ix_stock_movements_date ON inventory.stock_movements (organization_id, business_date DESC) WHERE deleted_at IS NULL;

CREATE TABLE inventory.stock_movement_lines (
    movement_id              bigint        NOT NULL,
    line_no                  smallint      NOT NULL,
    item_id                  bigint        NOT NULL,
    batch_id                 bigint,
    item_unit_id             bigint,
    quantity                 numeric(18,6) NOT NULL,
    conversion_factor        numeric(24,6) NOT NULL DEFAULT 1,
    quantity_base            numeric(18,6) NOT NULL,
    from_location_id         bigint,
    to_location_id           bigint,
    from_status              varchar(16),
    to_status                varchar(16),
    counted_quantity_base    numeric(18,6),
    unit_cost                numeric(18,6),
    reason_code_id           bigint,
    notes                    text,
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
    CONSTRAINT pk_stock_movement_lines PRIMARY KEY (id),
    CONSTRAINT fk_stock_movement_lines_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_stock_movement_lines_movement FOREIGN KEY (tenant_id, organization_id, movement_id)
        REFERENCES inventory.stock_movements (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_stock_movement_lines_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movement_lines_batch FOREIGN KEY (item_id, batch_id)
        REFERENCES catalogue.batches (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movement_lines_item_unit FOREIGN KEY (item_id, item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movement_lines_from FOREIGN KEY (tenant_id, organization_id, from_location_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movement_lines_to FOREIGN KEY (tenant_id, organization_id, to_location_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movement_lines_reason FOREIGN KEY (tenant_id, organization_id, reason_code_id)
        REFERENCES inventory.reason_codes (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_stock_movement_lines_quantity CHECK (quantity > 0 AND conversion_factor > 0 AND quantity_base > 0),
    CONSTRAINT ck_stock_movement_lines_base CHECK (quantity_base = round(quantity * conversion_factor, 6)),
    CONSTRAINT ck_stock_movement_lines_some_location CHECK (num_nonnulls(from_location_id, to_location_id) >= 1),
    CONSTRAINT ck_stock_movement_lines_statuses CHECK (
        (from_status IS NULL OR from_status IN ('available','quarantine','damaged','expired','in_transit','returned'))
        AND (to_status IS NULL OR to_status IN ('available','quarantine','damaged','expired','in_transit','returned')))
);
CREATE UNIQUE INDEX uq_stock_movement_lines_no ON inventory.stock_movement_lines (movement_id, line_no) WHERE deleted_at IS NULL;
CREATE INDEX ix_stock_movement_lines_item ON inventory.stock_movement_lines (item_id) WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- inventory.stock_ledger_entries — THE stock truth. Append-only, immutable, signed quantities in
-- the BASE unit. Every stock-changing fact of every module lands here, named by
-- (source_type, source_id, source_line_id). Corrections are reversing entries.
--
-- LEDGER class (LedgerMixin shape + organization_id NOT NULL): no soft delete, no row_version,
-- no updated_*. Partitioned by business_date; partitions are app-managed (monthly, created
-- ahead by inventory/partitions.py on the fieldops/partitions.py pattern), with a DEFAULT
-- partition as the safety net. Every PK/unique includes the partition key.
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.stock_ledger_entries (
    id                    bigserial     NOT NULL,
    uuid                  uuid          NOT NULL DEFAULT uuidv7(),
    tenant_id             bigint        NOT NULL REFERENCES org_management.tenants (id) ON DELETE RESTRICT,
    organization_id       bigint        NOT NULL,
    business_date         date          NOT NULL,
    posted_at             timestamptz   NOT NULL DEFAULT now(),
    -- what -------------------------------------------------------------------
    item_id               bigint        NOT NULL,
    batch_id              bigint,
    storage_location_id   bigint        NOT NULL,
    stock_status          varchar(16)   NOT NULL DEFAULT 'available',
    quantity_base         numeric(18,6) NOT NULL,
    -- how the source expressed it (snapshot; never recomputed) ---------------
    item_unit_id          bigint,
    unit_code             varchar(32),
    quantity_in_unit      numeric(18,6),
    conversion_factor     numeric(24,6) NOT NULL DEFAULT 1,
    -- value (organization base currency) -------------------------------------
    unit_cost             numeric(18,6),
    value_delta           numeric(18,6),
    -- why --------------------------------------------------------------------
    movement_type         varchar(24)   NOT NULL,
    reason_code_id        bigint,
    source_type           varchar(64)   NOT NULL,
    source_id             bigint        NOT NULL,
    source_line_id        bigint,
    source_number         varchar(64),
    reverses_entry_id     bigint,
    reverses_business_date date,
    -- audit (LedgerMixin + created_*) ----------------------------------------
    created_by            bigint,
    created_by_name       varchar(255),
    created_at            timestamptz   NOT NULL DEFAULT now(),
    app_version           varchar(32),
    app_metadata          jsonb         NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT pk_stock_ledger_entries PRIMARY KEY (id, business_date),
    CONSTRAINT uq_stock_ledger_entries_uuid UNIQUE (uuid, business_date),
    CONSTRAINT fk_stock_ledger_entries_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_ledger_entries_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_ledger_entries_batch FOREIGN KEY (item_id, batch_id)
        REFERENCES catalogue.batches (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_ledger_entries_item_unit FOREIGN KEY (item_id, item_unit_id)
        REFERENCES catalogue.item_units (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_ledger_entries_location FOREIGN KEY (tenant_id, organization_id, storage_location_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_ledger_entries_reason FOREIGN KEY (tenant_id, organization_id, reason_code_id)
        REFERENCES inventory.reason_codes (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_ledger_entries_source_type FOREIGN KEY (source_type)
        REFERENCES core.entity_types (code) ON DELETE RESTRICT,
    CONSTRAINT ck_stock_ledger_entries_quantity CHECK (quantity_base <> 0 AND conversion_factor > 0),
    CONSTRAINT ck_stock_ledger_entries_status CHECK (stock_status IN
        ('available','quarantine','damaged','expired','in_transit','returned')),
    CONSTRAINT ck_stock_ledger_entries_movement CHECK (movement_type IN
        ('receipt','issue','sale','sales_return','purchase_return','transfer_out','transfer_in',
         'adjustment_in','adjustment_out','write_off','opening','status_out','status_in',
         'assembly_consume','assembly_produce','reversal')),
    CONSTRAINT ck_stock_ledger_entries_reversal CHECK (
        (reverses_entry_id IS NULL) = (reverses_business_date IS NULL)
        AND ((movement_type = 'reversal') = (reverses_entry_id IS NOT NULL)))
) PARTITION BY RANGE (business_date);
COMMENT ON TABLE inventory.stock_ledger_entries IS
    'Append-only stock ledger: signed base-unit quantities per item × batch × location × status, named by its source document line. Immutable (trigger); corrections are reversals. Partitioned monthly by business_date (app-managed).';
COMMENT ON COLUMN inventory.stock_ledger_entries.quantity_base IS 'Signed: + into the location/status, − out of it. Always base units.';
COMMENT ON COLUMN inventory.stock_ledger_entries.source_type IS 'core.entity_types code of the source (stock_movement, invoice, credit_note, bill …).';
COMMENT ON COLUMN inventory.stock_ledger_entries.value_delta IS 'quantity_base × unit_cost at posting time; valuation layers (FIFO) are out of scope (plan 04 §9).';

CREATE TABLE inventory.stock_ledger_entries_default PARTITION OF inventory.stock_ledger_entries DEFAULT;

CREATE INDEX ix_stock_ledger_entries_item_date ON inventory.stock_ledger_entries (item_id, business_date DESC);
CREATE INDEX ix_stock_ledger_entries_batch_date ON inventory.stock_ledger_entries (batch_id, business_date DESC) WHERE batch_id IS NOT NULL;
CREATE INDEX ix_stock_ledger_entries_location ON inventory.stock_ledger_entries (storage_location_id, business_date DESC);
CREATE INDEX ix_stock_ledger_entries_source ON inventory.stock_ledger_entries (source_type, source_id, source_line_id);
CREATE INDEX ix_stock_ledger_entries_tenant_org ON inventory.stock_ledger_entries (tenant_id, organization_id);
CREATE INDEX ix_stock_ledger_entries_date_brin ON inventory.stock_ledger_entries USING brin (business_date);
-- a source line posts each (item, batch, location, status) leg once; replays are idempotent
CREATE UNIQUE INDEX uq_stock_ledger_entries_source_leg ON inventory.stock_ledger_entries
    (source_type, source_id, source_line_id, item_id, batch_id, storage_location_id, stock_status, movement_type, business_date)
    NULLS NOT DISTINCT;

CREATE OR REPLACE FUNCTION inventory.forbid_ledger_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'inventory.stock_ledger_entries is append-only; post a reversal instead'
        USING ERRCODE = '42501', HINT = 'inventory_ledger_immutable';
END $$;

CREATE TRIGGER trg_stock_ledger_entries_immutable
    BEFORE UPDATE OR DELETE ON inventory.stock_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION inventory.forbid_ledger_mutation();

-- While Zoho is the stock master (ledger_mode 'mirror', the default), nothing may post: a ledger fed
-- by only some stock-moving documents would be a second, wrong truth. The cut-over flips the mode
-- and posts the opening movement in ONE transaction (plan 04 §2.3).
CREATE OR REPLACE FUNCTION inventory.require_authoritative_ledger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT ledger_mode FROM inventory.effective_stock_policy(NEW.tenant_id, NEW.organization_id, NULL, NULL))
       IS DISTINCT FROM 'authoritative' THEN
        RAISE EXCEPTION 'organization % keeps stock in Zoho (ledger_mode mirror); cut over before posting', NEW.organization_id
            USING ERRCODE = '55000', HINT = 'inventory_ledger_mode_mirror';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_stock_ledger_entries_ledger_mode
    BEFORE INSERT ON inventory.stock_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION inventory.require_authoritative_ledger();


-- ---------------------------------------------------------------------------
-- inventory.stock_balances — the position cache: one row per (item, batch, location, status).
-- Written ONLY by the posting service, in the same transaction as the ledger rows, with an
-- atomic `quantity_on_hand = quantity_on_hand + delta` upsert. guard_negative_stock (below) runs on
-- the incremented row while it is locked, so the organization's negative-stock policy holds even
-- under concurrency (the losing transaction gets 23514 → 409 insufficient_stock).
-- Recomputable at any time from the ledger (inventory.rebuild_balances).
-- LEDGER-class cache (no soft delete, no row_version: the atomic increment is the concurrency
-- control). Reasoned entry in tests/test_tenancy.py.
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.stock_balances (
    id                    bigserial     NOT NULL,
    tenant_id             bigint        NOT NULL REFERENCES org_management.tenants (id) ON DELETE RESTRICT,
    organization_id       bigint        NOT NULL,
    item_id               bigint        NOT NULL,
    batch_id              bigint,
    storage_location_id   bigint        NOT NULL,
    stock_status          varchar(16)   NOT NULL,
    quantity_on_hand      numeric(18,6) NOT NULL DEFAULT 0,
    last_entry_at         timestamptz,
    updated_at            timestamptz   NOT NULL DEFAULT now(),
    app_version           varchar(32),
    app_metadata          jsonb         NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT pk_stock_balances PRIMARY KEY (id),
    CONSTRAINT fk_stock_balances_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_balances_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_balances_batch FOREIGN KEY (item_id, batch_id)
        REFERENCES catalogue.batches (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_balances_location FOREIGN KEY (tenant_id, organization_id, storage_location_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_stock_balances_status CHECK (stock_status IN
        ('available','quarantine','damaged','expired','in_transit','returned')),
    -- only sellable/available stock may ever be negative (a damaged or in-transit hole is a bug)
    CONSTRAINT ck_stock_balances_negative_only_available CHECK (quantity_on_hand >= 0 OR stock_status = 'available')
);
COMMENT ON TABLE inventory.stock_balances IS 'Position cache (item × batch × location × status), maintained in the posting transaction; never an input to the ledger. Rebuildable.';
CREATE UNIQUE INDEX uq_stock_balances_position ON inventory.stock_balances
    (tenant_id, organization_id, item_id, batch_id, storage_location_id, stock_status) NULLS NOT DISTINCT;
CREATE INDEX ix_stock_balances_item ON inventory.stock_balances (item_id) WHERE quantity_on_hand <> 0;
CREATE INDEX ix_stock_balances_batch ON inventory.stock_balances (batch_id) WHERE batch_id IS NOT NULL AND quantity_on_hand <> 0;
CREATE INDEX ix_stock_balances_location ON inventory.stock_balances (storage_location_id) WHERE quantity_on_hand <> 0;
-- negative positions are a work queue (stock to be booked in), so they get their own index
CREATE INDEX ix_stock_balances_negative ON inventory.stock_balances (organization_id, item_id) WHERE quantity_on_hand < 0;

CREATE OR REPLACE FUNCTION inventory.guard_negative_stock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_allow boolean;
BEGIN
    IF NEW.quantity_on_hand >= 0 THEN
        RETURN NEW;
    END IF;
    -- an UPDATE that moves a negative position TOWARDS zero is always allowed (booking stock in)
    IF TG_OP = 'UPDATE' AND NEW.quantity_on_hand >= OLD.quantity_on_hand THEN
        RETURN NEW;
    END IF;
    SELECT CASE WHEN NEW.batch_id IS NULL THEN p.allow_negative_stock ELSE p.allow_negative_batch_stock END
      INTO v_allow
      FROM inventory.effective_stock_policy(
               NEW.tenant_id, NEW.organization_id,
               (SELECT split_part(l.path, '/', 2)::bigint FROM inventory.storage_locations l
                 WHERE l.id = NEW.storage_location_id),
               NEW.item_id) p;
    IF NOT COALESCE(v_allow, false) THEN
        RAISE EXCEPTION 'insufficient stock: item % batch % location % would be %',
              NEW.item_id, NEW.batch_id, NEW.storage_location_id, NEW.quantity_on_hand
            USING ERRCODE = '23514', HINT = 'inventory_insufficient_stock';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_stock_balances_negative
    BEFORE INSERT OR UPDATE OF quantity_on_hand ON inventory.stock_balances
    FOR EACH ROW EXECUTE FUNCTION inventory.guard_negative_stock();
-- rebuild_balances() bypasses nothing: a rebuild that recreates a negative position the policy
-- forbids fails loudly, which is the correct signal (the ledger disagrees with the policy).


-- ---------------------------------------------------------------------------
-- inventory.stock_reservations — stock promised to an open sales document (order / draft
-- invoice / delivery). Reduces availability without moving stock. Consumed when the document
-- posts its issue; released when it is cancelled; expires_at sweeps abandoned carts.
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.stock_reservations (
    item_id               bigint        NOT NULL,
    batch_id              bigint,
    warehouse_id          bigint        NOT NULL,
    quantity_base         numeric(18,6) NOT NULL,
    source_type           varchar(64)   NOT NULL,
    source_id             bigint        NOT NULL,
    source_line_id        bigint,
    expires_at            timestamptz,
    consumed_at           timestamptz,
    released_at           timestamptz,
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
    CONSTRAINT pk_stock_reservations PRIMARY KEY (id),
    CONSTRAINT fk_stock_reservations_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_stock_reservations_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_reservations_batch FOREIGN KEY (item_id, batch_id)
        REFERENCES catalogue.batches (item_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_reservations_warehouse FOREIGN KEY (tenant_id, organization_id, warehouse_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_reservations_source_type FOREIGN KEY (source_type)
        REFERENCES core.entity_types (code) ON DELETE RESTRICT,
    CONSTRAINT ck_stock_reservations_quantity CHECK (quantity_base > 0),
    CONSTRAINT ck_stock_reservations_status CHECK (status IN ('active','consumed','released','expired')),
    CONSTRAINT ck_stock_reservations_closed CHECK (
        (status = 'consumed') = (consumed_at IS NOT NULL) AND (status IN ('released','expired')) = (released_at IS NOT NULL))
);
COMMENT ON TABLE inventory.stock_reservations IS 'Stock promised to open sales documents at warehouse level (optionally a batch); reduces availability, moves nothing.';
CREATE UNIQUE INDEX uq_stock_reservations_source ON inventory.stock_reservations (source_type, source_id, source_line_id, batch_id) NULLS NOT DISTINCT
    WHERE deleted_at IS NULL AND status = 'active';
CREATE INDEX ix_stock_reservations_item_wh ON inventory.stock_reservations (item_id, warehouse_id)
    WHERE deleted_at IS NULL AND status = 'active';
CREATE INDEX ix_stock_reservations_expiry ON inventory.stock_reservations (expires_at)
    WHERE deleted_at IS NULL AND status = 'active' AND expires_at IS NOT NULL;


-- ---------------------------------------------------------------------------
-- inventory.replenishment_policies — replenishment settings per item × warehouse.
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.replenishment_policies (
    item_id               bigint        NOT NULL,
    warehouse_id          bigint        NOT NULL,
    is_stocked            boolean       NOT NULL DEFAULT true,
    reorder_level_base    numeric(18,6),
    reorder_qty_base      numeric(18,6),
    min_stock_base        numeric(18,6),
    max_stock_base        numeric(18,6),
    default_bin_id        bigint,
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
    CONSTRAINT pk_replenishment_policies PRIMARY KEY (id),
    CONSTRAINT fk_replenishment_policies_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    -- ------------------------------------------------------------------------
    CONSTRAINT fk_replenishment_policies_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_replenishment_policies_warehouse FOREIGN KEY (tenant_id, organization_id, warehouse_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_replenishment_policies_bin FOREIGN KEY (tenant_id, organization_id, default_bin_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_replenishment_policies_values CHECK (
        (reorder_level_base IS NULL OR reorder_level_base >= 0) AND (reorder_qty_base IS NULL OR reorder_qty_base > 0)
        AND (min_stock_base IS NULL OR min_stock_base >= 0) AND (max_stock_base IS NULL OR max_stock_base >= 0)
        AND (max_stock_base IS NULL OR min_stock_base IS NULL OR max_stock_base >= min_stock_base))
);
CREATE UNIQUE INDEX uq_replenishment_policies_pair ON inventory.replenishment_policies (item_id, warehouse_id) WHERE deleted_at IS NULL;


-- ---------------------------------------------------------------------------
-- inventory.external_stock_levels — what Zoho says the stock is (item.locations[] and batch
-- balance_quantity per location). A SNAPSHOT for display while Zoho is the stock master and for
-- reconciliation after cut-over. Never an input to the ledger except through an explicit
-- opening-balance movement (plan 04 §2.3).
-- ---------------------------------------------------------------------------
CREATE TABLE inventory.external_stock_levels (
    id                        bigserial     NOT NULL,
    tenant_id                 bigint        NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
    organization_id           bigint        NOT NULL,
    source_system             varchar(16)   NOT NULL DEFAULT 'zoho',
    item_id                   bigint        NOT NULL,
    batch_id                  bigint,
    external_location_id      varchar(50)   NOT NULL,
    storage_location_id       bigint,
    stock_on_hand             numeric(18,6),
    available_stock           numeric(18,6),
    actual_available_stock    numeric(18,6),
    committed_stock           numeric(18,6),
    in_quantity               numeric(18,6),
    as_of                     timestamptz   NOT NULL,
    updated_at                timestamptz   NOT NULL DEFAULT now(),
    app_version               varchar(32),
    app_metadata              jsonb         NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT pk_external_stock_levels PRIMARY KEY (id),
    CONSTRAINT fk_external_stock_levels_tenant_org FOREIGN KEY (tenant_id, organization_id)
        REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_external_stock_levels_item FOREIGN KEY (tenant_id, organization_id, item_id)
        REFERENCES catalogue.items (tenant_id, organization_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_external_stock_levels_batch FOREIGN KEY (item_id, batch_id)
        REFERENCES catalogue.batches (item_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_external_stock_levels_location FOREIGN KEY (tenant_id, organization_id, storage_location_id)
        REFERENCES inventory.storage_locations (tenant_id, organization_id, id) ON DELETE SET NULL (storage_location_id),
    CONSTRAINT ck_external_stock_levels_source CHECK (source_system IN ('zoho'))
);
COMMENT ON TABLE inventory.external_stock_levels IS 'Latest stock figures reported by Zoho per item (× batch) × Zoho location. Snapshot for display/reconciliation, never ledger truth.';
CREATE UNIQUE INDEX uq_external_stock_levels_key ON inventory.external_stock_levels
    (tenant_id, organization_id, source_system, item_id, batch_id, external_location_id) NULLS NOT DISTINCT;


-- ---------------------------------------------------------------------------
-- inventory.v_batch_expiry — every lot with its expiry and ageing facts, policy applied.
--   days_to_expiry       effective_expires_on − today (negative = expired that many days ago)
--   shelf_life_left_pct  share of the lot's total shelf life still ahead
--   expiry_status        no_expiry | in_date | near_expiry | below_min_shelf_life | expired
--   is_sellable          FALSE for holds, QC pending/failed, inactive lots, and expiry per policy
--                        (expired: only when expired_sale_policy IN ('warn','allow'); 'override'
--                        lots are listed as not sellable — the line validator lets a permitted
--                        user override them explicitly)
--   ageing_days          today − first_received_on (fallback manufactured_on): how long WE have held it
-- Policy is resolved per (organization, item) at organization+item_group+item scope; warehouse
-- layers apply in v_item_availability, which has the warehouse.
-- ---------------------------------------------------------------------------
CREATE VIEW inventory.v_batch_expiry AS
SELECT b.tenant_id, b.organization_id, b.id AS batch_id, b.uuid AS batch_uuid, b.item_id,
       b.batch_number, b.effective_expires_on, b.manufactured_on, b.first_received_on,
       b.effective_expires_on - CURRENT_DATE AS days_to_expiry,
       CASE WHEN b.effective_expires_on IS NULL OR b.manufactured_on IS NULL
                 OR b.effective_expires_on <= b.manufactured_on THEN NULL
            ELSE round(100.0 * GREATEST(b.effective_expires_on - CURRENT_DATE, 0)
                       / (b.effective_expires_on - b.manufactured_on), 2) END AS shelf_life_left_pct,
       CURRENT_DATE - COALESCE(b.first_received_on, b.manufactured_on) AS ageing_days,
       CASE
           WHEN b.effective_expires_on IS NULL THEN 'no_expiry'
           WHEN b.effective_expires_on < CURRENT_DATE THEN 'expired'
           WHEN b.effective_expires_on - CURRENT_DATE < p.min_remaining_shelf_life_days
             OR (b.manufactured_on IS NOT NULL AND b.effective_expires_on > b.manufactured_on
                 AND 100.0 * (b.effective_expires_on - CURRENT_DATE) / (b.effective_expires_on - b.manufactured_on)
                     < p.min_remaining_shelf_life_pct) THEN 'below_min_shelf_life'
           WHEN b.effective_expires_on - CURRENT_DATE <= p.near_expiry_days THEN 'near_expiry'
           ELSE 'in_date'
       END AS expiry_status,
       (SELECT min(x) FROM unnest(p.ageing_bucket_days) x
         WHERE x >= GREATEST(b.effective_expires_on - CURRENT_DATE, 0)) AS expiry_bucket_days,
       p.expired_sale_policy,
       EXISTS (SELECT 1 FROM catalogue.batch_holds h
                WHERE h.batch_id = b.id AND h.released_at IS NULL AND h.deleted_at IS NULL) AS is_held,
       (b.status = 'active' AND b.qc_status IN ('not_required','passed')
        AND NOT EXISTS (SELECT 1 FROM catalogue.batch_holds h
                         WHERE h.batch_id = b.id AND h.released_at IS NULL AND h.deleted_at IS NULL)
        AND (b.effective_expires_on IS NULL
             OR (b.effective_expires_on >= CURRENT_DATE
                 AND b.effective_expires_on - CURRENT_DATE >= p.min_remaining_shelf_life_days
                 AND (b.manufactured_on IS NULL OR b.effective_expires_on <= b.manufactured_on
                      OR 100.0 * (b.effective_expires_on - CURRENT_DATE) / (b.effective_expires_on - b.manufactured_on)
                         >= p.min_remaining_shelf_life_pct))
             OR (b.effective_expires_on < CURRENT_DATE AND p.expired_sale_policy IN ('warn','allow')))
       ) AS is_sellable
  FROM catalogue.batches b
  CROSS JOIN LATERAL inventory.effective_stock_policy(b.tenant_id, b.organization_id, NULL, b.item_id) p
 WHERE b.deleted_at IS NULL;
COMMENT ON VIEW inventory.v_batch_expiry IS 'Lot expiry/ageing facts with the stock policy applied: days to expiry, % shelf life left, expiry status and bucket, held, sellable.';


-- ---------------------------------------------------------------------------
-- inventory.v_item_availability — stock per item × warehouse × batch with sellability:
--   on hand in 'available' status in locations that count as available (negative positions
--   included, so an allowed negative nets correctly), lot facts from v_batch_expiry, minus
--   reservations named for that lot.
-- inventory.v_item_warehouse_availability — the same rolled up per item × warehouse, netting
--   item-level reservations (batch NULL) too. This is what "can I promise 40 cartons?" reads.
-- Reads only; the allocation service applies the same predicates with FOR UPDATE on balances.
-- ---------------------------------------------------------------------------
CREATE VIEW inventory.v_item_availability AS
WITH on_hand AS (
    SELECT b.tenant_id, b.organization_id, b.item_id, b.batch_id,
           split_part(l.path, '/', 2)::bigint AS warehouse_id,
           sum(b.quantity_on_hand) AS quantity_on_hand
      FROM inventory.stock_balances b
      JOIN inventory.storage_locations l ON l.id = b.storage_location_id
     WHERE b.stock_status = 'available'
       AND b.quantity_on_hand <> 0
       AND l.counts_as_available AND l.deleted_at IS NULL
     GROUP BY 1, 2, 3, 4, 5
), reserved AS (
    SELECT r.item_id, r.batch_id, r.warehouse_id, sum(r.quantity_base) AS quantity_reserved
      FROM inventory.stock_reservations r
     WHERE r.status = 'active' AND r.deleted_at IS NULL AND r.batch_id IS NOT NULL
     GROUP BY 1, 2, 3
)
SELECT o.tenant_id, o.organization_id, o.item_id, o.batch_id, o.warehouse_id,
       o.quantity_on_hand,
       COALESCE(r.quantity_reserved, 0)                       AS quantity_reserved,
       o.quantity_on_hand - COALESCE(r.quantity_reserved, 0)  AS quantity_free,
       e.effective_expires_on, e.days_to_expiry, e.expiry_status, e.is_held,
       COALESCE(e.is_sellable, true)                          AS is_sellable
  FROM on_hand o
  LEFT JOIN reserved r ON r.item_id = o.item_id AND r.warehouse_id = o.warehouse_id AND r.batch_id = o.batch_id
  LEFT JOIN inventory.v_batch_expiry e ON e.batch_id = o.batch_id;
COMMENT ON VIEW inventory.v_item_availability IS 'Available-status stock per item × warehouse × batch with lot-level reservations, expiry status and sellability (policy applied).';

CREATE VIEW inventory.v_item_warehouse_availability AS
SELECT a.tenant_id, a.organization_id, a.item_id, a.warehouse_id,
       sum(a.quantity_on_hand)                                         AS quantity_on_hand,
       sum(a.quantity_on_hand) FILTER (WHERE a.is_sellable)            AS quantity_sellable,
       sum(a.quantity_reserved)
         + COALESCE((SELECT sum(r.quantity_base) FROM inventory.stock_reservations r
                      WHERE r.item_id = a.item_id AND r.warehouse_id = a.warehouse_id
                        AND r.batch_id IS NULL AND r.status = 'active' AND r.deleted_at IS NULL), 0)
                                                                       AS quantity_reserved,
       COALESCE(sum(a.quantity_free) FILTER (WHERE a.is_sellable), 0)
         - COALESCE((SELECT sum(r.quantity_base) FROM inventory.stock_reservations r
                      WHERE r.item_id = a.item_id AND r.warehouse_id = a.warehouse_id
                        AND r.batch_id IS NULL AND r.status = 'active' AND r.deleted_at IS NULL), 0)
                                                                       AS quantity_available,
       min(a.effective_expires_on) FILTER (WHERE a.is_sellable)        AS earliest_sellable_expiry,
       sum(a.quantity_on_hand) FILTER (WHERE a.expiry_status = 'near_expiry') AS quantity_near_expiry,
       sum(a.quantity_on_hand) FILTER (WHERE a.expiry_status = 'expired')     AS quantity_expired
  FROM inventory.v_item_availability a
 GROUP BY a.tenant_id, a.organization_id, a.item_id, a.warehouse_id;
COMMENT ON VIEW inventory.v_item_warehouse_availability IS 'Per item × warehouse: on hand, sellable, reserved (lot + item level), available to promise, earliest sellable expiry, near-expiry and expired quantities.';


-- ---------------------------------------------------------------------------
-- inventory.stock_ageing — how long current stock has been held, per item × warehouse × batch,
-- bucketed by the policy's ageing_bucket_days. FIFO attribution: the on-hand quantity is assumed
-- to be the most recent receipts ("last in still here"), walked newest-first until covered — the
-- standard ageing method for non-lot stock; for lots, receipts of that lot.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION inventory.stock_ageing(p_tenant_id bigint, p_organization_id bigint, p_as_of date DEFAULT CURRENT_DATE)
RETURNS TABLE (item_id bigint, warehouse_id bigint, batch_id bigint, quantity_base numeric,
               age_days integer, bucket_upper_days integer)
LANGUAGE sql STABLE AS $$
    WITH positions AS (
        SELECT b.item_id, b.batch_id, split_part(l.path, '/', 2)::bigint AS warehouse_id,
               sum(b.quantity_on_hand) AS on_hand
          FROM inventory.stock_balances b
          JOIN inventory.storage_locations l ON l.id = b.storage_location_id
         WHERE b.tenant_id = p_tenant_id AND b.organization_id = p_organization_id
         GROUP BY 1, 2, 3
        HAVING sum(b.quantity_on_hand) > 0
    ), receipts AS (
        SELECT e.item_id, e.batch_id, split_part(l.path, '/', 2)::bigint AS warehouse_id,
               e.business_date, e.quantity_base,
               sum(e.quantity_base) OVER (PARTITION BY e.item_id, e.batch_id, split_part(l.path, '/', 2)
                                          ORDER BY e.business_date DESC, e.id DESC) AS cum_newest_first
          FROM inventory.stock_ledger_entries e
          JOIN inventory.storage_locations l ON l.id = e.storage_location_id
         WHERE e.tenant_id = p_tenant_id AND e.organization_id = p_organization_id
           AND e.business_date <= p_as_of AND e.quantity_base > 0
           AND e.movement_type IN ('receipt','opening','sales_return','adjustment_in','transfer_in','assembly_produce','status_in')
    ), attributed AS (
        SELECT r.item_id, r.warehouse_id, r.batch_id,
               LEAST(r.quantity_base, p.on_hand - (r.cum_newest_first - r.quantity_base)) AS qty,
               p_as_of - r.business_date AS age_days
          FROM receipts r
          JOIN positions p ON p.item_id = r.item_id AND p.warehouse_id = r.warehouse_id
                          AND p.batch_id IS NOT DISTINCT FROM r.batch_id
         WHERE r.cum_newest_first - r.quantity_base < p.on_hand
    )
    SELECT a.item_id, a.warehouse_id, a.batch_id, a.qty, a.age_days,
           (SELECT min(x) FROM unnest(pol.ageing_bucket_days) x WHERE x >= a.age_days) AS bucket_upper_days
      FROM attributed a
      CROSS JOIN LATERAL inventory.effective_stock_policy(p_tenant_id, p_organization_id, a.warehouse_id, a.item_id) pol
$$;
COMMENT ON FUNCTION inventory.stock_ageing(bigint, bigint, date) IS
    'FIFO stock ageing per item × warehouse × batch with policy buckets (bucket_upper_days NULL = older than the last bucket). Transfers reset age at the receiving warehouse by design (transfer_in is a receipt there).';


-- ---------------------------------------------------------------------------
-- inventory.rebuild_balances — recompute the cache from the ledger for one item (or all when
-- NULL). The reconciliation job compares before/after and reports drift; it never "fixes" the
-- ledger.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION inventory.rebuild_balances(p_tenant_id bigint, p_item_id bigint DEFAULT NULL)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    v_rows integer;
BEGIN
    DELETE FROM inventory.stock_balances
     WHERE tenant_id = p_tenant_id AND (p_item_id IS NULL OR item_id = p_item_id);
    INSERT INTO inventory.stock_balances
           (tenant_id, organization_id, item_id, batch_id, storage_location_id, stock_status,
            quantity_on_hand, last_entry_at)
    SELECT tenant_id, organization_id, item_id, batch_id, storage_location_id, stock_status,
           sum(quantity_base), max(posted_at)
      FROM inventory.stock_ledger_entries
     WHERE tenant_id = p_tenant_id AND (p_item_id IS NULL OR item_id = p_item_id)
     GROUP BY tenant_id, organization_id, item_id, batch_id, storage_location_id, stock_status
    HAVING sum(quantity_base) <> 0;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END $$;


-- ============================================================================
-- §8. Additive changes to existing schemas
-- ============================================================================

-- Zoho manufacturers (Inventory, user-supplied payload: manufacturer_id, manufacturer, address,
-- telephone, email_id, mobile_no, gst_no, brand_fssai_no, importer_fssai_no) become core.manufacturers
-- through the crosswalk: a zoho_id echo, same as brands. Address → geo.place_links (owner
-- manufacturer, link type registered_office); gst_no / FSSAI numbers → manufacturer_identifiers.
ALTER TABLE core.manufacturers
    ADD COLUMN zoho_id text;
COMMENT ON COLUMN core.manufacturers.zoho_id IS 'Echo of Zoho manufacturer_id, written by the sync engine; identity of record is sync.sync_records.';
CREATE UNIQUE INDEX uq_manufacturers_zoho_id_live ON core.manufacturers (zoho_id)
    WHERE deleted_at IS NULL AND zoho_id IS NOT NULL;

-- Zoho separates a brand-owner FSSAI licence (brand_fssai_no) from an importer's
-- (importer_fssai_no); both are 14-digit FSSAI numbers.
ALTER TABLE core.manufacturer_identifiers DROP CONSTRAINT ck_manufacturer_identifiers_kind;
ALTER TABLE core.manufacturer_identifiers ADD CONSTRAINT ck_manufacturer_identifiers_kind CHECK (
    kind IS NULL OR kind IN ('gstin','pan','cin','fssai','fssai_importer','drug_manufacturing_licence',
                             'who_gmp','iso_certificate','gs1_company_prefix','duns','lei','other'));
ALTER TABLE core.manufacturer_identifiers DROP CONSTRAINT ck_manufacturer_identifiers_format;
ALTER TABLE core.manufacturer_identifiers ADD CONSTRAINT ck_manufacturer_identifiers_format CHECK (
    CASE kind
        WHEN 'gstin' THEN value_normalized ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'
        WHEN 'pan'   THEN value_normalized ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'
        WHEN 'cin'   THEN value_normalized ~ '^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
        WHEN 'fssai' THEN value_normalized ~ '^[0-9]{14}$'
        WHEN 'fssai_importer' THEN value_normalized ~ '^[0-9]{14}$'
        ELSE true
    END);

-- geo.places gets a (tenant_id, organization_id, id) scope key — created in §7 just before
-- inventory.storage_locations, its first referrer.


-- ============================================================================
-- §9. Mixin-generated indexes (exact Alembic autogenerate names) for every new entity table
-- ============================================================================
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT c.table_schema AS s, c.table_name AS n
          FROM information_schema.columns c
         WHERE c.table_schema IN ('catalogue','inventory','pricing')
           AND c.column_name = 'deleted_at'
           AND c.table_name IN (
               'units','packaging_types','sales_channels','item_groups','attributes','attribute_options',
               'products','product_attributes','items','item_merchandising','item_attribute_values',
               'item_units','item_identifiers','item_components','item_sales_channels','item_vendors',
               'batches','batch_holds',
               'schemes','scheme_targets','scheme_slabs','scheme_eligibility',
               'storage_locations','reason_codes','stock_movements','stock_movement_lines',
               'stock_reservations','replenishment_policies','stock_policies')
    LOOP
        EXECUTE format('CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I.%I (uuid)', 'ix_' || t.s || '_' || t.n || '_uuid', t.s, t.n);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I (deleted_at)', 'ix_' || t.s || '_' || t.n || '_deleted_at', t.s, t.n);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I (status)', 'ix_' || t.s || '_' || t.n || '_status', t.s, t.n);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I (tenant_id)', 'ix_' || t.s || '_' || t.n || '_tenant_id', t.s, t.n);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I (tenant_id, organization_id)', 'ix_' || t.n || '_tenant_org', t.s, t.n);
    END LOOP;
END $$;
-- LEDGER-class tables (stock_balances, external_stock_levels) get only their tenant indexes:
CREATE INDEX ix_inventory_stock_balances_tenant_id ON inventory.stock_balances (tenant_id);
CREATE INDEX ix_stock_balances_tenant_org ON inventory.stock_balances (tenant_id, organization_id);
CREATE INDEX ix_inventory_external_stock_levels_tenant_id ON inventory.external_stock_levels (tenant_id);
CREATE INDEX ix_external_stock_levels_tenant_org ON inventory.external_stock_levels (tenant_id, organization_id);


-- ============================================================================
-- §10. Seed data
-- ============================================================================

-- §10.1 GST UQC list (GLOBAL). Source: GSTN UQC master as published (Zoho Books India KB "unit
-- code list", ClearTax/Tally references) — re-verify against the GST portal before go-live.
INSERT INTO catalogue.uqc_codes (code, description, quantity_kind) VALUES
    ('BAG','Bags','count'), ('BAL','Bale','count'), ('BDL','Bundles','count'), ('BKL','Buckles','count'),
    ('BOU','Billions of units','count'), ('BOX','Box','count'), ('BTL','Bottles','count'), ('BUN','Bunches','count'),
    ('CAN','Cans','count'), ('CBM','Cubic meters','volume'), ('CCM','Cubic centimeters','volume'),
    ('CMS','Centimeters','length'), ('CTN','Cartons','count'), ('DOZ','Dozens','count'), ('DRM','Drums','count'),
    ('GGK','Great gross','count'), ('GMS','Grams','mass'), ('GRS','Gross','count'), ('GYD','Gross yards','length'),
    ('KGS','Kilograms','mass'), ('KLR','Kilolitre','volume'), ('KME','Kilometre','length'),
    ('LTR','Litres','volume'), ('MLT','Millilitre','volume'), ('MTR','Meters','length'), ('MTS','Metric ton','mass'),
    ('NOS','Numbers','count'), ('OTH','Others','other'), ('PAC','Packs','count'), ('PCS','Pieces','count'),
    ('PRS','Pairs','count'), ('QTL','Quintal','mass'), ('ROL','Rolls','count'), ('SET','Sets','count'),
    ('SQF','Square feet','area'), ('SQM','Square meters','area'), ('SQY','Square yards','area'),
    ('TBS','Tablets','count'), ('TGM','Ten gross','count'), ('THD','Thousands','count'), ('TON','Tonnes','mass'),
    ('TUB','Tubes','count'), ('UGS','US gallons','volume'), ('UNT','Units','count'), ('YDS','Yards','length')
ON CONFLICT (code) DO NOTHING;
-- NB: sources disagree on "Great gross" (GGK vs GGR). GGK is the code on the GST portal's
-- HSN-summary dropdown as commonly reproduced; verify (open question Q-UQC in README §8).

-- §10.2 Standard units per organization. Idempotent; called by the migration for every existing
-- organization and by the organization-provisioning hook for new ones. Zoho's units adopt these
-- rows by normalized code (README decision D-6).
CREATE OR REPLACE FUNCTION catalogue.seed_standard_units(p_tenant_id bigint, p_organization_id bigint)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    v_rows integer;
BEGIN
    INSERT INTO catalogue.units
           (tenant_id, organization_id, code, name, unit_class, uqc_code, decimal_places, si_factor, is_system, created_by_name)
    SELECT p_tenant_id, p_organization_id, v.code, v.name, v.unit_class, v.uqc, v.dp, v.si, true, 'system:migration'
      FROM (VALUES
        -- count / trade units
        ('pcs','Pieces','count','PCS',0,NULL::numeric), ('nos','Numbers','count','NOS',0,NULL),
        ('btl','Bottles','count','BTL',0,NULL), ('box','Box','count','BOX',0,NULL),
        ('ctn','Cartons','count','CTN',0,NULL), ('pac','Packs','count','PAC',0,NULL),
        ('strip','Strips','count','OTH',0,NULL), ('tab','Tablets','count','TBS',0,NULL),
        ('tube','Tubes','count','TUB',0,NULL), ('can','Cans','count','CAN',0,NULL),
        ('bag','Bags','count','BAG',0,NULL), ('doz','Dozens','count','DOZ',0,NULL),
        ('set','Sets','count','SET',0,NULL), ('roll','Rolls','count','ROL',0,NULL),
        -- mass (base g) — Zoho weight_units: kg, g, lb, oz
        ('g','Grams','mass','GMS',3,1), ('kg','Kilograms','mass','KGS',3,1000),
        ('mg','Milligrams','mass','OTH',3,0.001), ('lb','Pounds','mass','OTH',3,453.59237),
        ('oz','Ounces','mass','OTH',3,28.349523125),
        -- volume (base ml) — Zoho lists "l" among weight units; it resolves here
        ('ml','Millilitre','volume','MLT',3,1), ('l','Litres','volume','LTR',3,1000),
        -- length (base mm) — Zoho dimension units: cm, in (and m, mm)
        ('mm','Millimetre','length','OTH',2,1), ('cm','Centimetre','length','CMS',2,10),
        ('m','Metre','length','MTR',3,1000), ('in','Inch','length','OTH',2,25.4)
      ) AS v(code, name, unit_class, uqc, dp, si)
    ON CONFLICT (tenant_id, organization_id, code_normalized) WHERE deleted_at IS NULL DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END $$;

-- §10.3 Default reason codes per organization (idempotent).
CREATE OR REPLACE FUNCTION inventory.seed_reason_codes(p_tenant_id bigint, p_organization_id bigint)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    v_rows integer;
BEGIN
    INSERT INTO inventory.reason_codes
           (tenant_id, organization_id, code, name, applies_to, direction, requires_document, is_system, created_by_name)
    SELECT p_tenant_id, p_organization_id, v.code, v.name, v.applies_to, v.direction, v.doc, true, 'system:migration'
      FROM (VALUES
        ('opening_balance','Opening balance','adjustment','in',false),
        ('count_variance','Cycle-count variance','count','either',false),
        ('damaged_in_handling','Damaged in handling','write_off','out',false),
        ('expired','Expired stock','write_off','out',false),
        ('theft_loss','Theft / loss','write_off','out',true),
        ('found_stock','Found stock','adjustment','in',false),
        ('qc_failed','QC failed','hold','either',false),
        ('regulatory_hold','Regulatory hold','hold','either',true),
        ('recall','Manufacturer recall','hold','either',true),
        ('customer_return_saleable','Customer return — saleable','return','in',false),
        ('customer_return_damaged','Customer return — damaged','return','in',false),
        ('transfer','Inter-location transfer','transfer','either',false)
      ) AS v(code, name, applies_to, direction, doc)
    ON CONFLICT (tenant_id, organization_id, code) WHERE deleted_at IS NULL DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END $$;

-- §10.4 The organization's policy layer, written out explicitly (= the built-in defaults) so an
-- administrator sees and edits real values. Warehouse / item-group / item layers are created on demand.
CREATE OR REPLACE FUNCTION inventory.seed_stock_policy(p_tenant_id bigint, p_organization_id bigint)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    v_rows integer;
BEGIN
    INSERT INTO inventory.stock_policies
           (tenant_id, organization_id, scope_type, ledger_mode, allow_negative_stock, allow_negative_batch_stock,
            expired_sale_policy, near_expiry_days, min_remaining_shelf_life_days, min_remaining_shelf_life_pct,
            receipt_min_shelf_life_days, auto_mark_expired, allocation_strategy, ageing_bucket_days, created_by_name)
    VALUES (p_tenant_id, p_organization_id, 'organization', 'mirror', false, false,
            'block', 90, 0, 0, 0, true, 'fefo', ARRAY[30,60,90,180,365], 'system:migration')
    ON CONFLICT (tenant_id, organization_id, scope_type, warehouse_id, item_group_id, item_id)
        WHERE deleted_at IS NULL DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END $$;

DO $$
DECLARE
    o record;
BEGIN
    FOR o IN SELECT tenant_id, id FROM org_management.organizations WHERE deleted_at IS NULL LOOP
        PERFORM catalogue.seed_standard_units(o.tenant_id, o.id);
        PERFORM inventory.seed_reason_codes(o.tenant_id, o.id);
        PERFORM inventory.seed_stock_policy(o.tenant_id, o.id);
    END LOOP;
END $$;


-- ============================================================================
-- §11. Polymorphic registrations (what taxes/accounts/comments/documents/custom-fields/categories
-- need to know about the new entity classes). In the migrations these are the Python helpers
-- (taxes.registration.register_taxable_entity_type, accounting.registration.register_account_owner_type,
-- comments.registration.register_commentable_entity_type); this is their exact SQL effect.
-- ============================================================================
INSERT INTO core.entity_types (code, name, target_schema, target_table, created_by_name) VALUES
    ('item',            'Item',            'catalogue', 'items',            'system:migration'),
    ('product',         'Product',         'catalogue', 'products',         'system:migration'),
    ('batch',           'Batch',           'catalogue', 'batches',          'system:migration'),
    ('item_group',      'Item group',      'catalogue', 'item_groups',      'system:migration'),
    ('stock_movement',  'Stock movement',  'inventory', 'stock_movements',  'system:migration'),
    ('storage_location','Storage location','inventory', 'storage_locations','system:migration'),
    ('scheme',          'Scheme',          'pricing',   'schemes',          'system:migration')
ON CONFLICT (code) DO NOTHING;

-- Taxes: an item carries ONE tax per (intra/inter × sales/purchase) context, or an exemption
-- (Zoho item_tax_preferences, tax_exemption_id).
INSERT INTO tax.taxable_entity_types (entity_type_code, allows_multiple, allows_exemption, description, created_by_name)
VALUES ('item', false, true, 'Item GST preferences (Zoho item_tax_preferences / tax_exemption_id)', 'system:migration')
ON CONFLICT (entity_type_code) DO NOTHING;

-- Accounts: Zoho account_id / purchase_account_id / inventory_account_id; fall back to the organization.
INSERT INTO accounting.account_purpose_policies (entity_type_code, purpose_code, falls_back_to_organization, description, created_by_name)
VALUES ('item', 'sales', true, 'Zoho item account_id', 'system:migration'),
       ('item', 'purchase', true, 'Zoho item purchase_account_id', 'system:migration'),
       ('item', 'inventory_asset', true, 'Zoho item inventory_account_id', 'system:migration')
ON CONFLICT (entity_type_code, purpose_code) DO NOTHING;

-- Comments on items, products, batches and stock movements.
INSERT INTO comments.commentable_entity_types (entity_type_code, is_active, description, created_by_name)
VALUES ('item', true, NULL, 'system:migration'), ('product', true, NULL, 'system:migration'),
       ('batch', true, NULL, 'system:migration'), ('stock_movement', true, NULL, 'system:migration')
ON CONFLICT (entity_type_code) DO NOTHING;

-- Categories: whitelist `item` (and `product`) on the organization's Zoho category taxonomy is a
-- per-organization core.taxonomy_entity_types row, written by the items migration through
-- categories.service (not reproduced here: it depends on the taxonomy id of each organization).
-- Custom fields: owner types `item` and `batch` are the core.entity_types rows above;
-- extfields.field_definitions are learned from Zoho payloads (zoho_field_id) as for parties.
-- Documents (linkable_type item / product / batch / stock_movement) and media (model_type item /
-- product / item_group / batch) are open at the database level: only the Python enums change.

COMMIT;

-- ============================================================================
-- Run-after (not in the transaction): app-managed monthly partitions for the ledger, from the
-- earliest opening-balance month to three months ahead, e.g.
--   CREATE TABLE inventory.stock_ledger_entries_2026_10 PARTITION OF inventory.stock_ledger_entries
--       FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
-- inventory/partitions.py owns this (beat-free: called by the posting service when a month is
-- missing, plus a daily maintenance task), copying fieldops/partitions.py.
-- ============================================================================
-- End of file
