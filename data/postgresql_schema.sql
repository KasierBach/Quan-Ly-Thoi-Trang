-- 1. Tables (Use IF NOT EXISTS to prevent overwriting existing data)

-- Clear functions and views to avoid return type change errors
DROP VIEW IF EXISTS vw_AvailableProducts CASCADE;
DROP VIEW IF EXISTS vw_BestSellingProducts CASCADE;
DROP VIEW IF EXISTS vw_MonthlyRevenue CASCADE;
DROP VIEW IF EXISTS vw_CategoryRevenue CASCADE;
DROP FUNCTION IF EXISTS sp_SearchProducts CASCADE;
DROP FUNCTION IF EXISTS sp_AddProduct CASCADE;
DROP FUNCTION IF EXISTS sp_GetOrderDetails_Main CASCADE;
DROP FUNCTION IF EXISTS sp_GetOrderDetails_Items CASCADE;

-- Tables
CREATE TABLE IF NOT EXISTS Categories (
    CategoryID SERIAL PRIMARY KEY,
    CategoryName VARCHAR(100) NOT NULL UNIQUE,
    Description VARCHAR(255) NULL
);

CREATE TABLE IF NOT EXISTS Customers (
    CustomerID SERIAL PRIMARY KEY,
    FullName VARCHAR(255) NOT NULL,
    Email VARCHAR(255) NOT NULL UNIQUE,
    Password VARCHAR(255) NOT NULL,
    PhoneNumber VARCHAR(20) UNIQUE,
    Address VARCHAR(500) NULL,
    IsAdmin BOOLEAN DEFAULT FALSE,
    DarkModeEnabled BOOLEAN DEFAULT FALSE,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Products (
    ProductID SERIAL PRIMARY KEY,
    ProductName VARCHAR(255) NOT NULL,
    Description TEXT NULL,
    Price DECIMAL(18,2) NOT NULL,
    OriginalPrice DECIMAL(18,2) DEFAULT 0,
    CategoryID INT REFERENCES Categories(CategoryID),
    ImageURL VARCHAR(255) NULL,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Colors (
    ColorID SERIAL PRIMARY KEY,
    ColorName VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Sizes (
    SizeID SERIAL PRIMARY KEY,
    SizeName VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ProductVariants (
    VariantID SERIAL PRIMARY KEY,
    ProductID INT REFERENCES Products(ProductID),
    ColorID INT REFERENCES Colors(ColorID),
    SizeID INT REFERENCES Sizes(SizeID),
    Quantity INT NOT NULL DEFAULT 0,
    UNIQUE (ProductID, ColorID, SizeID)
);

CREATE TABLE IF NOT EXISTS Orders (
    OrderID SERIAL PRIMARY KEY,
    CustomerID INT REFERENCES Customers(CustomerID),
    OrderDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    TotalAmount DECIMAL(18,2) NOT NULL DEFAULT 0,
    Status VARCHAR(50) DEFAULT 'Pending',
    PaymentMethod VARCHAR(100) NULL,
    ShippingAddress VARCHAR(500) NULL
);

CREATE TABLE IF NOT EXISTS OrderDetails (
    OrderDetailID SERIAL PRIMARY KEY,
    OrderID INT REFERENCES Orders(OrderID) ON DELETE CASCADE,
    VariantID INT REFERENCES ProductVariants(VariantID),
    Quantity INT NOT NULL,
    Price DECIMAL(18,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS Wishlist (
    WishlistID SERIAL PRIMARY KEY,
    CustomerID INT REFERENCES Customers(CustomerID),
    ProductID INT REFERENCES Products(ProductID),
    AddedDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (CustomerID, ProductID)
);

CREATE TABLE IF NOT EXISTS Reviews (
    ReviewID SERIAL PRIMARY KEY,
    CustomerID INT REFERENCES Customers(CustomerID),
    ProductID INT REFERENCES Products(ProductID),
    Rating INT NOT NULL CHECK (Rating BETWEEN 1 AND 5),
    Comment TEXT NULL,
    ReviewDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (CustomerID, ProductID)
);

CREATE TABLE IF NOT EXISTS ContactMessages (
    MessageID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Email VARCHAR(255) NOT NULL,
    Subject VARCHAR(255) NULL,
    Message TEXT NOT NULL,
    SubmitDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Status VARCHAR(50) DEFAULT 'New'
);

CREATE TABLE IF NOT EXISTS NewsletterSubscribers (
    SubscriberID SERIAL PRIMARY KEY,
    Email VARCHAR(255) NOT NULL UNIQUE,
    SubscribeDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    IsActive BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ProductComments (
    CommentID SERIAL PRIMARY KEY,
    CustomerID INT REFERENCES Customers(CustomerID),
    ProductID INT REFERENCES Products(ProductID),
    Content TEXT NOT NULL,
    CommentDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    AdminReply TEXT NULL,
    ReplyDate TIMESTAMP NULL,
    IsVisible BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS PasswordResetTokens (
    TokenID SERIAL PRIMARY KEY,
    CustomerID INT REFERENCES Customers(CustomerID),
    Token VARCHAR(100) NOT NULL,
    ExpiryDate TIMESTAMP NOT NULL,
    IsUsed BOOLEAN DEFAULT FALSE,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- Views
-- =============================================

CREATE OR REPLACE VIEW vw_MonthlyRevenue AS
SELECT 
    EXTRACT(YEAR FROM OrderDate) AS Year,
    EXTRACT(MONTH FROM OrderDate) AS Month,
    SUM(TotalAmount) AS TotalRevenue,
    COUNT(OrderID) AS OrderCount
FROM 
    Orders
WHERE 
    Status != 'Cancelled'
GROUP BY 
    Year, Month;

CREATE OR REPLACE VIEW vw_CategoryRevenue AS
SELECT 
    c.CategoryID,
    c.CategoryName,
    SUM(od.Quantity * od.Price) AS TotalRevenue,
    SUM(od.Quantity) AS TotalQuantitySold
FROM 
    Categories c
    JOIN Products p ON c.CategoryID = p.CategoryID
    JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    JOIN OrderDetails od ON pv.VariantID = od.VariantID
    JOIN Orders o ON od.OrderID = o.OrderID
WHERE 
    o.Status != 'Cancelled'
GROUP BY 
    c.CategoryID, c.CategoryName;

CREATE OR REPLACE VIEW vw_AvailableProducts AS
SELECT 
    p.ProductID,
    p.ProductName,
    c.CategoryName,
    s.SizeName,
    cl.ColorName,
    pv.Quantity AS AvailableStock,
    p.Price,
    p.OriginalPrice
FROM 
    Products p
    JOIN Categories c ON p.CategoryID = c.CategoryID
    JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    JOIN Sizes s ON pv.SizeID = s.SizeID
    JOIN Colors cl ON pv.ColorID = cl.ColorID
WHERE 
    pv.Quantity > 0;

CREATE OR REPLACE VIEW vw_BestSellingProducts AS
SELECT
    p.ProductID,
    p.ProductName,
    SUM(od.Quantity) AS TotalSold,
    SUM(od.Quantity * od.Price) AS TotalRevenue,
    p.Price,
    p.OriginalPrice,
    c.CategoryName
FROM OrderDetails od
JOIN ProductVariants pv ON od.VariantID = pv.VariantID
JOIN Products p ON pv.ProductID = p.ProductID
JOIN Categories c ON p.CategoryID = c.CategoryID
GROUP BY p.ProductID, p.ProductName, p.Price, p.OriginalPrice, c.CategoryName
ORDER BY TotalSold DESC
LIMIT 10;

CREATE OR REPLACE VIEW vw_CustomerPurchaseHistory AS
SELECT 
    c.CustomerID,
    c.FullName,
    c.Email,
    o.OrderID,
    o.OrderDate,
    o.TotalAmount,
    o.Status,
    p.ProductName,
    cl.ColorName,
    s.SizeName,
    od.Quantity,
    od.Price,
    (od.Quantity * od.Price) AS Subtotal
FROM 
    Customers c
    JOIN Orders o ON c.CustomerID = o.CustomerID
    JOIN OrderDetails od ON o.OrderID = od.OrderID
    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
    JOIN Products p ON pv.ProductID = p.ProductID
    JOIN Colors cl ON pv.ColorID = cl.ColorID
    JOIN Sizes s ON pv.SizeID = s.SizeID;

CREATE OR REPLACE VIEW vw_ProductRatings AS
SELECT 
    p.ProductID,
    p.ProductName,
    COUNT(r.ReviewID) AS ReviewCount,
    AVG(CAST(r.Rating AS FLOAT)) AS AverageRating
FROM 
    Products p
    LEFT JOIN Reviews r ON p.ProductID = r.ProductID
GROUP BY 
    p.ProductID, p.ProductName;

-- =============================================
-- Functions (Replacing Stored Procedures)
-- =============================================

-- Function 1: Add customer
CREATE OR REPLACE FUNCTION sp_AddCustomer(
    p_FullName VARCHAR(255),
    p_Email VARCHAR(255),
    p_Password VARCHAR(255),
    p_PhoneNumber VARCHAR(20) DEFAULT NULL,
    p_Address VARCHAR(500) DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_CustomerID INT;
BEGIN
    IF EXISTS (SELECT 1 FROM Customers WHERE Email = p_Email) THEN
        RAISE EXCEPTION 'Email đã tồn tại trong hệ thống';
    END IF;
    
    IF p_PhoneNumber IS NOT NULL AND EXISTS (SELECT 1 FROM Customers WHERE PhoneNumber = p_PhoneNumber) THEN
        RAISE EXCEPTION 'Số điện thoại đã tồn tại trong hệ thống';
    END IF;
    
    INSERT INTO Customers (FullName, Email, Password, PhoneNumber, Address)
    VALUES (p_FullName, p_Email, p_Password, p_PhoneNumber, p_Address)
    RETURNING CustomerID INTO v_CustomerID;
    
    RETURN v_CustomerID;
END;
$$ LANGUAGE plpgsql;

-- Function 2: Create order
CREATE OR REPLACE FUNCTION sp_CreateOrder(
    p_CustomerID INT,
    p_PaymentMethod VARCHAR(100),
    p_ShippingAddress VARCHAR(500)
) RETURNS INT AS $$
DECLARE
    v_OrderID INT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Customers WHERE CustomerID = p_CustomerID) THEN
        RAISE EXCEPTION 'Khách hàng không tồn tại';
    END IF;
    
    INSERT INTO Orders (CustomerID, TotalAmount, Status, PaymentMethod, ShippingAddress)
    VALUES (p_CustomerID, 0, 'Pending', p_PaymentMethod, p_ShippingAddress)
    RETURNING OrderID INTO v_OrderID;
    
    RETURN v_OrderID;
END;
$$ LANGUAGE plpgsql;

-- Function 3: Add order detail
CREATE OR REPLACE FUNCTION sp_AddOrderDetail(
    p_OrderID INT,
    p_VariantID INT,
    p_Quantity INT
) RETURNS INT AS $$
DECLARE
    v_AvailableQuantity INT;
    v_CurrentPrice DECIMAL(18,2);
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = p_OrderID) THEN
        RAISE EXCEPTION 'Đơn hàng không tồn tại';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM ProductVariants WHERE VariantID = p_VariantID) THEN
        RAISE EXCEPTION 'Biến thể sản phẩm không tồn tại';
    END IF;
    
    SELECT Quantity INTO v_AvailableQuantity FROM ProductVariants WHERE VariantID = p_VariantID;
    
    IF v_AvailableQuantity < p_Quantity THEN
        RAISE EXCEPTION 'Số lượng sản phẩm không đủ. Hiện chỉ còn % sản phẩm.', v_AvailableQuantity;
    END IF;
    
    SELECT p.Price INTO v_CurrentPrice
    FROM Products p
    JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    WHERE pv.VariantID = p_VariantID;
    
    INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
    VALUES (p_OrderID, p_VariantID, p_Quantity, v_CurrentPrice);
    
    RETURN 0;
END;
$$ LANGUAGE plpgsql;

-- Function 4: Update order status
CREATE OR REPLACE FUNCTION sp_UpdateOrderStatus(
    p_OrderID INT,
    p_NewStatus VARCHAR(50)
) RETURNS INT AS $$
DECLARE
    v_CurrentStatus VARCHAR(50);
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = p_OrderID) THEN
        RAISE EXCEPTION 'Đơn hàng không tồn tại';
    END IF;
    
    IF p_NewStatus NOT IN ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled') THEN
        RAISE EXCEPTION 'Trạng thái đơn hàng không hợp lệ';
    END IF;
    
    SELECT Status INTO v_CurrentStatus FROM Orders WHERE OrderID = p_OrderID;
    
    IF v_CurrentStatus = 'Cancelled' AND p_NewStatus != 'Cancelled' THEN
        RAISE EXCEPTION 'Không thể thay đổi trạng thái của đơn hàng đã bị hủy';
    END IF;
    
    IF v_CurrentStatus = 'Delivered' AND p_NewStatus != 'Delivered' AND p_NewStatus != 'Cancelled' THEN
        RAISE EXCEPTION 'Không thể thay đổi trạng thái của đơn hàng đã giao';
    END IF;
    
    -- Inventory handling (Trigger trg_UpdateInventory On Status Change or handled by existing triggers)
    -- In T-SQL version, logic was here. In Postgres, we'll keep it consistent.
    
    IF p_NewStatus = 'Cancelled' AND v_CurrentStatus != 'Cancelled' THEN
        UPDATE ProductVariants pv
        SET Quantity = pv.Quantity + od.Quantity
        FROM OrderDetails od
        WHERE od.VariantID = pv.VariantID AND od.OrderID = p_OrderID;
    ELSIF v_CurrentStatus = 'Cancelled' AND p_NewStatus != 'Cancelled' THEN
        -- Check inventory
        IF EXISTS (
            SELECT 1
            FROM OrderDetails od
            JOIN ProductVariants pv ON od.VariantID = pv.VariantID
            WHERE od.OrderID = p_OrderID AND pv.Quantity < od.Quantity
        ) THEN
            RAISE EXCEPTION 'Không đủ tồn kho để khôi phục đơn hàng';
        END IF;
        
        UPDATE ProductVariants pv
        SET Quantity = pv.Quantity - od.Quantity
        FROM OrderDetails od
        WHERE od.VariantID = pv.VariantID AND od.OrderID = p_OrderID;
    END IF;
    
    UPDATE Orders SET Status = p_NewStatus WHERE OrderID = p_OrderID;
    
    RETURN 0;
END;
$$ LANGUAGE plpgsql;

-- Function 5: Search products (Returns Table)
CREATE OR REPLACE FUNCTION sp_SearchProducts(
    p_SearchTerm VARCHAR(255) DEFAULT NULL,
    p_CategoryID INT DEFAULT NULL,
    p_MinPrice DECIMAL(18,2) DEFAULT NULL,
    p_MaxPrice DECIMAL(18,2) DEFAULT NULL,
    p_ColorID INT DEFAULT NULL,
    p_SizeID INT DEFAULT NULL,
    p_InStockOnly BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    ProductID INT,
    ProductName VARCHAR(255),
    Description TEXT,
    Price DECIMAL(18,2),
    OriginalPrice DECIMAL(18,2),
    CategoryID INT,
    CategoryName VARCHAR(100)
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        p.ProductID,
        p.ProductName,
        p.Description,
        p.Price,
        p.OriginalPrice,
        c.CategoryID,
        c.CategoryName
    FROM 
        Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        LEFT JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    WHERE
        (p_SearchTerm IS NULL OR p.ProductName ILIKE '%' || p_SearchTerm || '%' OR p.Description ILIKE '%' || p_SearchTerm || '%')
        AND (p_CategoryID IS NULL OR p.CategoryID = p_CategoryID)
        AND (p_MinPrice IS NULL OR p.Price >= p_MinPrice)
        AND (p_MaxPrice IS NULL OR p.Price <= p_MaxPrice)
        AND (p_ColorID IS NULL OR EXISTS (
            SELECT 1 FROM ProductVariants v 
            WHERE v.ProductID = p.ProductID AND v.ColorID = p_ColorID
        ))
        AND (p_SizeID IS NULL OR EXISTS (
            SELECT 1 FROM ProductVariants v 
            WHERE v.ProductID = p.ProductID AND v.SizeID = p_SizeID
        ))
        AND (NOT p_InStockOnly OR EXISTS (
            SELECT 1 FROM ProductVariants v 
            WHERE v.ProductID = p.ProductID AND v.Quantity > 0
        ))
    ORDER BY
        p.ProductName;
END;
$$ LANGUAGE plpgsql;

-- Function 6: Get customer orders
CREATE OR REPLACE FUNCTION sp_GetCustomerOrders(p_CustomerID INT)
RETURNS TABLE (
    OrderID INT,
    OrderDate TIMESTAMP,
    TotalAmount DECIMAL(18,2),
    Status VARCHAR(50),
    PaymentMethod VARCHAR(100),
    ShippingAddress VARCHAR(500),
    TotalItems BIGINT
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Customers WHERE CustomerID = p_CustomerID) THEN
        RAISE EXCEPTION 'Khách hàng không tồn tại';
    END IF;
    
    RETURN QUERY
    SELECT 
        o.OrderID,
        o.OrderDate,
        o.TotalAmount,
        o.Status,
        o.PaymentMethod,
        o.ShippingAddress,
        COUNT(od.OrderDetailID) AS TotalItems
    FROM 
        Orders o
        LEFT JOIN OrderDetails od ON o.OrderID = od.OrderID
    WHERE 
        o.CustomerID = p_CustomerID
    GROUP BY 
        o.OrderID, o.OrderDate, o.TotalAmount, o.Status, o.PaymentMethod, o.ShippingAddress
    ORDER BY 
        o.OrderDate DESC;
END;
$$ LANGUAGE plpgsql;

-- Function 7: Get order details (Complex - returns multiple things)
-- In Postgres, we can't easily return two different result sets from one function call like T-SQL.
-- We'll split it or return it as a more complex JSON, but for simplicity in app.py, 
-- we might just call two separate queries if we want to avoid mass refactoring.
-- However, let's try to make a function that returns the main order info.
CREATE OR REPLACE FUNCTION sp_GetOrderDetails_Main(p_OrderID INT)
RETURNS TABLE (
    OrderID INT,
    OrderDate TIMESTAMP,
    TotalAmount DECIMAL(18,2),
    Status VARCHAR(50),
    PaymentMethod VARCHAR(100),
    ShippingAddress VARCHAR(500),
    CustomerID INT,
    CustomerName VARCHAR(255),
    CustomerEmail VARCHAR(255),
    CustomerPhone VARCHAR(20)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        o.OrderID,
        o.OrderDate,
        o.TotalAmount,
        o.Status,
        o.PaymentMethod,
        o.ShippingAddress,
        c.CustomerID,
        c.FullName,
        c.Email,
        c.PhoneNumber
    FROM 
        Orders o
        JOIN Customers c ON o.CustomerID = c.CustomerID
    WHERE 
        o.OrderID = p_OrderID;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_GetOrderDetails_Items(p_OrderID INT)
RETURNS TABLE (
    OrderDetailID INT,
    ProductID INT,
    ProductName VARCHAR(255),
    ColorName VARCHAR(50),
    SizeName VARCHAR(50),
    Quantity INT,
    Price DECIMAL(18,2),
    Subtotal DECIMAL(18,2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        od.OrderDetailID,
        p.ProductID,
        p.ProductName,
        cl.ColorName,
        s.SizeName,
        od.Quantity,
        od.Price,
        (od.Quantity * od.Price) AS Subtotal
    FROM 
        OrderDetails od
        JOIN ProductVariants pv ON od.VariantID = pv.VariantID
        JOIN Products p ON pv.ProductID = p.ProductID
        JOIN Colors cl ON pv.ColorID = cl.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
    WHERE 
        od.OrderID = p_OrderID;
END;
$$ LANGUAGE plpgsql;

-- Function 8: Add product
CREATE OR REPLACE FUNCTION sp_AddProduct(
    p_ProductName VARCHAR(255),
    p_Description TEXT,
    p_Price DECIMAL(18,2),
    p_OriginalPrice DECIMAL(18,2),
    p_CategoryID INT
) RETURNS INT AS $$
DECLARE
    v_ProductID INT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Categories WHERE CategoryID = p_CategoryID) THEN
        RAISE EXCEPTION 'Danh mục không tồn tại';
    END IF;
    
    INSERT INTO Products (ProductName, Description, Price, OriginalPrice, CategoryID)
    VALUES (p_ProductName, p_Description, p_Price, p_OriginalPrice, p_CategoryID)
    RETURNING ProductID INTO v_ProductID;
    
    RETURN v_ProductID;
END;
$$ LANGUAGE plpgsql;

-- Function 9: Add product variant
CREATE OR REPLACE FUNCTION sp_AddProductVariant(
    p_ProductID INT,
    p_ColorID INT,
    p_SizeID INT,
    p_Quantity INT
) RETURNS INT AS $$
DECLARE
    v_VariantID INT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Products WHERE ProductID = p_ProductID) THEN
        RAISE EXCEPTION 'Sản phẩm không tồn tại';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM Colors WHERE ColorID = p_ColorID) THEN
        RAISE EXCEPTION 'Màu sắc không tồn tại';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM Sizes WHERE SizeID = p_SizeID) THEN
        RAISE EXCEPTION 'Kích thước không tồn tại';
    END IF;
    
    INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
    VALUES (p_ProductID, p_ColorID, p_SizeID, p_Quantity)
    ON CONFLICT (ProductID, ColorID, SizeID)
    DO UPDATE SET Quantity = ProductVariants.Quantity + EXCLUDED.Quantity
    RETURNING VariantID INTO v_VariantID;
    
    RETURN v_VariantID;
END;
$$ LANGUAGE plpgsql;

-- Function 10: Get revenue by date range
CREATE OR REPLACE FUNCTION sp_GetRevenueByDateRange_Daily(
    p_StartDate DATE,
    p_EndDate DATE
) RETURNS TABLE (
    OrderDate DATE,
    OrderCount BIGINT,
    DailyRevenue DECIMAL(18,2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        CAST(o.OrderDate AS DATE) AS v_OrderDate,
        COUNT(o.OrderID) AS v_OrderCount,
        SUM(o.TotalAmount) AS v_DailyRevenue
    FROM 
        Orders o
    WHERE 
        CAST(o.OrderDate AS DATE) BETWEEN p_StartDate AND p_EndDate
        AND o.Status != 'Cancelled'
    GROUP BY 
        CAST(o.OrderDate AS DATE)
    ORDER BY 
        v_OrderDate;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_GetRevenueByDateRange_Category(
    p_StartDate DATE,
    p_EndDate DATE
) RETURNS TABLE (
    CategoryID INT,
    CategoryName VARCHAR(100),
    CategoryRevenue DECIMAL(18,2),
    TotalQuantitySold BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        c.CategoryID,
        c.CategoryName,
        SUM(od.Quantity * od.Price) AS v_CategoryRevenue,
        SUM(od.Quantity) AS v_TotalQuantitySold
    FROM 
        Categories c
        JOIN Products p ON c.CategoryID = p.CategoryID
        JOIN ProductVariants pv ON p.ProductID = pv.ProductID
        JOIN OrderDetails od ON pv.VariantID = od.VariantID
        JOIN Orders o ON od.OrderID = o.OrderID
    WHERE 
        CAST(o.OrderDate AS DATE) BETWEEN p_StartDate AND p_EndDate
        AND o.Status != 'Cancelled'
    GROUP BY 
        c.CategoryID, c.CategoryName
    ORDER BY 
        v_CategoryRevenue DESC;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- Triggers
-- =============================================

-- Trigger Function: Update inventory on order
CREATE OR REPLACE FUNCTION func_UpdateInventoryOnOrder() RETURNS TRIGGER AS $$
BEGIN
    -- This handles the "instead of insert" or "after insert" logic combined with checks.
    -- In T-SQL it was split.
    IF (TG_OP = 'INSERT') THEN
         -- Check inventory
        IF EXISTS (
            SELECT 1 FROM ProductVariants pv
            WHERE pv.VariantID = NEW.VariantID AND pv.Quantity < NEW.Quantity
        ) THEN
            RAISE EXCEPTION 'Không đủ tồn kho';
        END IF;

        -- Update inventory
        UPDATE ProductVariants pv
        SET Quantity = pv.Quantity - NEW.Quantity
        WHERE pv.VariantID = NEW.VariantID;
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        UPDATE ProductVariants pv
        SET Quantity = pv.Quantity + OLD.Quantity
        WHERE pv.VariantID = OLD.VariantID;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_UpdateInventory ON OrderDetails;
CREATE TRIGGER trg_UpdateInventory
BEFORE INSERT OR DELETE ON OrderDetails
FOR EACH ROW EXECUTE FUNCTION func_UpdateInventoryOnOrder();

-- Trigger Function: Update order total
CREATE OR REPLACE FUNCTION func_UpdateOrderTotal() RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        UPDATE Orders o
        SET TotalAmount = (SELECT COALESCE(SUM(Quantity * Price), 0) FROM OrderDetails WHERE OrderID = NEW.OrderID)
        WHERE o.OrderID = NEW.OrderID;
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        UPDATE Orders o
        SET TotalAmount = (SELECT COALESCE(SUM(Quantity * Price), 0) FROM OrderDetails WHERE OrderID = OLD.OrderID)
        WHERE o.OrderID = OLD.OrderID;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_UpdateOrderTotal ON OrderDetails;
CREATE TRIGGER trg_UpdateOrderTotal
AFTER INSERT OR UPDATE OR DELETE ON OrderDetails
FOR EACH ROW EXECUTE FUNCTION func_UpdateOrderTotal();
