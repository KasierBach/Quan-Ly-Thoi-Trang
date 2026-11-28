BEGIN;
SET LOCAL search_path = public, pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'));

-- Snapshot identities and variant labels so deleting a catalog row cannot erase an adjustment.
CREATE TABLE IF NOT EXISTS InventoryAdjustments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id INTEGER NOT NULL CHECK (product_id > 0),
    variant_id INTEGER NOT NULL CHECK (variant_id > 0),
    color_name VARCHAR(50) NOT NULL,
    size_name VARCHAR(50) NOT NULL,
    actor_id INTEGER NOT NULL CHECK (actor_id > 0),
    actor_name VARCHAR(255) NOT NULL,
    reason VARCHAR(300) NOT NULL CHECK (BTRIM(reason) <> ''),
    quantity_before INTEGER NOT NULL CHECK (quantity_before >= 0),
    quantity_after INTEGER NOT NULL CHECK (quantity_after >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (quantity_before <> quantity_after)
);
CREATE INDEX IF NOT EXISTS idx_inventory_adjustments_product
    ON InventoryAdjustments (product_id, id DESC);

COMMIT;
