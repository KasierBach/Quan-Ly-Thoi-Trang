BEGIN;
SET LOCAL search_path = public, pg_catalog;

CREATE TABLE IF NOT EXISTS ProductGallery (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES Products(ProductID) ON DELETE CASCADE,
    image_url VARCHAR(255) NOT NULL UNIQUE,
    caption VARCHAR(80) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_gallery_product ON ProductGallery (product_id, id);
CREATE TABLE IF NOT EXISTS CategorySizeMeasurements (
    category_id INTEGER NOT NULL REFERENCES Categories(CategoryID) ON DELETE CASCADE,
    size_id INTEGER NOT NULL REFERENCES Sizes(SizeID) ON DELETE CASCADE,
    chest SMALLINT CHECK (chest BETWEEN 1 AND 999),
    waist SMALLINT CHECK (waist BETWEEN 1 AND 999),
    hips SMALLINT CHECK (hips BETWEEN 1 AND 999),
    PRIMARY KEY (category_id, size_id),
    CHECK (num_nonnulls(chest, waist, hips) > 0)
);
ALTER TABLE ProductVariants ADD COLUMN IF NOT EXISTS low_stock_threshold INTEGER
    NOT NULL DEFAULT 20 CHECK (low_stock_threshold >= 0);
CREATE INDEX IF NOT EXISTS idx_variants_low_stock ON ProductVariants(Quantity, VariantID)
    WHERE Quantity < low_stock_threshold;

CREATE TABLE IF NOT EXISTS OrderStatusEvents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES Orders(OrderID) ON DELETE CASCADE,
    previous_status VARCHAR(50),
    status VARCHAR(50) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    actor_id INTEGER,
    actor_name VARCHAR(255),
    actor_role VARCHAR(12) NOT NULL CHECK (actor_role IN ('customer', 'staff', 'system'))
);
CREATE INDEX IF NOT EXISTS idx_order_status_events_order ON OrderStatusEvents (order_id, id DESC);

CREATE OR REPLACE FUNCTION func_RecordOrderStatus() RETURNS TRIGGER AS $$
DECLARE
    changed_by INTEGER;
    changed_by_name VARCHAR(255);
    changed_by_role VARCHAR(12) := 'system';
    old_status VARCHAR(50);
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.Status IS NOT DISTINCT FROM NEW.Status THEN
            RETURN NEW;
        END IF;
        old_status := OLD.Status;
        changed_by := NULLIF(current_setting('thua2.order_actor_id', true), '')::INTEGER;
    ELSIF NEW.Status = 'Pending' THEN
        changed_by := NEW.CustomerID;
    END IF;

    IF changed_by IS NOT NULL THEN
        SELECT FullName, CASE WHEN TG_OP = 'UPDATE' AND (IsAdmin OR role = 'admin')
                         THEN 'staff' ELSE 'customer' END
        INTO changed_by_name, changed_by_role FROM Customers WHERE CustomerID = changed_by;
        IF NOT FOUND THEN
            changed_by_role := 'system';
        END IF;
    END IF;

    INSERT INTO OrderStatusEvents (order_id, previous_status, status, actor_id, actor_name, actor_role)
    VALUES (NEW.OrderID, old_status, NEW.Status, changed_by, changed_by_name, changed_by_role);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_RecordOrderStatus
    AFTER INSERT OR UPDATE OF Status ON Orders
    FOR EACH ROW EXECUTE FUNCTION func_RecordOrderStatus();

COMMIT;
