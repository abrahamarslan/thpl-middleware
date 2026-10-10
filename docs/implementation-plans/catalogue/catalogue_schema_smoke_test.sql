-- Behavioural smoke test for catalogue_schema.sql — everything inside one transaction that ROLLS BACK.
-- Run against a database where catalogue_schema.sql has been applied (e.g. a schema-only copy of dev):
--   psql -d <db> -f catalogue_schema_smoke_test.sql        → expect "failed 0"
-- P2/P4/P6 port these checks to pytest (08-build-plan.md §3); this file stays as the DDL's executable spec.
\set ON_ERROR_STOP 1
BEGIN;
CREATE TEMP TABLE results (check_name text, ok boolean, detail text);

DO $$
DECLARE
    t bigint; o bigint; pcs bigint; btl bigint; box bigint; ctn bigint;
    item_a bigint; item_b bigint; item_c bigint; l_pcs bigint; l_btl bigint; l_box bigint; l_ctn bigint;
    wh bigint; bin bigint; bat bigint; bat_old bigint; bat_m bigint; pl bigint;
    v numeric; d date; msg text; st text; b boolean;
BEGIN
    SELECT tenant_id, id INTO t, o FROM org_management.organizations LIMIT 1;
    SELECT id INTO pcs FROM catalogue.units WHERE organization_id = o AND code = 'pcs';
    SELECT id INTO btl FROM catalogue.units WHERE organization_id = o AND code = 'btl';
    SELECT id INTO box FROM catalogue.units WHERE organization_id = o AND code = 'box';
    SELECT id INTO ctn FROM catalogue.units WHERE organization_id = o AND code = 'ctn';
    INSERT INTO results VALUES ('seeded units', pcs IS NOT NULL AND ctn IS NOT NULL, (SELECT count(*)::text FROM catalogue.units));
    INSERT INTO results VALUES ('seeded org stock policy',
        EXISTS (SELECT 1 FROM inventory.stock_policies WHERE organization_id = o AND scope_type = 'organization'), '');

    -- ── packaging hierarchy ──────────────────────────────────────────────
    INSERT INTO catalogue.items (tenant_id, organization_id, name, sku, base_unit_id, track_mode, expiry_tracked, generic_name, alias_names)
    VALUES (t, o, 'Paracetamol 500', 'PARA-500', pcs, 'batch', true, 'Paracetamol 500 mg', ARRAY['Crocin']) RETURNING id INTO item_a;
    INSERT INTO catalogue.item_units (tenant_id, organization_id, item_id, unit_id, is_base, base_factor) VALUES (t,o,item_a,pcs,true,1) RETURNING id INTO l_pcs;
    INSERT INTO catalogue.item_units (tenant_id, organization_id, item_id, unit_id, contents_item_unit_id, contents_qty, base_factor) VALUES (t,o,item_a,btl,l_pcs,10,0.000001) RETURNING id INTO l_btl;
    INSERT INTO catalogue.item_units (tenant_id, organization_id, item_id, unit_id, contents_item_unit_id, contents_qty, base_factor) VALUES (t,o,item_a,box,l_btl,12,0.000001) RETURNING id INTO l_box;
    INSERT INTO catalogue.item_units (tenant_id, organization_id, item_id, unit_id, contents_item_unit_id, contents_qty, base_factor) VALUES (t,o,item_a,ctn,l_box,8,0.000001) RETURNING id INTO l_ctn;
    SELECT base_factor INTO v FROM catalogue.item_units WHERE id = l_ctn;
    INSERT INTO results VALUES ('CTN base_factor = 960', v = 960, v::text);
    INSERT INTO results VALUES ('convert 1 CTN -> BTL = 96', catalogue.convert_quantity(1, l_ctn, l_btl) = 96, catalogue.convert_quantity(1, l_ctn, l_btl)::text);
    SELECT derive_price INTO b FROM catalogue.item_units WHERE id = l_ctn;
    INSERT INTO results VALUES ('AUoM needs an explicit price by default', NOT b, b::text);

    UPDATE catalogue.items SET zoho_item_unit_id = l_btl WHERE id = item_a;
    BEGIN
        INSERT INTO catalogue.items (tenant_id, organization_id, name, base_unit_id) VALUES (t,o,'probe',pcs) RETURNING id INTO item_c;
        UPDATE catalogue.items SET zoho_item_unit_id = l_btl WHERE id = item_c;
        INSERT INTO results VALUES ('zoho unit level must be the item''s own', false, 'accepted');
    EXCEPTION WHEN foreign_key_violation THEN
        INSERT INTO results VALUES ('zoho unit level must be the item''s own', true, SQLERRM);
    END;

    BEGIN
        UPDATE catalogue.item_units SET contents_qty = 10 WHERE id = l_ctn;
        INSERT INTO results VALUES ('structure immutable', false, 'update accepted');
    EXCEPTION WHEN check_violation THEN
        GET STACKED DIAGNOSTICS st = PG_EXCEPTION_HINT;
        INSERT INTO results VALUES ('structure immutable', st = 'catalogue_item_unit_immutable', st);
    END;
    BEGIN
        UPDATE catalogue.item_units SET valid_to = CURRENT_DATE + 1 WHERE id = l_box;
        INSERT INTO results VALUES ('cannot retire contained level', false, 'accepted');
    EXCEPTION WHEN foreign_key_violation THEN
        INSERT INTO results VALUES ('cannot retire contained level', true, SQLERRM);
    END;
    BEGIN
        INSERT INTO catalogue.item_units (tenant_id, organization_id, item_id, unit_id, is_base, base_factor) VALUES (t,o,item_a,btl,true,1);
        INSERT INTO results VALUES ('base unit must match item', false, 'accepted');
    EXCEPTION WHEN check_violation OR unique_violation THEN
        INSERT INTO results VALUES ('base unit must match item', true, SQLERRM);
    END;
    BEGIN
        UPDATE catalogue.items SET base_unit_id = btl WHERE id = item_a;
        INSERT INTO results VALUES ('base unit locked by hierarchy', false, 'accepted');
    EXCEPTION WHEN check_violation THEN
        INSERT INTO results VALUES ('base unit locked by hierarchy', true, SQLERRM);
    END;

    -- ── identifiers & components ─────────────────────────────────────────
    INSERT INTO catalogue.item_identifiers (tenant_id, organization_id, item_id, item_unit_id, kind, value, is_primary)
    VALUES (t,o,item_a,l_ctn,'gtin','18901207010015',true);
    BEGIN
        INSERT INTO catalogue.item_identifiers (tenant_id, organization_id, item_id, kind, value) VALUES (t,o,item_a,'barcode',' 1890120 7010015');
        INSERT INTO results VALUES ('scannable code unique', false, 'accepted');
    EXCEPTION WHEN unique_violation THEN
        INSERT INTO results VALUES ('scannable code unique', true, SQLERRM);
    END;
    INSERT INTO catalogue.items (tenant_id, organization_id, name, base_unit_id, composition, is_inventory_tracked)
    VALUES (t, o, 'Kit B', pcs, 'kit', false) RETURNING id INTO item_b;
    INSERT INTO catalogue.item_components (tenant_id, organization_id, parent_item_id, component_item_id, role, quantity)
    VALUES (t,o,item_b,item_a,'kit_member',2);
    BEGIN
        INSERT INTO catalogue.item_components (tenant_id, organization_id, parent_item_id, component_item_id, role, quantity)
        VALUES (t,o,item_a,item_b,'assembly_component',1);
        INSERT INTO results VALUES ('component cycle refused', false, 'accepted');
    EXCEPTION WHEN check_violation THEN
        INSERT INTO results VALUES ('component cycle refused', true, SQLERRM);
    END;
    BEGIN
        UPDATE catalogue.items SET is_inventory_tracked = true WHERE id = item_b;
        INSERT INTO results VALUES ('kit not stocked', false, 'accepted');
    EXCEPTION WHEN check_violation THEN
        INSERT INTO results VALUES ('kit not stocked', true, SQLERRM);
    END;

    -- ── batches & expiry ─────────────────────────────────────────────────
    INSERT INTO catalogue.batches (tenant_id, organization_id, item_id, batch_number, manufactured_on, expires_on, first_received_on)
    VALUES (t,o,item_a,'b-2026 01', CURRENT_DATE - 300, CURRENT_DATE + 365, CURRENT_DATE - 45) RETURNING id INTO bat;
    BEGIN
        INSERT INTO catalogue.batches (tenant_id, organization_id, item_id, batch_number) VALUES (t,o,item_a,'B-202601');
        INSERT INTO results VALUES ('batch number unique (normalized)', false, 'accepted');
    EXCEPTION WHEN unique_violation THEN
        INSERT INTO results VALUES ('batch number unique (normalized)', true, SQLERRM);
    END;
    INSERT INTO catalogue.batches (tenant_id, organization_id, item_id, batch_number, expires_on, expiry_precision)
    VALUES (t,o,item_a,'M-0327','2027-03-01','month') RETURNING id INTO bat_m;
    SELECT effective_expires_on INTO d FROM catalogue.batches WHERE id = bat_m;
    INSERT INTO results VALUES ('EXP 03/2027 = 2027-03-31', d = DATE '2027-03-31', d::text);

    INSERT INTO catalogue.batches (tenant_id, organization_id, item_id, batch_number, manufactured_on, expires_on)
    VALUES (t,o,item_a,'OLD-1', CURRENT_DATE - 800, CURRENT_DATE - 5) RETURNING id INTO bat_old;
    SELECT expiry_status || '/' || is_sellable INTO msg FROM inventory.v_batch_expiry WHERE batch_id = bat_old;
    INSERT INTO results VALUES ('expired lot blocked by default', msg = 'expired/false', msg);
    INSERT INTO inventory.stock_policies (tenant_id, organization_id, scope_type, item_id, expired_sale_policy)
    VALUES (t,o,'item',item_a,'warn');
    SELECT expiry_status || '/' || is_sellable INTO msg FROM inventory.v_batch_expiry WHERE batch_id = bat_old;
    INSERT INTO results VALUES ('expired lot sellable when item policy = warn', msg = 'expired/true', msg);
    UPDATE inventory.stock_policies SET expired_sale_policy = NULL, min_remaining_shelf_life_days = 400
     WHERE item_id = item_a AND scope_type = 'item';
    SELECT expiry_status || '/' || is_sellable INTO msg FROM inventory.v_batch_expiry WHERE batch_id = bat;
    INSERT INTO results VALUES ('shelf-life rule (item layer) blocks a 365-day lot', msg = 'below_min_shelf_life/false', msg);
    UPDATE inventory.stock_policies SET min_remaining_shelf_life_days = NULL WHERE item_id = item_a AND scope_type = 'item';
    SELECT expiry_status INTO msg FROM inventory.v_batch_expiry WHERE batch_id = bat;
    INSERT INTO results VALUES ('lot back in date after rule removed', msg = 'in_date', msg);

    -- ── storage, ledger mode, ledger, balances ───────────────────────────
    INSERT INTO inventory.storage_locations (tenant_id, organization_id, code, name, location_type) VALUES (t,o,'GDH','Godhra WH','warehouse') RETURNING id INTO wh;
    INSERT INTO inventory.storage_locations (tenant_id, organization_id, parent_id, code, name, location_type) VALUES (t,o,wh,'A-01','Bin A-01','bin') RETURNING id INTO bin;
    SELECT path INTO msg FROM inventory.storage_locations WHERE id = bin;
    INSERT INTO results VALUES ('location path', msg = '/' || wh || '/' || bin || '/', msg);

    BEGIN
        INSERT INTO inventory.stock_ledger_entries (tenant_id, organization_id, business_date, item_id, batch_id, storage_location_id,
               quantity_base, movement_type, source_type, source_id, source_line_id)
        VALUES (t,o,CURRENT_DATE,item_a,bat,bin,10,'opening','stock_movement',1,1);
        INSERT INTO results VALUES ('mirror mode refuses posting', false, 'accepted');
    EXCEPTION WHEN object_not_in_prerequisite_state THEN
        INSERT INTO results VALUES ('mirror mode refuses posting', true, SQLERRM);
    END;
    UPDATE inventory.stock_policies SET ledger_mode = 'authoritative' WHERE organization_id = o AND scope_type = 'organization';

    INSERT INTO inventory.stock_ledger_entries (tenant_id, organization_id, business_date, item_id, batch_id, storage_location_id,
           quantity_base, item_unit_id, unit_code, quantity_in_unit, conversion_factor, movement_type, source_type, source_id, source_line_id)
    VALUES (t,o,CURRENT_DATE - 45,item_a,bat,bin,1920,l_ctn,'ctn',2,960,'opening','stock_movement',1,1);
    INSERT INTO inventory.stock_balances (tenant_id, organization_id, item_id, batch_id, storage_location_id, stock_status, quantity_on_hand)
    VALUES (t,o,item_a,bat,bin,'available',1920);
    BEGIN
        UPDATE inventory.stock_ledger_entries SET quantity_base = 1 WHERE item_id = item_a;
        INSERT INTO results VALUES ('ledger immutable', false, 'accepted');
    EXCEPTION WHEN insufficient_privilege THEN
        INSERT INTO results VALUES ('ledger immutable', true, SQLERRM);
    END;
    BEGIN
        INSERT INTO inventory.stock_ledger_entries (tenant_id, organization_id, business_date, item_id, batch_id, storage_location_id,
               quantity_base, movement_type, source_type, source_id, source_line_id)
        VALUES (t,o,CURRENT_DATE - 45,item_a,bat,bin,1920,'opening','stock_movement',1,1);
        INSERT INTO results VALUES ('ledger leg idempotent', false, 'accepted');
    EXCEPTION WHEN unique_violation THEN
        INSERT INTO results VALUES ('ledger leg idempotent', true, SQLERRM);
    END;

    -- negative stock: refused by default, allowed by policy, never for a named lot unless that flag is set
    BEGIN
        UPDATE inventory.stock_balances SET quantity_on_hand = quantity_on_hand - 2000 WHERE item_id = item_a;
        INSERT INTO results VALUES ('negative stock refused by default', false, 'accepted');
    EXCEPTION WHEN check_violation THEN
        INSERT INTO results VALUES ('negative stock refused by default', true, SQLERRM);
    END;
    UPDATE inventory.stock_policies SET allow_negative_stock = true WHERE organization_id = o AND scope_type = 'organization';
    BEGIN
        UPDATE inventory.stock_balances SET quantity_on_hand = quantity_on_hand - 2000 WHERE item_id = item_a AND batch_id = bat;
        INSERT INTO results VALUES ('named lot still cannot go negative', false, 'accepted');
    EXCEPTION WHEN check_violation THEN
        INSERT INTO results VALUES ('named lot still cannot go negative', true, SQLERRM);
    END;
    INSERT INTO inventory.stock_balances (tenant_id, organization_id, item_id, batch_id, storage_location_id, stock_status, quantity_on_hand)
    VALUES (t,o,item_b,NULL,bin,'available',-5);
    INSERT INTO results VALUES ('non-lot negative allowed by org policy', true, '-5 accepted');
    UPDATE inventory.stock_balances SET quantity_on_hand = -2 WHERE item_id = item_b;
    INSERT INTO results VALUES ('negative moving towards zero always allowed', true, '-5 -> -2');
    BEGIN
        INSERT INTO inventory.stock_balances (tenant_id, organization_id, item_id, batch_id, storage_location_id, stock_status, quantity_on_hand)
        VALUES (t,o,item_b,NULL,bin,'damaged',-1);
        INSERT INTO results VALUES ('only available status may be negative', false, 'accepted');
    EXCEPTION WHEN check_violation THEN
        INSERT INTO results VALUES ('only available status may be negative', true, SQLERRM);
    END;
    UPDATE inventory.stock_policies SET allow_negative_stock = false WHERE organization_id = o AND scope_type = 'organization';

    -- availability
    INSERT INTO inventory.stock_reservations (tenant_id, organization_id, item_id, warehouse_id, batch_id, quantity_base, source_type, source_id, source_line_id)
    VALUES (t,o,item_a,wh,bat,120,'stock_movement',99,1);
    INSERT INTO inventory.stock_reservations (tenant_id, organization_id, item_id, warehouse_id, quantity_base, source_type, source_id, source_line_id)
    VALUES (t,o,item_a,wh,80,'stock_movement',99,2);
    SELECT quantity_available INTO v FROM inventory.v_item_warehouse_availability WHERE item_id = item_a;
    INSERT INTO results VALUES ('available to promise = 1920 - 120 - 80', v = 1720, v::text);
    INSERT INTO catalogue.batch_holds (tenant_id, organization_id, batch_id, hold_type) VALUES (t,o,bat,'recall');
    SELECT COALESCE(quantity_available, 0) INTO v FROM inventory.v_item_warehouse_availability WHERE item_id = item_a;
    INSERT INTO results VALUES ('held lot not available', v <= 0, v::text);

    -- ageing
    SELECT age_days::numeric INTO v FROM inventory.stock_ageing(t, o) WHERE item_id = item_a;
    INSERT INTO results VALUES ('stock ageing = 45 days', v = 45, v::text);
    SELECT bucket_upper_days::numeric INTO v FROM inventory.stock_ageing(t, o) WHERE item_id = item_a;
    INSERT INTO results VALUES ('ageing bucket 31-60', v = 60, v::text);

    SELECT inventory.rebuild_balances(t, item_a) INTO v;
    SELECT quantity_on_hand INTO v FROM inventory.stock_balances WHERE item_id = item_a;
    INSERT INTO results VALUES ('rebuild from ledger', v = 1920, v::text);

    -- ── pricing ──────────────────────────────────────────────────────────
    INSERT INTO pricing.price_lists (tenant_id, organization_id, name, price_list_type, sales_or_purchase_type)
    VALUES (t,o,'Trade','per_item','sales') RETURNING id INTO pl;
    INSERT INTO pricing.price_list_items (tenant_id, organization_id, price_list_id, item_id, item_unit_id, rate, valid_from, valid_to)
    VALUES (t,o,pl,item_a,l_ctn,1000,'2026-01-01','2026-07-01');
    INSERT INTO pricing.price_list_items (tenant_id, organization_id, price_list_id, item_id, item_unit_id, rate, valid_from)
    VALUES (t,o,pl,item_a,l_ctn,950,'2026-07-01');
    INSERT INTO results VALUES ('consecutive carton price windows', true, '');
    BEGIN
        INSERT INTO pricing.price_list_items (tenant_id, organization_id, price_list_id, item_id, item_unit_id, rate, valid_from)
        VALUES (t,o,pl,item_a,l_ctn,900,'2026-06-15');
        INSERT INTO results VALUES ('overlapping price window refused', false, 'accepted');
    EXCEPTION WHEN exclusion_violation THEN
        INSERT INTO results VALUES ('overlapping price window refused', true, SQLERRM);
    END;

    INSERT INTO pricing.schemes (tenant_id, organization_id, code, name, scheme_type, valid_from) VALUES (t,o,'PARA-10+1','10+1 cartons','free_goods',CURRENT_DATE);
    INSERT INTO pricing.scheme_targets (tenant_id, organization_id, scheme_id, target_type, target_id)
        SELECT t,o,id,'item_unit',l_ctn FROM pricing.schemes WHERE code = 'PARA-10+1';
    INSERT INTO pricing.scheme_slabs (tenant_id, organization_id, scheme_id, min_quantity, free_quantity, is_repeating)
        SELECT t,o,id,10,1,true FROM pricing.schemes WHERE code = 'PARA-10+1';
    BEGIN
        INSERT INTO pricing.scheme_slabs (tenant_id, organization_id, scheme_id, min_quantity, free_quantity, discount_percent)
            SELECT t,o,id,5,1,5 FROM pricing.schemes WHERE code = 'PARA-10+1';
        INSERT INTO results VALUES ('one reward per slab', false, 'accepted');
    EXCEPTION WHEN check_violation THEN
        INSERT INTO results VALUES ('one reward per slab', true, SQLERRM);
    END;
END $$;

SELECT check_name, ok, left(detail, 80) AS detail FROM results;
SELECT count(*) FILTER (WHERE ok) AS passed, count(*) FILTER (WHERE NOT ok) AS failed FROM results;
ROLLBACK;
