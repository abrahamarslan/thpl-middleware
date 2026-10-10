"""Catalogue phase 1 — masters: GST UQC codes, units, packaging types, sales channels, item groups,
variant attributes and their options.

    catalogue.uqc_codes          GLOBAL GSTN Unit Quantity Codes (seeded)
    catalogue.units              count + physical units per organization (standard set seeded)
    catalogue.packaging_types    packaging characteristics
    catalogue.sales_channels     route to market (zoho_code ↔ Zoho contact sales_channel)
    catalogue.item_groups        merchandising groups (tree)
    catalogue.attributes         variant axes …
    catalogue.attribute_options  … and their values

Every organization gets the standard units: existing ones here, new ones from the AFTER INSERT trigger
``trg_organizations_seed_catalogue`` on ``org_management.organizations`` (the database provisions it, so
no tenancy-core module has to import the catalogue).

The DDL is generated verbatim from the design file docs/implementation-plans/catalogue/catalogue_schema.sql
(§1, §2 up to products, §10.1, §10.2), so the migration and the reviewed design cannot drift. Statements
run one per ``execute`` (asyncpg runs one statement at a time).

Downgrade drops the trigger, the functions, the seven tables and the schema (lossy by nature).

Revision ID: 66d0b2e09e76
Revises: 5b8d2e71c4a9
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "66d0b2e09e76"
down_revision: str | None = "5b8d2e71c4a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = r"""
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
"""

_COMMENTS = r"""
COMMENT ON TABLE catalogue.uqc_codes IS 'GLOBAL: GST Unit Quantity Codes (GSTN list). Snapshotted on invoice lines for GSTR-1 / e-invoice.';
COMMENT ON COLUMN catalogue.uqc_codes.code IS NULL;
COMMENT ON COLUMN catalogue.uqc_codes.description IS NULL;
COMMENT ON COLUMN catalogue.uqc_codes.quantity_kind IS NULL;
COMMENT ON COLUMN catalogue.uqc_codes.is_active IS NULL;
COMMENT ON COLUMN catalogue.uqc_codes.created_at IS NULL;
COMMENT ON COLUMN catalogue.uqc_codes.updated_at IS NULL;
COMMENT ON TABLE catalogue.units IS 'Units of measure of one organization: count/trade and physical units (unit_class). Zoho crosswalk module `units`.';
COMMENT ON COLUMN catalogue.units.code IS 'Symbol as printed (pcs, box, kg, ml)';
COMMENT ON COLUMN catalogue.units.code_normalized IS 'STORED lower-cased trimmed code; uniqueness per organization';
COMMENT ON COLUMN catalogue.units.name IS NULL;
COMMENT ON COLUMN catalogue.units.plural_name IS NULL;
COMMENT ON COLUMN catalogue.units.unit_class IS 'count / mass / volume / length / area / time / other';
COMMENT ON COLUMN catalogue.units.uqc_code IS 'GST UQC this unit reports as; NULL = OTH at filing time';
COMMENT ON COLUMN catalogue.units.decimal_places IS NULL;
COMMENT ON COLUMN catalogue.units.si_factor IS 'Multiplier to the class base unit (g / ml / mm / mm2 / s); NULL for count units';
COMMENT ON COLUMN catalogue.units.is_system IS 'Seeded standard unit (catalogue.seed_standard_units)';
COMMENT ON COLUMN catalogue.units.zoho_id IS 'Echo of Zoho unit_id; identity of record is sync.sync_records';
COMMENT ON COLUMN catalogue.units.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.units.id IS NULL;
COMMENT ON COLUMN catalogue.units.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.units.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.units.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.units.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.units.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.units.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.units.status IS NULL;
COMMENT ON COLUMN catalogue.units.is_verified IS NULL;
COMMENT ON COLUMN catalogue.units.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.units.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.units.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.units.created_at IS NULL;
COMMENT ON COLUMN catalogue.units.updated_at IS NULL;
COMMENT ON COLUMN catalogue.units.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.units.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.units.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.packaging_types IS 'Packaging characteristics (carton, monocarton, shipper case, dangler). Quantities live on catalogue.item_units.';
COMMENT ON COLUMN catalogue.packaging_types.code IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.name IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.description IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.is_container IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.is_dangler IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.is_display_unit IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.is_stackable IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.stack_limit IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.handling_instructions IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.storage_requirements IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.standard_weight IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.weight_unit_id IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.standard_length IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.standard_width IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.standard_height IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.dimension_unit_id IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.icon IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.properties IS 'Material facts (board_gsm, flute, recyclable); the pasted metadata_ — renamed (SQLAlchemy trap)';
COMMENT ON COLUMN catalogue.packaging_types.valid_from IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.valid_to IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.packaging_types.id IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.packaging_types.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.packaging_types.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.packaging_types.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.packaging_types.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.packaging_types.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.packaging_types.status IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.is_verified IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.packaging_types.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.packaging_types.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.created_at IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.updated_at IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.packaging_types.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.packaging_types.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.sales_channels IS 'Sales channels (route to market). Local master; zoho_code maps the Zoho contact sales_channel string.';
COMMENT ON COLUMN catalogue.sales_channels.code IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.name IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.description IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.channel_kind IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.zoho_code IS 'Zoho contact sales_channel value this channel stands for (e.g. direct_sales)';
COMMENT ON COLUMN catalogue.sales_channels.position IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.sales_channels.id IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.sales_channels.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.sales_channels.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.sales_channels.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.sales_channels.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.sales_channels.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.sales_channels.status IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.is_verified IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.sales_channels.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.sales_channels.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.created_at IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.updated_at IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.sales_channels.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.sales_channels.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.item_groups IS 'Merchandising groups (menus, catalogues, offer targets). Distinct from core.categories and from Zoho item groups (= catalogue.products).';
COMMENT ON COLUMN catalogue.item_groups.code IS NULL;
COMMENT ON COLUMN catalogue.item_groups.name IS NULL;
COMMENT ON COLUMN catalogue.item_groups.description IS NULL;
COMMENT ON COLUMN catalogue.item_groups.parent_id IS 'Parent group; NULL = top level';
COMMENT ON COLUMN catalogue.item_groups.is_visible IS NULL;
COMMENT ON COLUMN catalogue.item_groups.show_in_menu IS NULL;
COMMENT ON COLUMN catalogue.item_groups.display_order IS NULL;
COMMENT ON COLUMN catalogue.item_groups.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.item_groups.id IS NULL;
COMMENT ON COLUMN catalogue.item_groups.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.item_groups.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.item_groups.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.item_groups.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.item_groups.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.item_groups.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.item_groups.status IS NULL;
COMMENT ON COLUMN catalogue.item_groups.is_verified IS NULL;
COMMENT ON COLUMN catalogue.item_groups.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.item_groups.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.item_groups.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.item_groups.created_at IS NULL;
COMMENT ON COLUMN catalogue.item_groups.updated_at IS NULL;
COMMENT ON COLUMN catalogue.item_groups.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.item_groups.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.item_groups.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.attributes IS 'Variant axes (volume, pack size, flavour). Values in attribute_options.';
COMMENT ON COLUMN catalogue.attributes.code IS NULL;
COMMENT ON COLUMN catalogue.attributes.name IS NULL;
COMMENT ON COLUMN catalogue.attributes.input_type IS NULL;
COMMENT ON COLUMN catalogue.attributes.unit_id IS 'Unit of a numeric axis (ml for Volume)';
COMMENT ON COLUMN catalogue.attributes.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.attributes.id IS NULL;
COMMENT ON COLUMN catalogue.attributes.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.attributes.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.attributes.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.attributes.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.attributes.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.attributes.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.attributes.status IS NULL;
COMMENT ON COLUMN catalogue.attributes.is_verified IS NULL;
COMMENT ON COLUMN catalogue.attributes.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.attributes.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.attributes.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.attributes.created_at IS NULL;
COMMENT ON COLUMN catalogue.attributes.updated_at IS NULL;
COMMENT ON COLUMN catalogue.attributes.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.attributes.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.attributes.deleted_reason IS 'Why it was deleted';
COMMENT ON TABLE catalogue.attribute_options IS 'Values of a variant axis.';
COMMENT ON COLUMN catalogue.attribute_options.attribute_id IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.value IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.value_normalized IS 'STORED; uniqueness per attribute';
COMMENT ON COLUMN catalogue.attribute_options.numeric_value IS 'Sortable number (95 for ''95 ml'')';
COMMENT ON COLUMN catalogue.attribute_options.swatch IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.position IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.uuid IS 'Time-ordered public reference id (PG18 uuidv7())';
COMMENT ON COLUMN catalogue.attribute_options.id IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.tenant_id IS 'Tenant isolation key';
COMMENT ON COLUMN catalogue.attribute_options.organization_id IS 'Organization within the tenant (required)';
COMMENT ON COLUMN catalogue.attribute_options.created_by IS 'users.id of the creator (NULL = system)';
COMMENT ON COLUMN catalogue.attribute_options.created_by_name IS 'Creator display name at the time';
COMMENT ON COLUMN catalogue.attribute_options.updated_by IS 'users.id of the last updater';
COMMENT ON COLUMN catalogue.attribute_options.updated_by_name IS 'Last updater display name at the time';
COMMENT ON COLUMN catalogue.attribute_options.status IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.is_verified IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.row_version IS 'Optimistic-lock counter (incremented on every update)';
COMMENT ON COLUMN catalogue.attribute_options.app_version IS 'App version that last wrote the row';
COMMENT ON COLUMN catalogue.attribute_options.app_metadata IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.created_at IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.updated_at IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.deleted_at IS NULL;
COMMENT ON COLUMN catalogue.attribute_options.deleted_by IS 'users.id who deleted it';
COMMENT ON COLUMN catalogue.attribute_options.deleted_reason IS 'Why it was deleted';
"""

_UQC_SEED = r"""
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
"""

_SEED_FUNCTION = r"""
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
"""

_PROVISIONING = (
    r"""
CREATE OR REPLACE FUNCTION catalogue.on_organization_created() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM catalogue.seed_standard_units(NEW.tenant_id, NEW.id);
    RETURN NEW;
END $$
""",
    "COMMENT ON FUNCTION catalogue.on_organization_created() IS "
    "'Gives every new organization the standard catalogue units (trg_organizations_seed_catalogue).'",
    "CREATE TRIGGER trg_organizations_seed_catalogue AFTER INSERT ON org_management.organizations "
    "FOR EACH ROW EXECUTE FUNCTION catalogue.on_organization_created()",
    "SELECT catalogue.seed_standard_units(o.tenant_id, o.id) FROM org_management.organizations o "
    "WHERE o.deleted_at IS NULL",
)

#: The mixin-generated indexes, with the names Alembic autogenerate emits.
_ENTITY_TABLES = ("units", "packaging_types", "sales_channels", "item_groups", "attributes", "attribute_options")


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
    op.execute("CREATE SCHEMA IF NOT EXISTS catalogue")
    op.execute("COMMENT ON SCHEMA catalogue IS "
               "'Item master: units, packaging, merchandising groups, variant attributes, items, batches.'")
    for statement in _statements(_TABLES):
        op.execute(statement)
    for statement in _statements(_COMMENTS):
        op.execute(statement)
    for table in _ENTITY_TABLES:
        op.execute(f"CREATE UNIQUE INDEX ix_catalogue_{table}_uuid ON catalogue.{table} (uuid)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_deleted_at ON catalogue.{table} (deleted_at)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_status ON catalogue.{table} (status)")
        op.execute(f"CREATE INDEX ix_catalogue_{table}_tenant_id ON catalogue.{table} (tenant_id)")
        op.execute(f"CREATE INDEX ix_{table}_tenant_org ON catalogue.{table} (tenant_id, organization_id)")
    for statement in _statements(_UQC_SEED) + _statements(_SEED_FUNCTION):
        op.execute(statement)
    for statement in _PROVISIONING:
        op.execute(statement)

    bind = op.get_bind()
    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_organizations_seed_catalogue ON org_management.organizations")
    op.execute("DROP FUNCTION IF EXISTS catalogue.on_organization_created()")
    op.execute("DROP FUNCTION IF EXISTS catalogue.seed_standard_units(bigint, bigint)")
    for table in ("attribute_options", "attributes", "item_groups", "sales_channels", "packaging_types",
                  "units", "uqc_codes"):
        op.execute(f"DROP TABLE IF EXISTS catalogue.{table}")
    op.execute("DROP SCHEMA IF EXISTS catalogue")
