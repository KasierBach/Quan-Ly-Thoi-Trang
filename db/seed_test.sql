-- Synthetic fixtures only. Never point a seed/reset runner at an application database.
-- The validated loopback-only tools/seed_test.py runner (or the integration fixture)
-- must authorize this connection before executing this file.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
DO $$
BEGIN
    IF current_database() <> 'thua2_main_test'
       OR current_setting('thua2.allow_test_seed', true) IS DISTINCT FROM 'loopback-disposable' THEN
        RAISE EXCEPTION 'Seed refused: use the loopback-only disposable thua2_main_test runner';
    END IF;
    IF EXISTS (
        SELECT 1 FROM Customers
        WHERE CustomerID IN (1, 2, 3)
          AND Email <> CASE CustomerID
              WHEN 1 THEN 'customer@example.test'
              WHEN 2 THEN 'admin@example.test'
              WHEN 3 THEN 'other@example.test' END
    ) OR EXISTS (
        SELECT 1 FROM Products WHERE ProductID IN (1, 2)
          AND ProductName <> CASE ProductID
              WHEN 1 THEN 'Test Cotton Shirt' WHEN 2 THEN 'Test Summer Dress' END
    ) OR EXISTS (
        SELECT 1 FROM Orders WHERE OrderID IN (1, 2, 3)
          AND notes IS DISTINCT FROM 'Synthetic seed order'
    ) THEN
        RAISE EXCEPTION 'Seed refused: reserved fixture IDs contain non-fixture data';
    END IF;
END;
$$;

-- All three accounts use TestUser123!; this is a reproducible Werkzeug PBKDF2 hash,
-- not an original/customer password. example.test is a reserved test domain.
INSERT INTO Customers
    (CustomerID, FullName, Email, Password, IsAdmin, role, auth_version,
     Gender, DateOfBirth, Address, avatar_url, CreatedAt)
VALUES
    (1, 'Test Customer', 'customer@example.test',
     'pbkdf2:sha256:1000000$thua2mainseed$eb30e58ef38b2340adabaa0e4b07889ff7c12788adf91bdaef5ebc4aa899ab96',
     FALSE, 'customer', 1, 'other', DATE '1995-01-01', '1 Synthetic Test Street',
     '/static/images/default.jpg', TIMESTAMP '2026-04-01 09:00:00'),
    (2, 'Test Admin', 'admin@example.test',
     'pbkdf2:sha256:1000000$thua2mainseed$eb30e58ef38b2340adabaa0e4b07889ff7c12788adf91bdaef5ebc4aa899ab96',
     TRUE, 'admin', 1, 'other', DATE '1990-01-01', '2 Synthetic Test Street',
     '/static/images/default.jpg', TIMESTAMP '2026-04-01 09:00:00'),
    (3, 'Test Other Customer', 'other@example.test',
     'pbkdf2:sha256:1000000$thua2mainseed$eb30e58ef38b2340adabaa0e4b07889ff7c12788adf91bdaef5ebc4aa899ab96',
     FALSE, 'customer', 1, 'other', DATE '1996-01-01', '3 Synthetic Test Street',
     '/static/images/default.jpg', TIMESTAMP '2026-04-01 09:00:00')
ON CONFLICT (CustomerID) DO NOTHING;

INSERT INTO Categories (CategoryID, CategoryName, Description) VALUES
    (1, 'Test Tops', 'Synthetic category'), (2, 'Test Dresses', 'Synthetic category')
ON CONFLICT (CategoryID) DO NOTHING;
INSERT INTO Colors (ColorID, ColorName) VALUES (1, 'Test Black'), (2, 'Test White')
ON CONFLICT (ColorID) DO NOTHING;
INSERT INTO Sizes (SizeID, SizeName) VALUES (1, 'Test M'), (2, 'Test L')
ON CONFLICT (SizeID) DO NOTHING;
INSERT INTO Products
    (ProductID, ProductName, Description, Price, OriginalPrice, CategoryID, ImageURL, CreatedAt)
VALUES
    (1, 'Test Cotton Shirt', 'Synthetic test product; no customer data.',
     199000.00, 249000.00, 1, 'images/ao-thun-nam-den.jpg', TIMESTAMP '2026-04-01 09:00:00'),
    (2, 'Test Summer Dress', 'Synthetic test product; no customer data.',
     399000.00, 449000.00, 2, 'images/vay-dam-suong-den.jpg', TIMESTAMP '2026-04-01 09:00:00')
ON CONFLICT (ProductID) DO NOTHING;
INSERT INTO ProductVariants (VariantID, ProductID, ColorID, SizeID, Quantity) VALUES
    (1, 1, 1, 1, 100), (2, 2, 2, 2, 20)
ON CONFLICT (VariantID) DO NOTHING;

-- Exercise the real stock/total/lifecycle functions; reruns neither replenish
-- inventory nor reinsert details on an existing (possibly terminal) order.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = 1) THEN
        INSERT INTO Orders
            (OrderID, CustomerID, OrderDate, PaymentMethod, ShippingAddress,
             recipient_name, recipient_phone, recipient_email, notes)
        VALUES (1, 1, TIMESTAMP '2026-04-02 10:00:00', 'cod', '1 Synthetic Test Street',
                'Test Customer', '0900000001', 'customer@example.test', 'Synthetic seed order');
        INSERT INTO OrderDetails (OrderDetailID, OrderID, VariantID, Quantity, Price)
        VALUES (1, 1, 1, 2, 199000.00);
        PERFORM sp_UpdateOrderStatus(1, 'Processing');
        PERFORM sp_UpdateOrderStatus(1, 'Shipped');
        PERFORM sp_UpdateOrderStatus(1, 'Delivered');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = 2) THEN
        INSERT INTO Orders
            (OrderID, CustomerID, OrderDate, PaymentMethod, ShippingAddress,
             recipient_name, recipient_phone, recipient_email, notes)
        VALUES (2, 1, TIMESTAMP '2026-04-03 10:00:00', 'cod', '1 Synthetic Test Street',
                'Test Customer', '0900000001', 'customer@example.test', 'Synthetic seed order');
        INSERT INTO OrderDetails (OrderDetailID, OrderID, VariantID, Quantity, Price)
        VALUES (2, 2, 2, 1, 399000.00);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = 3) THEN
        INSERT INTO Orders
            (OrderID, CustomerID, OrderDate, PaymentMethod, ShippingAddress,
             recipient_name, recipient_phone, recipient_email, notes)
        VALUES (3, 3, TIMESTAMP '2026-04-04 10:00:00', 'cod', '3 Synthetic Test Street',
                'Test Other Customer', '0900000003', 'other@example.test', 'Synthetic seed order');
        INSERT INTO OrderDetails (OrderDetailID, OrderID, VariantID, Quantity, Price)
        VALUES (3, 3, 1, 1, 199000.00);
        PERFORM sp_UpdateOrderStatus(3, 'Cancelled');
    END IF;
END;
$$;

INSERT INTO Reviews (ReviewID, CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (1, 1, 1, 5, 'Synthetic integration review', TIMESTAMP '2026-04-05 10:00:00')
ON CONFLICT (ReviewID) DO NOTHING;
INSERT INTO ProductComments
    (CommentID, CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate)
VALUES (1, 1, 1, 'Synthetic integration comment', TIMESTAMP '2026-04-05 11:00:00',
        'Synthetic admin reply', TIMESTAMP '2026-04-05 12:00:00')
ON CONFLICT (CommentID) DO NOTHING;
INSERT INTO Wishlist (WishlistID, CustomerID, ProductID, AddedDate)
VALUES (1, 1, 2, TIMESTAMP '2026-04-05 10:00:00')
ON CONFLICT (WishlistID) DO NOTHING;
INSERT INTO ContactMessages (MessageID, Name, Email, Subject, Message, SubmitDate)
VALUES (1, 'Synthetic Contact', 'contact@example.test', 'Synthetic contact subject',
        'Synthetic integration contact message', TIMESTAMP '2026-04-05 10:00:00')
ON CONFLICT (MessageID) DO NOTHING;
INSERT INTO NewsletterSubscribers (SubscriberID, Email, SubscribeDate)
VALUES (1, 'subscriber@example.test', TIMESTAMP '2026-04-05 10:00:00')
ON CONFLICT (SubscriberID) DO NOTHING;

INSERT INTO Conversations (id, type, name, created_by, created_at, updated_at) VALUES
    (1, 'support', 'Synthetic Support', 1, TIMESTAMP '2026-04-05 10:00:00', TIMESTAMP '2026-04-05 10:00:00'),
    (2, 'private', 'Synthetic Private', 1, TIMESTAMP '2026-04-05 10:00:00', TIMESTAMP '2026-04-05 10:00:00'),
    (3, 'group', 'Synthetic Small Group', 1, TIMESTAMP '2026-04-05 10:00:00', TIMESTAMP '2026-04-05 10:00:00')
ON CONFLICT (id) DO NOTHING;
INSERT INTO Participants (id, conversation_id, user_id, role, joined_at) VALUES
    (1, 1, 1, 'owner', TIMESTAMP '2026-04-05 10:00:00'),
    (2, 1, 2, 'admin', TIMESTAMP '2026-04-05 10:00:00'),
    (3, 2, 1, 'owner', TIMESTAMP '2026-04-05 10:00:00'),
    (4, 2, 3, 'member', TIMESTAMP '2026-04-05 10:00:00'),
    (5, 3, 1, 'admin', TIMESTAMP '2026-04-05 10:00:00'),
    (6, 3, 2, 'member', TIMESTAMP '2026-04-05 10:00:00'),
    (7, 3, 3, 'member', TIMESTAMP '2026-04-05 10:00:00')
ON CONFLICT (id) DO NOTHING;
INSERT INTO Messages
    (id, sender_type, content, session_id, user_id, conversation_id, created_at)
VALUES
    (1, 'user', 'Synthetic support question', 'user_1', 1, 1, TIMESTAMP '2026-04-05 10:01:00'),
    (2, 'admin', 'Synthetic support answer', 'user_2', 2, 1, TIMESTAMP '2026-04-05 10:02:00'),
    (3, 'user', 'Synthetic private message', 'user_3', 3, 2, TIMESTAMP '2026-04-05 10:03:00')
ON CONFLICT (id) DO NOTHING;

-- Preserve sequence high-water marks (including values consumed by failed
-- transactions); never rewind a sequence when this seed is replayed.
DO $$
DECLARE
    item RECORD;
    sequence_name TEXT;
    maximum_id BIGINT;
    current_value BIGINT;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('customers', 'customerid'), ('categories', 'categoryid'),
        ('colors', 'colorid'), ('sizes', 'sizeid'), ('products', 'productid'),
        ('productvariants', 'variantid'), ('orders', 'orderid'),
        ('orderdetails', 'orderdetailid'), ('reviews', 'reviewid'),
        ('productcomments', 'commentid'), ('wishlist', 'wishlistid'),
        ('contactmessages', 'messageid'), ('newslettersubscribers', 'subscriberid'),
        ('conversations', 'id'), ('participants', 'id'), ('messages', 'id')
    ) AS identifiers(table_name, column_name)
    LOOP
        sequence_name := pg_get_serial_sequence('public.' || item.table_name, item.column_name);
        EXECUTE format('SELECT COALESCE(MAX(%I), 0) FROM public.%I', item.column_name, item.table_name)
            INTO maximum_id;
        EXECUTE format('SELECT last_value FROM %s', sequence_name) INTO current_value;
        PERFORM setval(sequence_name::regclass, GREATEST(maximum_id, current_value, 1), TRUE);
    END LOOP;
END;
$$;
COMMIT;
