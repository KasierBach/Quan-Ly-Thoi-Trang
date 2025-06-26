-- =============================================
-- Tạo cơ sở dữ liệu
-- =============================================
CREATE DATABASE FashionStoreDB;
GO

USE FashionStoreDB;
GO

-- =============================================
-- Tạo các bảng
-- =============================================

-- Tạo bảng Customers (Khách hàng)
CREATE TABLE Customers (
    CustomerID INT PRIMARY KEY IDENTITY(1,1),
    FullName NVARCHAR(255) NOT NULL,
    Email NVARCHAR(255) NOT NULL UNIQUE,
    Password NVARCHAR(255) NOT NULL,
    PhoneNumber NVARCHAR(20) UNIQUE,
    Address NVARCHAR(500) NULL,
    CreatedAt DATETIME DEFAULT GETDATE()
);
GO

-- Tạo bảng Categories (Danh mục sản phẩm)
CREATE TABLE Categories (
    CategoryID INT PRIMARY KEY IDENTITY(1,1),
    CategoryName NVARCHAR(100) NOT NULL UNIQUE,
    Description NVARCHAR(255) NULL
);
GO

-- Tạo bảng Products (Sản phẩm)
CREATE TABLE Products (
    ProductID INT PRIMARY KEY IDENTITY(1,1),
    ProductName NVARCHAR(255) NOT NULL,
    Description NVARCHAR(MAX) NULL,
    Price DECIMAL(18,2) NOT NULL,
    CategoryID INT FOREIGN KEY REFERENCES Categories(CategoryID),
    CreatedAt DATETIME DEFAULT GETDATE()
);
GO

ALTER TABLE Products
ADD ImageURL NVARCHAR(255) NULL;
GO

UPDATE Products
SET ImageURL = NULL;

UPDATE Products
SET ImageURL = REPLACE(ImageURL, '/static/', '');

-- Tạo bảng Colors (Màu sắc)
CREATE TABLE Colors (
    ColorID INT PRIMARY KEY IDENTITY(1,1),
    ColorName NVARCHAR(50) NOT NULL UNIQUE
);
GO

-- Tạo bảng Sizes (Kích thước)
CREATE TABLE Sizes (
    SizeID INT PRIMARY KEY IDENTITY(1,1),
    SizeName NVARCHAR(50) NOT NULL UNIQUE
);
GO

-- Tạo bảng ProductVariants (Biến thể sản phẩm)
CREATE TABLE ProductVariants (
    VariantID INT PRIMARY KEY IDENTITY(1,1),
    ProductID INT FOREIGN KEY REFERENCES Products(ProductID),
    ColorID INT FOREIGN KEY REFERENCES Colors(ColorID),
    SizeID INT FOREIGN KEY REFERENCES Sizes(SizeID),
    Quantity INT NOT NULL DEFAULT 0,
    CONSTRAINT UC_ProductVariant UNIQUE (ProductID, ColorID, SizeID)
);
GO

-- Tạo bảng Orders (Đơn hàng)
CREATE TABLE Orders (
    OrderID INT PRIMARY KEY IDENTITY(1,1),
    CustomerID INT FOREIGN KEY REFERENCES Customers(CustomerID),
    OrderDate DATETIME DEFAULT GETDATE(),
    TotalAmount DECIMAL(18,2) NOT NULL,
    Status NVARCHAR(50) DEFAULT 'Pending',
    PaymentMethod NVARCHAR(100) NULL,
    ShippingAddress NVARCHAR(500) NULL
);
GO

-- Tạo bảng OrderDetails (Chi tiết đơn hàng)
CREATE TABLE OrderDetails (
    OrderDetailID INT PRIMARY KEY IDENTITY(1,1),
    OrderID INT FOREIGN KEY REFERENCES Orders(OrderID),
    VariantID INT FOREIGN KEY REFERENCES ProductVariants(VariantID),
    Quantity INT NOT NULL,
    Price DECIMAL(18,2) NOT NULL
);
GO

-- =============================================
-- Tạo các View
-- =============================================

-- View 1: Thống kê doanh thu theo tháng
CREATE VIEW vw_MonthlyRevenue AS
SELECT 
    YEAR(OrderDate) AS Year,
    MONTH(OrderDate) AS Month,
    SUM(TotalAmount) AS TotalRevenue,
    COUNT(OrderID) AS OrderCount
FROM 
    Orders
WHERE 
    Status != 'Cancelled'
GROUP BY 
    YEAR(OrderDate), MONTH(OrderDate);
GO

-- View 2: Thống kê doanh thu theo danh mục sản phẩm
CREATE VIEW vw_CategoryRevenue AS
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
GO

-- View 3: Sản phẩm còn hàng
CREATE VIEW vw_AvailableProducts AS
SELECT 
    p.ProductID,
    p.ProductName,
    c.CategoryName,
    s.SizeName,
    cl.ColorName,
    pv.Quantity AS AvailableStock,
    p.Price
FROM 
    Products p
    JOIN Categories c ON p.CategoryID = c.CategoryID
    JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    JOIN Sizes s ON pv.SizeID = s.SizeID
    JOIN Colors cl ON pv.ColorID = cl.ColorID
WHERE 
    pv.Quantity > 0;
GO

-- View 4: Sản phẩm bán chạy
CREATE VIEW vw_BestSellingProducts AS
SELECT TOP 4
    p.ProductID,
    p.ProductName,
    SUM(od.Quantity) AS TotalSold,
    p.Price,
    c.CategoryName
FROM OrderDetails od
JOIN ProductVariants pv ON od.VariantID = pv.VariantID
JOIN Products p ON pv.ProductID = p.ProductID
JOIN Categories c ON p.CategoryID = c.CategoryID
GROUP BY p.ProductID, p.ProductName, p.Price, c.CategoryName
ORDER BY SUM(od.Quantity) DESC;
go;

-- View 5: Lịch sử mua hàng của khách hàng
CREATE VIEW vw_CustomerPurchaseHistory AS
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
GO

-- =============================================
-- Tạo các Trigger
-- =============================================

-- Trigger 1: Cập nhật tồn kho khi thêm chi tiết đơn hàng
CREATE TRIGGER trg_UpdateInventoryOnOrderInsert
ON OrderDetails
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Cập nhật số lượng tồn kho
    UPDATE pv
    SET pv.Quantity = pv.Quantity - i.Quantity
    FROM ProductVariants pv
    INNER JOIN inserted i ON pv.VariantID = i.VariantID;
    
    -- Kiểm tra nếu có sản phẩm bị âm tồn kho
    IF EXISTS (SELECT 1 FROM ProductVariants WHERE Quantity < 0)
    BEGIN
        RAISERROR('Không đủ số lượng tồn kho cho một hoặc nhiều sản phẩm', 16, 1);
        ROLLBACK TRANSACTION;
    END
END;
GO

-- Trigger 2: Cập nhật tồn kho khi hủy đơn hàng (xóa chi tiết đơn hàng)
CREATE TRIGGER trg_UpdateInventoryOnOrderDelete
ON OrderDetails
AFTER DELETE
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Cập nhật số lượng tồn kho (trả lại số lượng)
    UPDATE pv
    SET pv.Quantity = pv.Quantity + d.Quantity
    FROM ProductVariants pv
    INNER JOIN deleted d ON pv.VariantID = d.VariantID;
END;
GO

-- Trigger 3: Kiểm tra tồn kho trước khi thêm chi tiết đơn hàng
CREATE TRIGGER trg_CheckInventoryBeforeOrder
ON OrderDetails
INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra xem có đủ tồn kho không
    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN ProductVariants pv ON i.VariantID = pv.VariantID
        WHERE pv.Quantity < i.Quantity
    )
    BEGIN
        DECLARE @ErrorMsg NVARCHAR(200);
        SELECT @ErrorMsg = 'Không đủ tồn kho cho sản phẩm: ' + 
                          CAST((SELECT TOP 1 p.ProductName 
                                FROM inserted i 
                                JOIN ProductVariants pv ON i.VariantID = pv.VariantID
                                JOIN Products p ON pv.ProductID = p.ProductID
                                WHERE pv.Quantity < i.Quantity) AS NVARCHAR(100));
        
        RAISERROR(@ErrorMsg, 16, 1);
        RETURN;
    END
    
    -- Nếu đủ tồn kho, thêm chi tiết đơn hàng
    INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
    SELECT OrderID, VariantID, Quantity, Price
    FROM inserted;
END;
GO

-- Trigger 4: Cập nhật tổng tiền đơn hàng khi thêm/sửa/xóa chi tiết đơn hàng
CREATE TRIGGER trg_UpdateOrderTotal
ON OrderDetails
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Lấy danh sách OrderID bị ảnh hưởng
    DECLARE @AffectedOrders TABLE (OrderID INT);
    
    -- Từ inserted
    INSERT INTO @AffectedOrders (OrderID)
    SELECT DISTINCT OrderID FROM inserted
    WHERE OrderID IS NOT NULL;
    
    -- Từ deleted
    INSERT INTO @AffectedOrders (OrderID)
    SELECT DISTINCT OrderID FROM deleted
    WHERE OrderID IS NOT NULL AND OrderID NOT IN (SELECT OrderID FROM @AffectedOrders);
    
    -- Cập nhật tổng tiền cho mỗi đơn hàng bị ảnh hưởng
    UPDATE o
    SET TotalAmount = ISNULL((
        SELECT SUM(Quantity * Price)
        FROM OrderDetails
        WHERE OrderID = o.OrderID
    ), 0)
    FROM Orders o
    WHERE o.OrderID IN (SELECT OrderID FROM @AffectedOrders);
END;
GO

-- =============================================
-- Tạo các Stored Procedure
-- =============================================

-- Procedure 1: Thêm khách hàng mới
CREATE PROCEDURE sp_AddCustomer
    @FullName NVARCHAR(255),
    @Email NVARCHAR(255),
    @Password NVARCHAR(255),
    @PhoneNumber NVARCHAR(20) = NULL,
    @Address NVARCHAR(500) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra email đã tồn tại chưa
    IF EXISTS (SELECT 1 FROM Customers WHERE Email = @Email)
    BEGIN
        RAISERROR('Email đã tồn tại trong hệ thống', 16, 1);
        RETURN -1;
    END
    
    -- Kiểm tra số điện thoại đã tồn tại chưa (nếu có)
    IF @PhoneNumber IS NOT NULL AND EXISTS (SELECT 1 FROM Customers WHERE PhoneNumber = @PhoneNumber)
    BEGIN
        RAISERROR('Số điện thoại đã tồn tại trong hệ thống', 16, 1);
        RETURN -2;
    END
    
    -- Thêm khách hàng mới
    INSERT INTO Customers (FullName, Email, Password, PhoneNumber, Address, CreatedAt)
    VALUES (@FullName, @Email, @Password, @PhoneNumber, @Address, GETDATE());
    
    -- Trả về ID của khách hàng vừa thêm
    RETURN SCOPE_IDENTITY();
END;
GO

-- Procedure 2: Tạo đơn hàng mới
CREATE PROCEDURE sp_CreateOrder
    @CustomerID INT,
    @PaymentMethod NVARCHAR(100),
    @ShippingAddress NVARCHAR(500),
    @OrderID INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra khách hàng tồn tại
    IF NOT EXISTS (SELECT 1 FROM Customers WHERE CustomerID = @CustomerID)
    BEGIN
        RAISERROR('Khách hàng không tồn tại', 16, 1);
        RETURN -1;
    END
    
    -- Tạo đơn hàng mới với tổng tiền ban đầu là 0
    INSERT INTO Orders (CustomerID, OrderDate, TotalAmount, Status, PaymentMethod, ShippingAddress)
    VALUES (@CustomerID, GETDATE(), 0, 'Pending', @PaymentMethod, @ShippingAddress);
    
    -- Lấy ID của đơn hàng vừa tạo
    SET @OrderID = SCOPE_IDENTITY();
    
    RETURN 0;
END;
GO

-- Procedure 3: Thêm chi tiết đơn hàng
CREATE PROCEDURE sp_AddOrderDetail
    @OrderID INT,
    @VariantID INT,
    @Quantity INT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra đơn hàng tồn tại
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = @OrderID)
    BEGIN
        RAISERROR('Đơn hàng không tồn tại', 16, 1);
        RETURN -1;
    END
    
    -- Kiểm tra biến thể sản phẩm tồn tại
    IF NOT EXISTS (SELECT 1 FROM ProductVariants WHERE VariantID = @VariantID)
    BEGIN
        RAISERROR('Biến thể sản phẩm không tồn tại', 16, 1);
        RETURN -2;
    END
    
    -- Kiểm tra số lượng tồn kho
    DECLARE @AvailableQuantity INT;
    SELECT @AvailableQuantity = Quantity FROM ProductVariants WHERE VariantID = @VariantID;
    
    IF @AvailableQuantity < @Quantity
    BEGIN
        RAISERROR('Số lượng sản phẩm không đủ. Hiện chỉ còn %d sản phẩm.', 16, 1, @AvailableQuantity);
        RETURN -3;
    END
    
    -- Lấy giá sản phẩm hiện tại
    DECLARE @CurrentPrice DECIMAL(18,2);
    SELECT @CurrentPrice = p.Price
    FROM Products p
    JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    WHERE pv.VariantID = @VariantID;
    
    -- Thêm chi tiết đơn hàng
    INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
    VALUES (@OrderID, @VariantID, @Quantity, @CurrentPrice);
    
    -- Cập nhật số lượng tồn kho (trigger sẽ xử lý)
    
    RETURN 0;
END;
GO

-- Procedure 4: Cập nhật trạng thái đơn hàng
CREATE PROCEDURE sp_UpdateOrderStatus
    @OrderID INT,
    @NewStatus NVARCHAR(50)
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra đơn hàng tồn tại
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = @OrderID)
    BEGIN
        RAISERROR('Đơn hàng không tồn tại', 16, 1);
        RETURN -1;
    END
    
    -- Kiểm tra trạng thái hợp lệ
    IF @NewStatus NOT IN ('Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled')
    BEGIN
        RAISERROR('Trạng thái đơn hàng không hợp lệ', 16, 1);
        RETURN -2;
    END
    
    -- Lấy trạng thái hiện tại
    DECLARE @CurrentStatus NVARCHAR(50);
    SELECT @CurrentStatus = Status FROM Orders WHERE OrderID = @OrderID;
    
    -- Nếu đơn hàng đã bị hủy, không cho phép thay đổi trạng thái
    IF @CurrentStatus = 'Cancelled' AND @NewStatus != 'Cancelled'
    BEGIN
        RAISERROR('Không thể thay đổi trạng thái của đơn hàng đã bị hủy', 16, 1);
        RETURN -3;
    END
    
    -- Nếu đơn hàng đã giao, không cho phép thay đổi trạng thái (trừ khi hủy)
    IF @CurrentStatus = 'Delivered' AND @NewStatus != 'Delivered' AND @NewStatus != 'Cancelled'
    BEGIN
        RAISERROR('Không thể thay đổi trạng thái của đơn hàng đã giao', 16, 1);
        RETURN -4;
    END
    
    -- Nếu đổi từ trạng thái khác sang Cancelled, cần hoàn trả tồn kho
    IF @NewStatus = 'Cancelled' AND @CurrentStatus != 'Cancelled'
    BEGIN
        -- Hoàn trả tồn kho
        UPDATE pv
        SET pv.Quantity = pv.Quantity + od.Quantity
        FROM ProductVariants pv
        JOIN OrderDetails od ON pv.VariantID = od.VariantID
        WHERE od.OrderID = @OrderID;
    END
    
    -- Nếu đổi từ Cancelled sang trạng thái khác, cần trừ lại tồn kho
    IF @CurrentStatus = 'Cancelled' AND @NewStatus != 'Cancelled'
    BEGIN
        -- Kiểm tra xem có đủ tồn kho không
        IF EXISTS (
            SELECT 1
            FROM OrderDetails od
            JOIN ProductVariants pv ON od.VariantID = pv.VariantID
            WHERE od.OrderID = @OrderID AND pv.Quantity < od.Quantity
        )
        BEGIN
            RAISERROR('Không đủ tồn kho để khôi phục đơn hàng', 16, 1);
            RETURN -5;
        END
        
        -- Trừ lại tồn kho
        UPDATE pv
        SET pv.Quantity = pv.Quantity - od.Quantity
        FROM ProductVariants pv
        JOIN OrderDetails od ON pv.VariantID = od.VariantID
        WHERE od.OrderID = @OrderID;
    END
    
    -- Cập nhật trạng thái đơn hàng
    UPDATE Orders
    SET Status = @NewStatus
    WHERE OrderID = @OrderID;
    
    RETURN 0;
END;
GO

-- Procedure 5: Tìm kiếm sản phẩm
CREATE PROCEDURE sp_SearchProducts
    @SearchTerm NVARCHAR(255) = NULL,
    @CategoryID INT = NULL,
    @MinPrice DECIMAL(18,2) = NULL,
    @MaxPrice DECIMAL(18,2) = NULL,
    @ColorID INT = NULL,
    @SizeID INT = NULL,
    @InStockOnly BIT = 0
AS
BEGIN
    SET NOCOUNT ON;
    
    SELECT DISTINCT
        p.ProductID,
        p.ProductName,
        p.Description,
        p.Price,
        c.CategoryID,
        c.CategoryName
    FROM 
        Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        LEFT JOIN ProductVariants pv ON p.ProductID = pv.ProductID
    WHERE
        (@SearchTerm IS NULL OR p.ProductName LIKE '%' + @SearchTerm + '%' OR p.Description LIKE '%' + @SearchTerm + '%')
        AND (@CategoryID IS NULL OR p.CategoryID = @CategoryID)
        AND (@MinPrice IS NULL OR p.Price >= @MinPrice)
        AND (@MaxPrice IS NULL OR p.Price <= @MaxPrice)
        AND (@ColorID IS NULL OR EXISTS (
            SELECT 1 FROM ProductVariants 
            WHERE ProductID = p.ProductID AND ColorID = @ColorID
        ))
        AND (@SizeID IS NULL OR EXISTS (
            SELECT 1 FROM ProductVariants 
            WHERE ProductID = p.ProductID AND SizeID = @SizeID
        ))
        AND (@InStockOnly = 0 OR EXISTS (
            SELECT 1 FROM ProductVariants 
            WHERE ProductID = p.ProductID AND Quantity > 0
        ))
    ORDER BY
        p.ProductName;
END;
GO

-- Procedure 6: Lấy danh sách đơn hàng của khách hàng
CREATE PROCEDURE sp_GetCustomerOrders
    @CustomerID INT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra khách hàng tồn tại
    IF NOT EXISTS (SELECT 1 FROM Customers WHERE CustomerID = @CustomerID)
    BEGIN
        RAISERROR('Khách hàng không tồn tại', 16, 1);
        RETURN -1;
    END
    
    -- Lấy danh sách đơn hàng
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
        o.CustomerID = @CustomerID
    GROUP BY 
        o.OrderID, o.OrderDate, o.TotalAmount, o.Status, o.PaymentMethod, o.ShippingAddress
    ORDER BY 
        o.OrderDate DESC;
    
    RETURN 0;
END;
GO

-- Procedure 7: Lấy chi tiết đơn hàng
CREATE PROCEDURE sp_GetOrderDetails
    @OrderID INT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra đơn hàng tồn tại
    IF NOT EXISTS (SELECT 1 FROM Orders WHERE OrderID = @OrderID)
    BEGIN
        RAISERROR('Đơn hàng không tồn tại', 16, 1);
        RETURN -1;
    END
    
    -- Lấy thông tin đơn hàng
    SELECT 
        o.OrderID,
        o.OrderDate,
        o.TotalAmount,
        o.Status,
        o.PaymentMethod,
        o.ShippingAddress,
        c.CustomerID,
        c.FullName AS CustomerName,
        c.Email AS CustomerEmail,
        c.PhoneNumber AS CustomerPhone
    FROM 
        Orders o
        JOIN Customers c ON o.CustomerID = c.CustomerID
    WHERE 
        o.OrderID = @OrderID;
    
    -- Lấy chi tiết các sản phẩm trong đơn hàng
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
        od.OrderID = @OrderID;
    
    RETURN 0;
END;
GO

-- Procedure 8: Thêm sản phẩm mới
CREATE PROCEDURE sp_AddProduct
    @ProductName NVARCHAR(255),
    @Description NVARCHAR(MAX),
    @Price DECIMAL(18,2),
    @CategoryID INT,
    @ProductID INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra danh mục tồn tại
    IF NOT EXISTS (SELECT 1 FROM Categories WHERE CategoryID = @CategoryID)
    BEGIN
        RAISERROR('Danh mục không tồn tại', 16, 1);
        RETURN -1;
    END
    
    -- Thêm sản phẩm mới
    INSERT INTO Products (ProductName, Description, Price, CategoryID, CreatedAt)
    VALUES (@ProductName, @Description, @Price, @CategoryID, GETDATE());
    
    -- Lấy ID của sản phẩm vừa thêm
    SET @ProductID = SCOPE_IDENTITY();
    
    RETURN 0;
END;
GO

-- Procedure 9: Thêm biến thể sản phẩm
CREATE PROCEDURE sp_AddProductVariant
    @ProductID INT,
    @ColorID INT,
    @SizeID INT,
    @Quantity INT,
    @VariantID INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra sản phẩm tồn tại
    IF NOT EXISTS (SELECT 1 FROM Products WHERE ProductID = @ProductID)
    BEGIN
        RAISERROR('Sản phẩm không tồn tại', 16, 1);
        RETURN -1;
    END
    
    -- Kiểm tra màu sắc tồn tại
    IF NOT EXISTS (SELECT 1 FROM Colors WHERE ColorID = @ColorID)
    BEGIN
        RAISERROR('Màu sắc không tồn tại', 16, 1);
        RETURN -2;
    END
    
    -- Kiểm tra kích thước tồn tại
    IF NOT EXISTS (SELECT 1 FROM Sizes WHERE SizeID = @SizeID)
    BEGIN
        RAISERROR('Kích thước không tồn tại', 16, 1);
        RETURN -3;
    END
    
    -- Kiểm tra biến thể đã tồn tại chưa
    IF EXISTS (SELECT 1 FROM ProductVariants WHERE ProductID = @ProductID AND ColorID = @ColorID AND SizeID = @SizeID)
    BEGIN
        -- Cập nhật số lượng nếu biến thể đã tồn tại
        UPDATE ProductVariants
        SET Quantity = Quantity + @Quantity
        WHERE ProductID = @ProductID AND ColorID = @ColorID AND SizeID = @SizeID;
        
        -- Lấy ID của biến thể
        SELECT @VariantID = VariantID
        FROM ProductVariants
        WHERE ProductID = @ProductID AND ColorID = @ColorID AND SizeID = @SizeID;
    END
    ELSE
    BEGIN
        -- Thêm biến thể mới
        INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
        VALUES (@ProductID, @ColorID, @SizeID, @Quantity);
        
        -- Lấy ID của biến thể vừa thêm
        SET @VariantID = SCOPE_IDENTITY();
    END
    
    RETURN 0;
END;
GO

-- Procedure 10: Thống kê doanh thu theo khoảng thời gian
CREATE PROCEDURE sp_GetRevenueByDateRange
    @StartDate DATE,
    @EndDate DATE
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra ngày hợp lệ
    IF @StartDate > @EndDate
    BEGIN
        RAISERROR('Ngày bắt đầu không thể sau ngày kết thúc', 16, 1);
        RETURN -1;
    END
    
    -- Thống kê doanh thu theo ngày
    SELECT 
        CAST(OrderDate AS DATE) AS OrderDate,
        COUNT(OrderID) AS OrderCount,
        SUM(TotalAmount) AS DailyRevenue
    FROM 
        Orders
    WHERE 
        CAST(OrderDate AS DATE) BETWEEN @StartDate AND @EndDate
        AND Status != 'Cancelled'
    GROUP BY 
        CAST(OrderDate AS DATE)
    ORDER BY 
        CAST(OrderDate AS DATE);
    
    -- Thống kê doanh thu theo danh mục
    SELECT 
        c.CategoryID,
        c.CategoryName,
        SUM(od.Quantity * od.Price) AS CategoryRevenue,
        SUM(od.Quantity) AS TotalQuantitySold
    FROM 
        Categories c
        JOIN Products p ON c.CategoryID = p.CategoryID
        JOIN ProductVariants pv ON p.ProductID = pv.ProductID
        JOIN OrderDetails od ON pv.VariantID = od.VariantID
        JOIN Orders o ON od.OrderID = o.OrderID
    WHERE 
        CAST(o.OrderDate AS DATE) BETWEEN @StartDate AND @EndDate
        AND o.Status != 'Cancelled'
    GROUP BY 
        c.CategoryID, c.CategoryName
    ORDER BY 
        CategoryRevenue DESC;
    
    -- Thống kê sản phẩm bán chạy
    SELECT TOP 10
        p.ProductID,
        p.ProductName,
        c.CategoryName,
        SUM(od.Quantity) AS TotalSold,
        SUM(od.Quantity * od.Price) AS TotalRevenue
    FROM 
        Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        JOIN ProductVariants pv ON p.ProductID = pv.ProductID
        JOIN OrderDetails od ON pv.VariantID = od.VariantID
        JOIN Orders o ON od.OrderID = o.OrderID
    WHERE 
        CAST(o.OrderDate AS DATE) BETWEEN @StartDate AND @EndDate
        AND o.Status != 'Cancelled'
    GROUP BY 
        p.ProductID, p.ProductName, c.CategoryName
    ORDER BY 
        TotalSold DESC;
    
    RETURN 0;
END;
GO

-- =============================================
-- Thêm dữ liệu mẫu
-- =============================================

-- Thêm dữ liệu mẫu cho bảng Categories
INSERT INTO Categories (CategoryName, Description)
VALUES 
    (N'Áo nam', N'Các loại áo dành cho nam giới'),
    (N'Quần nam', N'Các loại quần dành cho nam giới'),
    (N'Áo nữ', N'Các loại áo dành cho nữ giới'),
    (N'Quần nữ', N'Các loại quần dành cho nữ giới'),
    (N'Váy đầm', N'Các loại váy và đầm dành cho nữ giới'),
    (N'Phụ kiện', N'Các loại phụ kiện thời trang');
GO

-- Thêm dữ liệu mẫu cho bảng Colors
INSERT INTO Colors (ColorName)
VALUES 
    (N'Đen'),
    (N'Trắng'),
    (N'Đỏ'),
    (N'Xanh dương'),
    (N'Xanh lá'),
    (N'Vàng'),
    (N'Hồng'),
    (N'Xám'),
    (N'Nâu');
GO

-- Thêm dữ liệu mẫu cho bảng Sizes
INSERT INTO Sizes (SizeName)
VALUES 
    ('S'),
    ('M'),
    ('L'),
    ('XL'),
    ('XXL'),
    ('28'),
    ('29'),
    ('30'),
    ('31'),
    ('32'),
    ('33'),
    ('34');
GO

-- Thêm dữ liệu mẫu cho bảng Customers
INSERT INTO Customers (FullName, Email, Password, PhoneNumber, Address)
VALUES 
    (N'Nguyễn Văn An', 'an.nguyen@example.com', 'hashed_password_1', '0901234567', N'123 Đường Lê Lợi, Quận 1, TP.HCM'),
    (N'Trần Thị Bình', 'binh.tran@example.com', 'hashed_password_2', '0912345678', N'456 Đường Nguyễn Huệ, Quận 1, TP.HCM'),
    (N'Lê Văn Cường', 'cuong.le@example.com', 'hashed_password_3', '0923456789', N'789 Đường Cách Mạng Tháng 8, Quận 3, TP.HCM'),
    (N'Phạm Thị Dung', 'dung.pham@example.com', 'hashed_password_4', '0934567890', N'101 Đường Võ Văn Tần, Quận 3, TP.HCM'),
    (N'Hoàng Văn Em', 'em.hoang@example.com', 'hashed_password_5', '0945678901', N'202 Đường Nguyễn Thị Minh Khai, Quận 1, TP.HCM'),
	(N'Nguyễn Thị Hương', 'huong.nguyen@example.com', 'password123', '0987654321', N'25 Đường Lý Tự Trọng, Quận 1, TP.HCM'),
    (N'Trần Văn Minh', 'minh.tran@example.com', 'password456', '0976543210', N'42 Đường Nguyễn Đình Chiểu, Quận 3, TP.HCM'),
    (N'Lê Thị Lan', 'lan.le@example.com', 'password789', '0965432109', N'78 Đường Trần Hưng Đạo, Quận 5, TP.HCM'),
    (N'Phạm Văn Đức', 'duc.pham@example.com', 'passwordabc', '0954321098', N'15 Đường Lê Duẩn, Quận 1, TP.HCM'),
    (N'Vũ Thị Mai', 'mai.vu@example.com', 'passworddef', '0943210987', N'63 Đường Nguyễn Trãi, Quận 5, TP.HCM'),
    (N'Đặng Văn Hùng', 'hung.dang@example.com', 'passwordghi', '0932109876', N'92 Đường Võ Thị Sáu, Quận 3, TP.HCM'),
    (N'Hoàng Thị Thảo', 'thao.hoang@example.com', 'passwordjkl', '0921098765', N'37 Đường Điện Biên Phủ, Quận Bình Thạnh, TP.HCM'),
    (N'Ngô Văn Tùng', 'tung.ngo@example.com', 'passwordmno', '0910987654', N'54 Đường Phan Đình Phùng, Quận Phú Nhuận, TP.HCM'),
    (N'Bùi Thị Hà', 'ha.bui@example.com', 'passwordpqr', '0909876543', N'29 Đường Nguyễn Văn Cừ, Quận 5, TP.HCM'),
    (N'Đỗ Văn Nam', 'nam.do@example.com', 'passwordstu', '0898765432', N'81 Đường Cách Mạng Tháng 8, Quận 10, TP.HCM');
GO

-- Thêm dữ liệu mẫu cho bảng Products
INSERT INTO Products (ProductName, Description, Price, CategoryID)
VALUES 
    (N'Áo sơ mi nam trắng', N'Áo sơ mi nam màu trắng chất liệu cotton cao cấp, thiết kế đơn giản, lịch sự', 350000, 1),
    (N'Áo thun nam đen', N'Áo thun nam màu đen chất liệu cotton, thiết kế đơn giản, thoải mái', 250000, 1),
    (N'Quần jean nam xanh', N'Quần jean nam màu xanh đậm, chất liệu denim co giãn, form slim fit', 450000, 2),
    (N'Quần kaki nam nâu', N'Quần kaki nam màu nâu, chất liệu kaki cao cấp, form regular', 400000, 2),
    (N'Áo sơ mi nữ trắng', N'Áo sơ mi nữ màu trắng chất liệu lụa, thiết kế thanh lịch', 320000, 3),
    (N'Áo thun nữ hồng', N'Áo thun nữ màu hồng pastel, chất liệu cotton mềm mại', 220000, 3),
    (N'Quần jean nữ xanh nhạt', N'Quần jean nữ màu xanh nhạt, chất liệu denim co giãn, form skinny', 420000, 4),
    (N'Váy đầm suông đen', N'Váy đầm suông màu đen, chất liệu vải mềm, thiết kế đơn giản, thanh lịch', 550000, 5),
    (N'Váy đầm xòe hoa', N'Váy đầm xòe họa tiết hoa, chất liệu vải mềm mại, phù hợp mùa hè', 650000, 5),
    (N'Thắt lưng da nam', N'Thắt lưng da bò màu đen, khóa kim loại cao cấp', 300000, 6),
	(N'Áo sơ mi nam kẻ sọc', N'Áo sơ mi nam kẻ sọc xanh trắng, chất liệu cotton thoáng mát', 380000, 1),
    (N'Áo polo nam thể thao', N'Áo polo nam thể thao, chất liệu thun co giãn, thoáng khí', 280000, 1),
    (N'Quần short nam kaki', N'Quần short nam kaki, phù hợp mùa hè, form regular', 320000, 2),
    (N'Quần jogger nam', N'Quần jogger nam chất liệu nỉ, co giãn tốt, phù hợp thể thao', 350000, 2),
    (N'Áo kiểu nữ công sở', N'Áo kiểu nữ công sở, thiết kế thanh lịch, chất liệu lụa cao cấp', 420000, 3),
    (N'Áo khoác nữ nhẹ', N'Áo khoác nữ nhẹ chất liệu dù, chống nắng, chống gió nhẹ', 450000, 3),
    (N'Quần culottes nữ', N'Quần culottes nữ ống rộng, chất liệu vải mềm, thoáng mát', 380000, 4),
    (N'Quần legging nữ thể thao', N'Quần legging nữ thể thao, co giãn 4 chiều, thoát mồ hôi tốt', 250000, 4),
    (N'Váy liền thân công sở', N'Váy liền thân công sở, thiết kế thanh lịch, kín đáo', 580000, 5),
    (N'Đầm maxi đi biển', N'Đầm maxi đi biển, chất liệu voan nhẹ, họa tiết hoa', 620000, 5),
    (N'Mũ bucket thời trang', N'Mũ bucket thời trang, chất liệu cotton, phù hợp đi chơi, dã ngoại', 180000, 6),
    (N'Túi xách nữ công sở', N'Túi xách nữ công sở, chất liệu da PU cao cấp, nhiều ngăn tiện lợi', 480000, 6);
GO

-- Thêm dữ liệu mẫu cho bảng ProductVariants
-- Áo sơ mi nam trắng
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (1, 2, 1, 20), -- Trắng, S
    (1, 2, 2, 30), -- Trắng, M
    (1, 2, 3, 25), -- Trắng, L
    (1, 2, 4, 15); -- Trắng, XL

-- Áo thun nam đen
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (2, 1, 1, 25), -- Đen, S
    (2, 1, 2, 35), -- Đen, M
    (2, 1, 3, 30), -- Đen, L
    (2, 1, 4, 20), -- Đen, XL
    (2, 8, 1, 15), -- Xám, S
    (2, 8, 2, 25), -- Xám, M
    (2, 8, 3, 20), -- Xám, L
    (2, 8, 4, 10); -- Xám, XL

-- Quần jean nam xanh
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (3, 4, 6, 15),  -- Xanh dương, 28
    (3, 4, 7, 20),  -- Xanh dương, 29
    (3, 4, 8, 25),  -- Xanh dương, 30
    (3, 4, 9, 20),  -- Xanh dương, 31
    (3, 4, 10, 15), -- Xanh dương, 32
    (3, 4, 11, 10); -- Xanh dương, 33

-- Quần kaki nam nâu
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (4, 9, 6, 10),  -- Nâu, 28
    (4, 9, 7, 15),  -- Nâu, 29
    (4, 9, 8, 20),  -- Nâu, 30
    (4, 9, 9, 15),  -- Nâu, 31
    (4, 9, 10, 10), -- Nâu, 32
    (4, 9, 11, 5);  -- Nâu, 33

-- Áo sơ mi nữ trắng
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (5, 2, 1, 20), -- Trắng, S
    (5, 2, 2, 30), -- Trắng, M
    (5, 2, 3, 20); -- Trắng, L

-- Áo thun nữ hồng
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (6, 7, 1, 25), -- Hồng, S
    (6, 7, 2, 35), -- Hồng, M
    (6, 7, 3, 25), -- Hồng, L
    (6, 2, 1, 20), -- Trắng, S
    (6, 2, 2, 30), -- Trắng, M
    (6, 2, 3, 20); -- Trắng, L

-- Quần jean nữ xanh nhạt
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (7, 4, 6, 15),  -- Xanh dương, 28
    (7, 4, 7, 20),  -- Xanh dương, 29
    (7, 4, 8, 15),  -- Xanh dương, 30
    (7, 4, 9, 10);  -- Xanh dương, 31

-- Váy đầm suông đen
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (8, 1, 1, 15), -- Đen, S
    (8, 1, 2, 25), -- Đen, M
    (8, 1, 3, 15); -- Đen, L

-- Váy đầm xòe hoa (giả sử màu chính là hồng)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (9, 7, 1, 10), -- Hồng, S
    (9, 7, 2, 20), -- Hồng, M
    (9, 7, 3, 10); -- Hồng, L

-- Thắt lưng da nam (chỉ có màu đen và nâu, không có size)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (10, 1, 1, 30), -- Đen, S (giả sử S là size nhỏ)
    (10, 9, 1, 25); -- Nâu, S

-- Áo sơ mi nam kẻ sọc (ProductID: 11)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (11, 4, 1, 15), -- Xanh dương, S
    (11, 4, 2, 25), -- Xanh dương, M
    (11, 4, 3, 20), -- Xanh dương, L
    (11, 4, 4, 10); -- Xanh dương, XL

-- Áo polo nam thể thao (ProductID: 12)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (12, 1, 1, 20), -- Đen, S
    (12, 1, 2, 30), -- Đen, M
    (12, 1, 3, 25), -- Đen, L
    (12, 4, 1, 15), -- Xanh dương, S
    (12, 4, 2, 25), -- Xanh dương, M
    (12, 4, 3, 20), -- Xanh dương, L
    (12, 3, 1, 10), -- Đỏ, S
    (12, 3, 2, 15), -- Đỏ, M
    (12, 3, 3, 10); -- Đỏ, L

-- Quần short nam kaki (ProductID: 13)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (13, 1, 8, 20),  -- Đen, 30
    (13, 1, 9, 15),  -- Đen, 31
    (13, 1, 10, 10), -- Đen, 32
    (13, 9, 8, 15),  -- Nâu, 30
    (13, 9, 9, 10),  -- Nâu, 31
    (13, 9, 10, 5),  -- Nâu, 32
    (13, 8, 8, 15),  -- Xám, 30
    (13, 8, 9, 10),  -- Xám, 31
    (13, 8, 10, 5);  -- Xám, 32

-- Quần jogger nam (ProductID: 14)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (14, 1, 1, 25), -- Đen, S
    (14, 1, 2, 35), -- Đen, M
    (14, 1, 3, 30), -- Đen, L
    (14, 8, 1, 20), -- Xám, S
    (14, 8, 2, 30), -- Xám, M
    (14, 8, 3, 25), -- Xám, L
    (14, 5, 1, 15), -- Xanh lá, S
    (14, 5, 2, 25), -- Xanh lá, M
    (14, 5, 3, 20); -- Xanh lá, L

-- Áo kiểu nữ công sở (ProductID: 15)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (15, 2, 1, 20), -- Trắng, S
    (15, 2, 2, 30), -- Trắng, M
    (15, 2, 3, 15), -- Trắng, L
    (15, 1, 1, 15), -- Đen, S
    (15, 1, 2, 25), -- Đen, M
    (15, 1, 3, 10), -- Đen, L
    (15, 7, 1, 10), -- Hồng, S
    (15, 7, 2, 20), -- Hồng, M
    (15, 7, 3, 5);  -- Hồng, L

-- Áo khoác nữ nhẹ (ProductID: 16)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (16, 1, 1, 15), -- Đen, S
    (16, 1, 2, 25), -- Đen, M
    (16, 1, 3, 10), -- Đen, L
    (16, 4, 1, 10), -- Xanh dương, S
    (16, 4, 2, 20), -- Xanh dương, M
    (16, 4, 3, 5),  -- Xanh dương, L
    (16, 7, 1, 10), -- Hồng, S
    (16, 7, 2, 15), -- Hồng, M
    (16, 7, 3, 5);  -- Hồng, L

-- Quần culottes nữ (ProductID: 17)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (17, 1, 1, 20), -- Đen, S
    (17, 1, 2, 30), -- Đen, M
    (17, 1, 3, 15), -- Đen, L
    (17, 9, 1, 15), -- Nâu, S
    (17, 9, 2, 25), -- Nâu, M
    (17, 9, 3, 10), -- Nâu, L
    (17, 8, 1, 10), -- Xám, S
    (17, 8, 2, 20), -- Xám, M
    (17, 8, 3, 5);  -- Xám, L

-- Quần legging nữ thể thao (ProductID: 18)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (18, 1, 1, 25), -- Đen, S
    (18, 1, 2, 35), -- Đen, M
    (18, 1, 3, 20), -- Đen, L
    (18, 8, 1, 15), -- Xám, S
    (18, 8, 2, 25), -- Xám, M
    (18, 8, 3, 10), -- Xám, L
    (18, 4, 1, 10), -- Xanh dương, S
    (18, 4, 2, 20), -- Xanh dương, M
    (18, 4, 3, 5);  -- Xanh dương, L

-- Váy liền thân công sở (ProductID: 19)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (19, 1, 1, 15), -- Đen, S
    (19, 1, 2, 25), -- Đen, M
    (19, 1, 3, 10), -- Đen, L
    (19, 9, 1, 10), -- Nâu, S
    (19, 9, 2, 20), -- Nâu, M
    (19, 9, 3, 5),  -- Nâu, L
    (19, 4, 1, 10), -- Xanh dương, S
    (19, 4, 2, 15), -- Xanh dương, M
    (19, 4, 3, 5);  -- Xanh dương, L

-- Đầm maxi đi biển (ProductID: 20)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (20, 4, 1, 15), -- Xanh dương, S
    (20, 4, 2, 25), -- Xanh dương, M
    (20, 4, 3, 10), -- Xanh dương, L
    (20, 7, 1, 20), -- Hồng, S
    (20, 7, 2, 30), -- Hồng, M
    (20, 7, 3, 15), -- Hồng, L
    (20, 6, 1, 10), -- Vàng, S
    (20, 6, 2, 20), -- Vàng, M
    (20, 6, 3, 5);  -- Vàng, L

-- Mũ bucket thời trang (ProductID: 21)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (21, 1, 1, 30), -- Đen, S
    (21, 2, 1, 25), -- Trắng, S
    (21, 4, 1, 20), -- Xanh dương, S
    (21, 7, 1, 15); -- Hồng, S

-- Túi xách nữ công sở (ProductID: 22)
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
VALUES 
    (22, 1, 1, 20), -- Đen, S
    (22, 9, 1, 15), -- Nâu, S
    (22, 3, 1, 10); -- Đỏ, S

-- Tạo một số đơn hàng mẫu
DECLARE @OrderID1 INT, @OrderID2 INT, @OrderID3 INT;

-- Đơn hàng 1
EXEC sp_CreateOrder 1, N'Thanh toán khi nhận hàng', N'123 Đường Lê Lợi, Quận 1, TP.HCM', @OrderID1 OUTPUT;
EXEC sp_AddOrderDetail @OrderID1, 1, 1; -- Áo sơ mi nam trắng, size S
EXEC sp_AddOrderDetail @OrderID1, 5, 2; -- Áo thun nam đen, size M, màu xám

-- Đơn hàng 2
EXEC sp_CreateOrder 2, N'Chuyển khoản ngân hàng', N'456 Đường Nguyễn Huệ, Quận 1, TP.HCM', @OrderID2 OUTPUT;
EXEC sp_AddOrderDetail @OrderID2, 10, 1; -- Quần jean nam xanh, size 28
EXEC sp_AddOrderDetail @OrderID2, 20, 1; -- Váy đầm suông đen, size S

-- Đơn hàng 3
EXEC sp_CreateOrder 3, N'Thanh toán khi nhận hàng', N'789 Đường Cách Mạng Tháng 8, Quận 3, TP.HCM', @OrderID3 OUTPUT;
EXEC sp_AddOrderDetail @OrderID3, 15, 2; -- Áo thun nữ hồng, size M
EXEC sp_AddOrderDetail @OrderID3, 25, 1; -- Thắt lưng da nam, màu đen

-- Cập nhật trạng thái đơn hàng
EXEC sp_UpdateOrderStatus @OrderID1, 'Shipped';
EXEC sp_UpdateOrderStatus @OrderID2, 'Delivered';
GO

-- =============================================
-- Ví dụ sử dụng
-- =============================================

-- 1. Tìm kiếm sản phẩm theo tên và danh mục
-- EXEC sp_SearchProducts @SearchTerm = N'áo', @CategoryID = 1, @InStockOnly = 1;

-- 2. Xem doanh thu theo tháng
-- SELECT * FROM vw_MonthlyRevenue ORDER BY Year DESC, Month DESC;

-- 3. Xem sản phẩm bán chạy
-- SELECT * FROM vw_BestSellingProducts;

-- 4. Xem sản phẩm còn hàng
-- SELECT * FROM vw_AvailableProducts;

-- 5. Xem lịch sử mua hàng của khách hàng
-- SELECT * FROM vw_CustomerPurchaseHistory WHERE CustomerID = 1;

-- 6. Thống kê doanh thu theo khoảng thời gian
-- EXEC sp_GetRevenueByDateRange '2023-01-01', '2023-12-31';

-- 7. Lấy danh sách đơn hàng của khách hàng
-- EXEC sp_GetCustomerOrders 2;

-- 8. Xem chi tiết đơn hàng
-- EXEC sp_GetOrderDetails 1;

-- 9. Thêm sản phẩm mới và biến thể
/*
DECLARE @NewProductID INT, @NewVariantID INT;
EXEC sp_AddProduct N'Áo khoác nam mùa đông', N'Áo khoác nam chống nước, giữ ấm tốt cho mùa đông', 850000, 1, @NewProductID OUTPUT;
EXEC sp_AddProductVariant @NewProductID, 1, 2, 10, @NewVariantID OUTPUT; -- Đen, M, 10 cái
EXEC sp_AddProductVariant @NewProductID, 1, 3, 15, @NewVariantID OUTPUT; -- Đen, L, 15 cái
EXEC sp_AddProductVariant @NewProductID, 8, 2, 8, @NewVariantID OUTPUT;  -- Xám, M, 8 cái
EXEC sp_AddProductVariant @NewProductID, 8, 3, 12, @NewVariantID OUTPUT; -- Xám, L, 12 cái
*/

-- 10. Tạo đơn hàng mới
/*
DECLARE @NewOrderID INT;
EXEC sp_CreateOrder 4, N'Thanh toán khi nhận hàng', N'101 Đường Võ Văn Tần, Quận 3, TP.HCM', @NewOrderID OUTPUT;
EXEC sp_AddOrderDetail @NewOrderID, 3, 2; -- Áo sơ mi nam trắng, size M
EXEC sp_AddOrderDetail @NewOrderID, 10, 1; -- Quần jean nam xanh, size 28
EXEC sp_UpdateOrderStatus @NewOrderID, 'Processing';
*/

SELECT ProductID, ImageURL FROM Products WHERE ProductID = 5;
