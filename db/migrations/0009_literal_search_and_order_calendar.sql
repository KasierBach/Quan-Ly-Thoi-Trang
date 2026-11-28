BEGIN;
SET LOCAL search_path = public, pg_catalog;

CREATE OR REPLACE FUNCTION sp_SearchProducts(
    p_SearchTerm VARCHAR(255) DEFAULT NULL, p_CategoryID INT DEFAULT NULL,
    p_MinPrice DECIMAL(18,2) DEFAULT NULL, p_MaxPrice DECIMAL(18,2) DEFAULT NULL,
    p_ColorID INT DEFAULT NULL, p_SizeID INT DEFAULT NULL, p_InStockOnly BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    ProductID INT, ProductName VARCHAR(255), Description TEXT, Price DECIMAL(18,2),
    OriginalPrice DECIMAL(18,2), CategoryID INT, CategoryName VARCHAR(100), ImageURL VARCHAR(255)
) AS $$
BEGIN
    RETURN QUERY SELECT p.ProductID, p.ProductName, p.Description, p.Price,
                        p.OriginalPrice, c.CategoryID, c.CategoryName, p.ImageURL
    FROM Products p JOIN Categories c ON p.CategoryID = c.CategoryID
    WHERE (p_SearchTerm IS NULL OR strpos(lower(p.ProductName), lower(p_SearchTerm)) > 0
           OR strpos(lower(p.Description), lower(p_SearchTerm)) > 0)
      AND (p_CategoryID IS NULL OR p.CategoryID = p_CategoryID)
      AND (p_MinPrice IS NULL OR p.Price >= p_MinPrice)
      AND (p_MaxPrice IS NULL OR p.Price <= p_MaxPrice)
      AND ((p_ColorID IS NULL AND p_SizeID IS NULL AND NOT COALESCE(p_InStockOnly, FALSE))
           OR EXISTS (SELECT 1 FROM ProductVariants v WHERE v.ProductID = p.ProductID
                      AND (p_ColorID IS NULL OR v.ColorID = p_ColorID)
                      AND (p_SizeID IS NULL OR v.SizeID = p_SizeID)
                      AND (NOT COALESCE(p_InStockOnly, FALSE) OR v.Quantity > 0)))
    ORDER BY p.ProductName, p.ProductID;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE Orders ALTER COLUMN OrderDate SET DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Ho_Chi_Minh');
CREATE INDEX IF NOT EXISTS idx_orders_customer_date ON Orders(CustomerID, OrderDate DESC, OrderID DESC);

COMMIT;
