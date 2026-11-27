-- Reconstructed for main aa0f131e60d4489eea1b16b753d220cd87d34ce3 (2026-04-17).
-- Inputs ONLY: ignored Jan-2026 .data/postgresql_schema.sql (749 lines) and
-- .data/chat_migration.sql (141 lines), then contracts in main app SQL.
-- No newer tracked migration, customer export, or production connection used.
-- PostgreSQL 14+; CREATE OR REPLACE TRIGGER avoids destructive drop/recreate.
-- Replay adds missing schema and replaces callable definitions, never data.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'));

CREATE TABLE IF NOT EXISTS Categories (
    CategoryID SERIAL PRIMARY KEY,
    CategoryName VARCHAR(100) NOT NULL UNIQUE,
    Description VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS Customers (
    CustomerID SERIAL PRIMARY KEY,
    FullName VARCHAR(255) NOT NULL,
    Email VARCHAR(255) NOT NULL UNIQUE,
    Password VARCHAR(255) NOT NULL,
    PhoneNumber VARCHAR(20) UNIQUE,
    Address VARCHAR(500),
    IsAdmin BOOLEAN DEFAULT FALSE,
    DarkModeEnabled BOOLEAN DEFAULT FALSE,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Main auth uses Gender/DateOfBirth; avatar_url is canonical for auth + chat.
-- The application exposes AvatarUrl as an output alias, not a second column.
ALTER TABLE Customers ADD COLUMN IF NOT EXISTS Gender VARCHAR(20);
ALTER TABLE Customers ADD COLUMN IF NOT EXISTS DateOfBirth DATE;
ALTER TABLE Customers ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE Customers ADD COLUMN IF NOT EXISTS bio TEXT;
ALTER TABLE Customers ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP;
ALTER TABLE Customers ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'customer';
ALTER TABLE Customers ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 1;

-- Phase 5 OAuth compatibility (schema only; no live application here).
-- NULL explicitly disables password authentication; never a dummy password.
ALTER TABLE Customers ALTER COLUMN Password DROP NOT NULL;
CREATE TABLE IF NOT EXISTS OAuthIdentities (
    identity_id BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES Customers(CustomerID) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL CHECK (provider IN ('google', 'github')),
    issuer VARCHAR(255) NOT NULL,
    subject VARCHAR(255) NOT NULL CHECK (length(subject) > 0),
    email VARCHAR(254) NOT NULL,
    email_verified BOOLEAN NOT NULL CHECK (email_verified IS TRUE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, issuer, subject),
    UNIQUE (customer_id, provider),
    CHECK ((provider = 'google' AND issuer = 'https://accounts.google.com')
        OR (provider = 'github' AND issuer = 'https://github.com'))
);
-- Server one-use state + temporary PKCE material, never provider tokens/secrets.
CREATE TABLE IF NOT EXISTS OAuthStates (
    state_digest CHAR(64) PRIMARY KEY CHECK (state_digest ~ '^[0-9a-f]{64}$'),
    binding_digest CHAR(64) NOT NULL CHECK (binding_digest ~ '^[0-9a-f]{64}$'),
    purpose VARCHAR(20) NOT NULL CHECK (purpose IN ('authorization', 'reauth')),
    auth_data JSONB NOT NULL CHECK (jsonb_typeof(auth_data) = 'object'),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expiry ON OAuthStates (expires_at);

CREATE TABLE IF NOT EXISTS Products (
    ProductID SERIAL PRIMARY KEY,
    ProductName VARCHAR(255) NOT NULL,
    Description TEXT,
    Price DECIMAL(18,2) NOT NULL,
    OriginalPrice DECIMAL(18,2) DEFAULT 0,
    CategoryID INT NOT NULL REFERENCES Categories(CategoryID),
    ImageURL VARCHAR(255),
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
    ProductID INT NOT NULL REFERENCES Products(ProductID),
    ColorID INT NOT NULL REFERENCES Colors(ColorID),
    SizeID INT NOT NULL REFERENCES Sizes(SizeID),
    Quantity INT NOT NULL DEFAULT 0,
    UNIQUE (ProductID, ColorID, SizeID)
);
CREATE TABLE IF NOT EXISTS Orders (
    OrderID SERIAL PRIMARY KEY,
    CustomerID INT NOT NULL REFERENCES Customers(CustomerID),
    OrderDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    TotalAmount DECIMAL(18,2) NOT NULL DEFAULT 0,
    Status VARCHAR(50) NOT NULL DEFAULT 'Pending',
    PaymentMethod VARCHAR(100),
    ShippingAddress VARCHAR(500)
);
ALTER TABLE Orders ADD COLUMN IF NOT EXISTS recipient_name VARCHAR(255);
ALTER TABLE Orders ADD COLUMN IF NOT EXISTS recipient_phone VARCHAR(20);
ALTER TABLE Orders ADD COLUMN IF NOT EXISTS recipient_email VARCHAR(254);
ALTER TABLE Orders ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE Orders ADD COLUMN IF NOT EXISTS checkout_key UUID;
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_checkout_key ON Orders (checkout_key);
CREATE TABLE IF NOT EXISTS OrderDetails (
    OrderDetailID SERIAL PRIMARY KEY,
    OrderID INT NOT NULL REFERENCES Orders(OrderID) ON DELETE CASCADE,
    VariantID INT NOT NULL REFERENCES ProductVariants(VariantID),
    Quantity INT NOT NULL,
    Price DECIMAL(18,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS Wishlist (
    WishlistID SERIAL PRIMARY KEY,
    CustomerID INT NOT NULL REFERENCES Customers(CustomerID),
    ProductID INT NOT NULL REFERENCES Products(ProductID),
    AddedDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (CustomerID, ProductID)
);
CREATE TABLE IF NOT EXISTS Reviews (
    ReviewID SERIAL PRIMARY KEY,
    CustomerID INT NOT NULL REFERENCES Customers(CustomerID),
    ProductID INT NOT NULL REFERENCES Products(ProductID),
    Rating INT NOT NULL CHECK (Rating BETWEEN 1 AND 5),
    Comment TEXT,
    ReviewDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (CustomerID, ProductID)
);
CREATE TABLE IF NOT EXISTS ContactMessages (
    MessageID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Email VARCHAR(255) NOT NULL,
    Subject VARCHAR(255),
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
    CustomerID INT NOT NULL REFERENCES Customers(CustomerID),
    ProductID INT NOT NULL REFERENCES Products(ProductID),
    Content TEXT NOT NULL,
    CommentDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    AdminReply TEXT,
    ReplyDate TIMESTAMP,
    IsVisible BOOLEAN DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS PasswordResetTokens (
    TokenID SERIAL PRIMARY KEY,
    CustomerID INT NOT NULL REFERENCES Customers(CustomerID),
    Token VARCHAR(100) NOT NULL CONSTRAINT passwordresettokens_sha256 CHECK (Token::text ~ '^[0-9a-f]{64}$'),
    ExpiryDate TIMESTAMP NOT NULL,
    IsUsed BOOLEAN DEFAULT FALSE,
    CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Preserve the old legacy-session + advanced-conversation chat models.
CREATE TABLE IF NOT EXISTS Messages (
    id SERIAL PRIMARY KEY,
    sender_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    session_id VARCHAR(100) NOT NULL,
    user_id INT REFERENCES Customers(CustomerID),
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS Conversations (
    id SERIAL PRIMARY KEY,
    type VARCHAR(20) NOT NULL DEFAULT 'support',
    name VARCHAR(255),
    avatar_url TEXT,
    created_by INT REFERENCES Customers(CustomerID) ON DELETE RESTRICT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- These settings are referenced by main but absent from the old migration.
ALTER TABLE Conversations ADD COLUMN IF NOT EXISTS theme_color VARCHAR(20) DEFAULT '#0084ff';
ALTER TABLE Conversations ADD COLUMN IF NOT EXISTS default_emoji VARCHAR(50) DEFAULT '👍';
CREATE TABLE IF NOT EXISTS Participants (
    id SERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES Conversations(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES Customers(CustomerID) ON DELETE RESTRICT,
    role VARCHAR(20) DEFAULT 'member',
    nickname VARCHAR(100),
    is_muted BOOLEAN DEFAULT FALSE,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_read_at TIMESTAMP,
    UNIQUE (conversation_id, user_id)
);
ALTER TABLE Messages ADD COLUMN IF NOT EXISTS conversation_id INT REFERENCES Conversations(id) ON DELETE CASCADE;
ALTER TABLE Messages ADD COLUMN IF NOT EXISTS message_type VARCHAR(20) DEFAULT 'text';
ALTER TABLE Messages ADD COLUMN IF NOT EXISTS reply_to_id INT REFERENCES Messages(id) ON DELETE SET NULL;
ALTER TABLE Messages ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
ALTER TABLE Messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE Messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP;
CREATE TABLE IF NOT EXISTS Attachments (
    id SERIAL PRIMARY KEY,
    message_id INT NOT NULL REFERENCES Messages(id) ON DELETE CASCADE,
    file_url TEXT NOT NULL,
    file_name VARCHAR(255),
    file_type VARCHAR(50),
    mime_type VARCHAR(100),
    file_size BIGINT,
    thumbnail_url TEXT,
    width INT,
    height INT,
    duration INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS Reactions (
    id SERIAL PRIMARY KEY,
    message_id INT NOT NULL REFERENCES Messages(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES Customers(CustomerID) ON DELETE RESTRICT,
    emoji VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (message_id, user_id, emoji)
);
CREATE TABLE IF NOT EXISTS PinnedMessages (
    id SERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES Conversations(id) ON DELETE CASCADE,
    message_id INT NOT NULL REFERENCES Messages(id) ON DELETE CASCADE,
    pinned_by INT REFERENCES Customers(CustomerID) ON DELETE RESTRICT,
    pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (conversation_id, message_id)
);
ALTER TABLE Attachments ADD COLUMN IF NOT EXISTS storage_name TEXT;

-- NOT VALID keeps existing legacy rows untouched. PostgreSQL still enforces
-- these constraints for every subsequent INSERT/UPDATE. Conflicting existing
-- unique emails/tokens fail this transaction instead of being silently removed.
DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('customers', 'customers_auth_version_positive', 'auth_version IS NOT NULL AND auth_version >= 1'),
        ('products', 'products_nonnegative_price', 'Price >= 0 AND (OriginalPrice IS NULL OR OriginalPrice >= 0)'),
        ('products', 'products_finite_price', 'Price <> ''NaN''::NUMERIC AND (OriginalPrice IS NULL OR OriginalPrice <> ''NaN''::NUMERIC)'),
        ('products', 'products_category_required', 'CategoryID IS NOT NULL'),
        ('productvariants', 'productvariants_nonnegative_quantity', 'Quantity >= 0'),
        ('productvariants', 'productvariants_references_required', 'ProductID IS NOT NULL AND ColorID IS NOT NULL AND SizeID IS NOT NULL'),
        ('orders', 'orders_customer_required', 'CustomerID IS NOT NULL'),
        ('orders', 'orders_valid_status', 'Status IS NOT NULL AND Status IN (''Pending'', ''Processing'', ''Shipped'', ''Delivered'', ''Cancelled'')'),
        ('orders', 'orders_nonnegative_total', 'TotalAmount >= 0'),
        ('orders', 'orders_finite_total', 'TotalAmount <> ''NaN''::NUMERIC'),
        ('orderdetails', 'orderdetails_positive_quantity', 'Quantity > 0'),
        ('orderdetails', 'orderdetails_nonnegative_price', 'Price >= 0'),
        ('orderdetails', 'orderdetails_finite_price', 'Price <> ''NaN''::NUMERIC'),
        ('orderdetails', 'orderdetails_references_required', 'OrderID IS NOT NULL AND VariantID IS NOT NULL'),
        ('passwordresettokens', 'passwordresettokens_sha256', 'Token::text ~ ''^[0-9a-f]{64}$'''),
        ('conversations', 'conversations_valid_type', 'type IN (''private'', ''group'', ''support'')'),
        ('participants', 'participants_valid_role', 'role IS NOT NULL AND role IN (''member'', ''admin'', ''owner'')'),
        ('participants', 'participants_references_required', 'conversation_id IS NOT NULL AND user_id IS NOT NULL'),
        ('attachments', 'attachments_nonnegative_metadata', '(file_size IS NULL OR file_size >= 0) AND (width IS NULL OR width > 0) AND (height IS NULL OR height > 0) AND (duration IS NULL OR duration >= 0)')
    ) AS constraints(table_name, constraint_name, expression)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = ('public.' || item.table_name)::regclass
              AND conname = item.constraint_name
        ) THEN
            EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (%s) NOT VALID',
                           item.table_name, item.constraint_name, item.expression);
        END IF;
    END LOOP;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_email_lower ON Customers (lower(Email));
CREATE UNIQUE INDEX IF NOT EXISTS idx_newsletter_email_lower ON NewsletterSubscribers (lower(Email));
CREATE UNIQUE INDEX IF NOT EXISTS idx_passwordreset_token ON PasswordResetTokens(Token);
CREATE INDEX IF NOT EXISTS idx_passwordreset_customer ON PasswordResetTokens(CustomerID);
CREATE INDEX IF NOT EXISTS idx_products_category ON Products(CategoryID);
CREATE INDEX IF NOT EXISTS idx_products_name ON Products(ProductName);
CREATE INDEX IF NOT EXISTS idx_products_price ON Products(Price);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON Orders(CustomerID);
CREATE INDEX IF NOT EXISTS idx_orders_date ON Orders(OrderDate DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON Orders(Status);
CREATE INDEX IF NOT EXISTS idx_orderdetails_order ON OrderDetails(OrderID);
CREATE INDEX IF NOT EXISTS idx_orderdetails_variant ON OrderDetails(VariantID);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON Reviews(ProductID);
CREATE INDEX IF NOT EXISTS idx_productcomments_product ON ProductComments(ProductID);
CREATE INDEX IF NOT EXISTS idx_productvariants_product ON ProductVariants(ProductID);
CREATE INDEX IF NOT EXISTS idx_wishlist_customer ON Wishlist(CustomerID);
CREATE INDEX IF NOT EXISTS idx_messages_session ON Messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON Messages(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_type ON Conversations(type);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON Conversations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_participants_conversation ON Participants(conversation_id);
CREATE INDEX IF NOT EXISTS idx_participants_user ON Participants(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON Messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON Messages(reply_to_id);
CREATE INDEX IF NOT EXISTS idx_messages_type ON Messages(message_type);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_page ON Messages(conversation_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON Attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_attachments_type ON Attachments(file_type);
CREATE INDEX IF NOT EXISTS idx_reactions_message ON Reactions(message_id);
CREATE INDEX IF NOT EXISTS idx_reactions_user ON Reactions(user_id);
CREATE INDEX IF NOT EXISTS idx_pinned_conversation ON PinnedMessages(conversation_id);

-- All financial views/functions recognize revenue only on delivery.
-- Column names/order/types retain the original ReportService contracts.
CREATE OR REPLACE VIEW vw_MonthlyRevenue AS
SELECT EXTRACT(YEAR FROM OrderDate) AS Year,
       EXTRACT(MONTH FROM OrderDate) AS Month,
       SUM(TotalAmount) AS TotalRevenue, COUNT(OrderID) AS OrderCount
FROM Orders WHERE Status = 'Delivered'
GROUP BY Year, Month;
CREATE OR REPLACE VIEW vw_CategoryRevenue AS
SELECT c.CategoryID, c.CategoryName, SUM(od.Quantity * od.Price) AS TotalRevenue,
       SUM(od.Quantity) AS TotalQuantitySold
FROM Categories c
JOIN Products p ON c.CategoryID = p.CategoryID
JOIN ProductVariants pv ON p.ProductID = pv.ProductID
JOIN OrderDetails od ON pv.VariantID = od.VariantID
JOIN Orders o ON od.OrderID = o.OrderID
WHERE o.Status = 'Delivered'
GROUP BY c.CategoryID, c.CategoryName;
CREATE OR REPLACE VIEW vw_AvailableProducts AS
SELECT p.ProductID, p.ProductName, c.CategoryName, s.SizeName, cl.ColorName,
       pv.Quantity AS AvailableStock, p.Price, p.OriginalPrice
FROM Products p
JOIN Categories c ON p.CategoryID = c.CategoryID
JOIN ProductVariants pv ON p.ProductID = pv.ProductID
JOIN Sizes s ON pv.SizeID = s.SizeID
JOIN Colors cl ON pv.ColorID = cl.ColorID
WHERE pv.Quantity > 0;
CREATE OR REPLACE VIEW vw_BestSellingProducts AS
SELECT p.ProductID, p.ProductName, SUM(od.Quantity) AS TotalSold,
       SUM(od.Quantity * od.Price) AS TotalRevenue, p.Price, p.OriginalPrice, c.CategoryName
FROM OrderDetails od
JOIN Orders o ON od.OrderID = o.OrderID
JOIN ProductVariants pv ON od.VariantID = pv.VariantID
JOIN Products p ON pv.ProductID = p.ProductID
JOIN Categories c ON p.CategoryID = c.CategoryID
WHERE o.Status = 'Delivered'
GROUP BY p.ProductID, p.ProductName, p.Price, p.OriginalPrice, c.CategoryName
ORDER BY TotalSold DESC, p.ProductID LIMIT 10;
CREATE OR REPLACE VIEW vw_CustomerPurchaseHistory AS
SELECT c.CustomerID, c.FullName, c.Email, o.OrderID, o.OrderDate, o.TotalAmount,
       o.Status, p.ProductName, cl.ColorName, s.SizeName, od.Quantity, od.Price,
       (od.Quantity * od.Price) AS Subtotal
FROM Customers c
JOIN Orders o ON c.CustomerID = o.CustomerID
JOIN OrderDetails od ON o.OrderID = od.OrderID
JOIN ProductVariants pv ON od.VariantID = pv.VariantID
JOIN Products p ON pv.ProductID = p.ProductID
JOIN Colors cl ON pv.ColorID = cl.ColorID
JOIN Sizes s ON pv.SizeID = s.SizeID;
CREATE OR REPLACE VIEW vw_ProductRatings AS
SELECT p.ProductID, p.ProductName, COUNT(r.ReviewID) AS ReviewCount,
       AVG(CAST(r.Rating AS FLOAT)) AS AverageRating
FROM Products p LEFT JOIN Reviews r ON p.ProductID = r.ProductID
GROUP BY p.ProductID, p.ProductName;
CREATE OR REPLACE VIEW vw_ConversationSummary AS
SELECT c.id AS conversation_id, c.type, c.name, c.avatar_url, c.created_at,
       (SELECT COUNT(*) FROM Participants p WHERE p.conversation_id = c.id) AS member_count,
       (SELECT COUNT(*) FROM Messages m WHERE m.conversation_id = c.id AND m.is_deleted = FALSE) AS message_count,
       (SELECT m.content FROM Messages m WHERE m.conversation_id = c.id AND m.is_deleted = FALSE
        ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message,
       (SELECT m.created_at FROM Messages m WHERE m.conversation_id = c.id AND m.is_deleted = FALSE
        ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message_at
FROM Conversations c;

CREATE OR REPLACE FUNCTION sp_AddCustomer(
    p_FullName VARCHAR(255), p_Email VARCHAR(255), p_Password VARCHAR(255),
    p_PhoneNumber VARCHAR(20) DEFAULT NULL, p_Address VARCHAR(500) DEFAULT NULL
) RETURNS INT AS $$
DECLARE v_CustomerID INT;
BEGIN
    -- Let UNIQUE violations retain SQLSTATE 23505 for the auth error contract.
    INSERT INTO Customers (FullName, Email, Password, PhoneNumber, Address)
    VALUES (p_FullName, lower(btrim(p_Email)), p_Password, NULLIF(btrim(p_PhoneNumber), ''), p_Address)
    RETURNING CustomerID INTO v_CustomerID;
    RETURN v_CustomerID;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_CreateOrder(
    p_CustomerID INT, p_PaymentMethod VARCHAR(100), p_ShippingAddress VARCHAR(500)
) RETURNS INT AS $$
DECLARE v_OrderID INT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Customers WHERE CustomerID = p_CustomerID) THEN
        RAISE EXCEPTION 'Customer does not exist' USING ERRCODE = '23503';
    END IF;
    INSERT INTO Orders (CustomerID, TotalAmount, Status, PaymentMethod, ShippingAddress)
    VALUES (p_CustomerID, 0, 'Pending', p_PaymentMethod, p_ShippingAddress)
    RETURNING OrderID INTO v_OrderID;
    RETURN v_OrderID;
END;
$$ LANGUAGE plpgsql;

-- The order row is always locked before stock is read/written. The trigger,
-- not both trigger + function, owns the decrement and total recomputation.
CREATE OR REPLACE FUNCTION sp_AddOrderDetail(
    p_OrderID INT, p_VariantID INT, p_Quantity INT
) RETURNS INT AS $$
DECLARE v_CurrentPrice DECIMAL(18,2); v_Status VARCHAR(50);
BEGIN
    IF p_Quantity IS NULL OR p_Quantity <= 0 THEN
        RAISE EXCEPTION 'Order quantity must be positive' USING ERRCODE = '23514';
    END IF;
    SELECT o.Status INTO v_Status FROM Orders o WHERE o.OrderID = p_OrderID FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Order does not exist' USING ERRCODE = '23503';
    END IF;
    IF v_Status <> 'Pending' THEN
        RAISE EXCEPTION 'Only Pending order details may change' USING ERRCODE = '23514';
    END IF;
    SELECT p.Price INTO v_CurrentPrice FROM Products p
    JOIN ProductVariants pv ON p.ProductID = pv.ProductID WHERE pv.VariantID = p_VariantID;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Product variant does not exist' USING ERRCODE = '23503';
    END IF;
    INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
    VALUES (p_OrderID, p_VariantID, p_Quantity, v_CurrentPrice);
    RETURN 0;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_UpdateOrderStatus(
    p_OrderID INT, p_NewStatus VARCHAR(50)
) RETURNS INT AS $$
DECLARE v_CurrentStatus VARCHAR(50);
BEGIN
    IF p_NewStatus IS NULL OR p_NewStatus NOT IN ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled') THEN
        RAISE EXCEPTION 'Invalid order status' USING ERRCODE = '23514';
    END IF;
    SELECT o.Status INTO v_CurrentStatus FROM Orders o WHERE o.OrderID = p_OrderID FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Order does not exist' USING ERRCODE = '23503';
    END IF;
    IF v_CurrentStatus = p_NewStatus THEN RETURN 0; END IF;
    -- func_GuardOrderLifecycle serializes cancellation and validates transitions
    -- for this function AND direct UPDATE statements.
    UPDATE Orders SET Status = p_NewStatus WHERE OrderID = p_OrderID;
    RETURN 0;
END;
$$ LANGUAGE plpgsql;

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
    WHERE (p_SearchTerm IS NULL OR p.ProductName ILIKE '%' || p_SearchTerm || '%'
           OR p.Description ILIKE '%' || p_SearchTerm || '%')
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

CREATE OR REPLACE FUNCTION sp_GetCustomerOrders(p_CustomerID INT)
RETURNS TABLE (
    OrderID INT, OrderDate TIMESTAMP, TotalAmount DECIMAL(18,2), Status VARCHAR(50),
    PaymentMethod VARCHAR(100), ShippingAddress VARCHAR(500), TotalItems BIGINT
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Customers c WHERE c.CustomerID = p_CustomerID) THEN
        RAISE EXCEPTION 'Customer does not exist' USING ERRCODE = '23503';
    END IF;
    RETURN QUERY SELECT o.OrderID, o.OrderDate, o.TotalAmount, o.Status, o.PaymentMethod,
                        o.ShippingAddress, COUNT(od.OrderDetailID) AS TotalItems
    FROM Orders o LEFT JOIN OrderDetails od ON o.OrderID = od.OrderID
    WHERE o.CustomerID = p_CustomerID
    GROUP BY o.OrderID, o.OrderDate, o.TotalAmount, o.Status, o.PaymentMethod, o.ShippingAddress
    ORDER BY o.OrderDate DESC, o.OrderID DESC;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION sp_GetOrderDetails_Main(p_OrderID INT)
RETURNS TABLE (
    OrderID INT, OrderDate TIMESTAMP, TotalAmount DECIMAL(18,2), Status VARCHAR(50),
    PaymentMethod VARCHAR(100), ShippingAddress VARCHAR(500), CustomerID INT,
    CustomerName VARCHAR(255), CustomerEmail VARCHAR(255), CustomerPhone VARCHAR(20)
) AS $$
BEGIN
    RETURN QUERY SELECT o.OrderID, o.OrderDate, o.TotalAmount, o.Status, o.PaymentMethod,
                        o.ShippingAddress, c.CustomerID, c.FullName, c.Email, c.PhoneNumber
    FROM Orders o JOIN Customers c ON o.CustomerID = c.CustomerID WHERE o.OrderID = p_OrderID;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION sp_GetOrderDetails_Items(p_OrderID INT)
RETURNS TABLE (
    OrderDetailID INT, ProductID INT, ProductName VARCHAR(255), ColorName VARCHAR(50),
    SizeName VARCHAR(50), Quantity INT, Price DECIMAL(18,2), Subtotal DECIMAL(18,2)
) AS $$
BEGIN
    RETURN QUERY SELECT od.OrderDetailID, p.ProductID, p.ProductName, cl.ColorName,
                        s.SizeName, od.Quantity, od.Price, (od.Quantity * od.Price)::DECIMAL(18,2)
    FROM OrderDetails od
    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
    JOIN Products p ON pv.ProductID = p.ProductID
    JOIN Colors cl ON pv.ColorID = cl.ColorID
    JOIN Sizes s ON pv.SizeID = s.SizeID
    WHERE od.OrderID = p_OrderID ORDER BY od.OrderDetailID;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_AddProduct(
    p_ProductName VARCHAR(255), p_Description TEXT, p_Price DECIMAL(18,2),
    p_OriginalPrice DECIMAL(18,2), p_CategoryID INT
) RETURNS INT AS $$
DECLARE v_ProductID INT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Categories WHERE CategoryID = p_CategoryID) THEN
        RAISE EXCEPTION 'Category does not exist' USING ERRCODE = '23503';
    END IF;
    INSERT INTO Products (ProductName, Description, Price, OriginalPrice, CategoryID)
    VALUES (p_ProductName, p_Description, p_Price, p_OriginalPrice, p_CategoryID)
    RETURNING ProductID INTO v_ProductID;
    RETURN v_ProductID;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION sp_AddProductVariant(
    p_ProductID INT, p_ColorID INT, p_SizeID INT, p_Quantity INT
) RETURNS INT AS $$
DECLARE v_VariantID INT;
BEGIN
    IF p_Quantity IS NULL OR p_Quantity < 0 THEN
        RAISE EXCEPTION 'Stock quantity cannot be negative' USING ERRCODE = '23514';
    END IF;
    INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
    VALUES (p_ProductID, p_ColorID, p_SizeID, p_Quantity)
    ON CONFLICT (ProductID, ColorID, SizeID)
    DO UPDATE SET Quantity = ProductVariants.Quantity + EXCLUDED.Quantity
    RETURNING VariantID INTO v_VariantID;
    RETURN v_VariantID;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_GetRevenueByDateRange_Daily(p_StartDate DATE, p_EndDate DATE)
RETURNS TABLE (OrderDate DATE, OrderCount BIGINT, DailyRevenue DECIMAL(18,2)) AS $$
BEGIN
    RETURN QUERY SELECT CAST(o.OrderDate AS DATE), COUNT(o.OrderID), SUM(o.TotalAmount)
    FROM Orders o WHERE o.OrderDate >= p_StartDate AND o.OrderDate < p_EndDate + 1
      AND o.Status = 'Delivered'
    GROUP BY CAST(o.OrderDate AS DATE) ORDER BY CAST(o.OrderDate AS DATE);
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION sp_GetRevenueByDateRange_Category(p_StartDate DATE, p_EndDate DATE)
RETURNS TABLE (
    CategoryID INT, CategoryName VARCHAR(100), CategoryRevenue DECIMAL(18,2), TotalQuantitySold BIGINT
) AS $$
BEGIN
    RETURN QUERY SELECT c.CategoryID, c.CategoryName, SUM(od.Quantity * od.Price), SUM(od.Quantity)
    FROM Categories c
    JOIN Products p ON c.CategoryID = p.CategoryID
    JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    JOIN OrderDetails od ON pv.VariantID = od.VariantID
    JOIN Orders o ON od.OrderID = o.OrderID
    WHERE o.OrderDate >= p_StartDate AND o.OrderDate < p_EndDate + 1 AND o.Status = 'Delivered'
    GROUP BY c.CategoryID, c.CategoryName ORDER BY SUM(od.Quantity * od.Price) DESC, c.CategoryID;
END;
$$ LANGUAGE plpgsql;

-- State graph: Pending -> Processing/Cancelled; Processing -> Shipped/Cancelled;
-- Shipped -> Delivered. Delivered/Cancelled are immutable terminal ledgers.
-- Restock belongs only to the serialized Pending/Processing -> Cancelled change,
-- or Pending parent deletion. Group duplicate variant details before returning.
CREATE OR REPLACE FUNCTION func_GuardOrderLifecycle() RETURNS TRIGGER AS $$
DECLARE item RECORD; v_DetailTotal DECIMAL(18,2);
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.Status IS DISTINCT FROM 'Pending' OR NEW.TotalAmount IS DISTINCT FROM 0::NUMERIC THEN
            RAISE EXCEPTION 'New orders must be Pending with zero initial total' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.Status IS NULL OR NEW.Status NOT IN ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled') THEN
            RAISE EXCEPTION 'Invalid order status' USING ERRCODE = '23514';
        END IF;
        IF NEW.OrderID IS DISTINCT FROM OLD.OrderID OR NEW.CustomerID IS DISTINCT FROM OLD.CustomerID THEN
            RAISE EXCEPTION 'Order identity and customer are immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.Status IN ('Delivered', 'Cancelled') THEN
            IF NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'Finished orders are immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.Status IS DISTINCT FROM OLD.Status THEN
            IF NOT ((OLD.Status = 'Pending' AND NEW.Status IN ('Processing', 'Cancelled'))
                 OR (OLD.Status = 'Processing' AND NEW.Status IN ('Shipped', 'Cancelled'))
                 OR (OLD.Status = 'Shipped' AND NEW.Status = 'Delivered')) THEN
                RAISE EXCEPTION 'Invalid order transition: % -> %', OLD.Status, NEW.Status
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.Status <> 'Cancelled' AND NOT EXISTS (SELECT 1 FROM OrderDetails WHERE OrderID = OLD.OrderID) THEN
                RAISE EXCEPTION 'An empty order cannot advance' USING ERRCODE = '23514';
            END IF;
        END IF;
        SELECT COALESCE(SUM(od.Quantity * od.Price), 0) INTO v_DetailTotal
        FROM OrderDetails od WHERE od.OrderID = OLD.OrderID;
        IF NEW.TotalAmount IS DISTINCT FROM v_DetailTotal THEN
            RAISE EXCEPTION 'Order total must equal its persisted detail total' USING ERRCODE = '23514';
        END IF;
        IF NEW.Status IS DISTINCT FROM 'Cancelled' OR OLD.Status = 'Cancelled' THEN RETURN NEW; END IF;
    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.Status IS DISTINCT FROM 'Pending' THEN
            RAISE EXCEPTION 'Only Pending orders may be deleted' USING ERRCODE = '23514';
        END IF;
    END IF;
    FOR item IN
        SELECT pv.VariantID, totals.Quantity
        FROM ProductVariants pv
        JOIN (SELECT od.VariantID, SUM(od.Quantity) AS Quantity
              FROM OrderDetails od WHERE od.OrderID = OLD.OrderID GROUP BY od.VariantID) totals
          ON totals.VariantID = pv.VariantID
        ORDER BY pv.VariantID FOR UPDATE OF pv
    LOOP
        UPDATE ProductVariants SET Quantity = Quantity + item.Quantity WHERE VariantID = item.VariantID;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- This replaces the old trigger's check-then-update race with a conditional
-- UPDATE (which locks/rechecks the actual row). UPDATEs adjust only the delta;
-- variant transfers lock BOTH variants in ascending order. Finished details
-- cannot be inserted/updated/deleted, even through direct SQL.
CREATE OR REPLACE FUNCTION func_UpdateInventoryOnOrder() RETURNS TRIGGER AS $$
DECLARE v_Status VARCHAR(50); v_OrderID INT; v_Delta INT;
BEGIN
    IF TG_OP = 'DELETE' THEN v_OrderID := OLD.OrderID; ELSE v_OrderID := NEW.OrderID; END IF;
    IF TG_OP = 'UPDATE' AND (NEW.OrderID IS DISTINCT FROM OLD.OrderID
                            OR NEW.OrderDetailID IS DISTINCT FROM OLD.OrderDetailID) THEN
        RAISE EXCEPTION 'Order details cannot change identity or move between orders' USING ERRCODE = '23514';
    END IF;
    SELECT o.Status INTO v_Status FROM Orders o WHERE o.OrderID = v_OrderID FOR UPDATE;
    IF NOT FOUND THEN
        IF TG_OP = 'DELETE' THEN
            -- ON DELETE CASCADE after the Pending parent trigger already restocked.
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Order does not exist' USING ERRCODE = '23503';
    END IF;
    IF v_Status IS DISTINCT FROM 'Pending' THEN
        RAISE EXCEPTION 'Only Pending order details may change' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        UPDATE ProductVariants SET Quantity = Quantity + OLD.Quantity WHERE VariantID = OLD.VariantID;
        RETURN OLD;
    END IF;
    IF NEW.Quantity IS NULL OR NEW.Quantity <= 0 OR NEW.Price IS NULL OR NEW.Price < 0 THEN
        RAISE EXCEPTION 'Order quantity must be positive and price nonnegative' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        UPDATE ProductVariants SET Quantity = Quantity - NEW.Quantity
        WHERE VariantID = NEW.VariantID AND Quantity >= NEW.Quantity;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Insufficient stock or unknown variant' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.VariantID IS DISTINCT FROM OLD.VariantID THEN
        PERFORM pv.VariantID FROM ProductVariants pv
        WHERE pv.VariantID IN (OLD.VariantID, NEW.VariantID) ORDER BY pv.VariantID FOR UPDATE;
        UPDATE ProductVariants SET Quantity = Quantity - NEW.Quantity
        WHERE VariantID = NEW.VariantID AND Quantity >= NEW.Quantity;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Insufficient stock or unknown variant' USING ERRCODE = '23514';
        END IF;
        UPDATE ProductVariants SET Quantity = Quantity + OLD.Quantity WHERE VariantID = OLD.VariantID;
    ELSE
        v_Delta := NEW.Quantity - OLD.Quantity;
        UPDATE ProductVariants SET Quantity = Quantity - v_Delta
        WHERE VariantID = NEW.VariantID AND Quantity >= v_Delta;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Insufficient stock or unknown variant' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION func_UpdateOrderTotal() RETURNS TRIGGER AS $$
DECLARE v_OrderID INT;
BEGIN
    IF TG_OP = 'DELETE' THEN v_OrderID := OLD.OrderID; ELSE v_OrderID := NEW.OrderID; END IF;
    UPDATE Orders o SET TotalAmount = (
        SELECT COALESCE(SUM(od.Quantity * od.Price), 0) FROM OrderDetails od WHERE od.OrderID = v_OrderID
    ) WHERE o.OrderID = v_OrderID;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER trg_GuardOrderLifecycle
BEFORE INSERT OR UPDATE OR DELETE ON Orders
FOR EACH ROW EXECUTE FUNCTION func_GuardOrderLifecycle();
CREATE OR REPLACE TRIGGER trg_UpdateInventory
BEFORE INSERT OR UPDATE OR DELETE ON OrderDetails
FOR EACH ROW EXECUTE FUNCTION func_UpdateInventoryOnOrder();
CREATE OR REPLACE TRIGGER trg_UpdateOrderTotal
AFTER INSERT OR UPDATE OR DELETE ON OrderDetails
FOR EACH ROW EXECUTE FUNCTION func_UpdateOrderTotal();

-- Legacy chat FKs had CASCADE/SET NULL. Keep those constraints untouched on
-- existing DBs, but stop parent deletion BEFORE they can erase chat history.
-- New DBs also use RESTRICT for each customer-side chat reference.
CREATE OR REPLACE FUNCTION func_PreserveCustomerHistory() RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM Orders WHERE CustomerID = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM Reviews WHERE CustomerID = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM ProductComments WHERE CustomerID = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM Wishlist WHERE CustomerID = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM PasswordResetTokens WHERE CustomerID = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM Messages WHERE user_id = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM Participants WHERE user_id = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM Conversations WHERE created_by = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM Reactions WHERE user_id = OLD.CustomerID)
       OR EXISTS (SELECT 1 FROM PinnedMessages WHERE pinned_by = OLD.CustomerID) THEN
        RAISE EXCEPTION 'Customer has retained order, feedback, or chat history' USING ERRCODE = '23503';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER trg_PreserveCustomerHistory
BEFORE DELETE ON Customers
FOR EACH ROW EXECUTE FUNCTION func_PreserveCustomerHistory();
COMMIT;
