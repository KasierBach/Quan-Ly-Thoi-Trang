-- Existing orders keep a NULL key. A reviewed checkout can create one order.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'));

ALTER TABLE Orders ADD COLUMN IF NOT EXISTS checkout_key UUID;
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_checkout_key ON Orders (checkout_key);

COMMIT;
