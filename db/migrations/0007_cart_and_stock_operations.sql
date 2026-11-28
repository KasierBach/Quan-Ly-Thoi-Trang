BEGIN;
SET LOCAL search_path = public, pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'));

CREATE TABLE IF NOT EXISTS ShoppingCarts (
    cart_id UUID PRIMARY KEY,
    revision UUID NOT NULL,
    items JSONB NOT NULL CHECK (jsonb_typeof(items) = 'array'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE InventoryAdjustments ADD COLUMN IF NOT EXISTS operation_key UUID;
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_adjustments_operation
    ON InventoryAdjustments (actor_id, operation_key) WHERE operation_key IS NOT NULL;

COMMIT;
