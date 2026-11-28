BEGIN;
SET LOCAL search_path = public, pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'));

CREATE INDEX IF NOT EXISTS idx_customers_avatar_url ON Customers (avatar_url) WHERE avatar_url IS NOT NULL;

COMMIT;
