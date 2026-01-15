use FashionStoreDB;

-- Create Wishlist table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Wishlist')
BEGIN
    CREATE TABLE Wishlist (
        WishlistID INT PRIMARY KEY IDENTITY(1,1),
        CustomerID INT FOREIGN KEY REFERENCES Customers(CustomerID),
        ProductID INT FOREIGN KEY REFERENCES Products(ProductID),
        AddedDate DATETIME DEFAULT GETDATE(),
        CONSTRAINT UC_CustomerProduct UNIQUE (CustomerID, ProductID)
    );
END

-- Create Reviews table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Reviews')
BEGIN
    CREATE TABLE Reviews (
        ReviewID INT PRIMARY KEY IDENTITY(1,1),
        CustomerID INT FOREIGN KEY REFERENCES Customers(CustomerID),
        ProductID INT FOREIGN KEY REFERENCES Products(ProductID),
        Rating INT NOT NULL CHECK (Rating BETWEEN 1 AND 5),
        Comment NVARCHAR(MAX) NULL,
        ReviewDate DATETIME DEFAULT GETDATE(),
        CONSTRAINT UC_CustomerProductReview UNIQUE (CustomerID, ProductID)
    );
END

-- Create ContactMessages table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ContactMessages')
BEGIN
    CREATE TABLE ContactMessages (
        MessageID INT PRIMARY KEY IDENTITY(1,1),
        Name NVARCHAR(255) NOT NULL,
        Email NVARCHAR(255) NOT NULL,
        Subject NVARCHAR(255) NULL,
        Message NVARCHAR(MAX) NOT NULL,
        SubmitDate DATETIME DEFAULT GETDATE(),
        Status NVARCHAR(50) DEFAULT 'New'
    );
END

-- Create NewsletterSubscribers table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'NewsletterSubscribers')
BEGIN
    CREATE TABLE NewsletterSubscribers (
        SubscriberID INT PRIMARY KEY IDENTITY(1,1),
        Email NVARCHAR(255) NOT NULL UNIQUE,
        SubscribeDate DATETIME DEFAULT GETDATE(),
        IsActive BIT DEFAULT 1
    );
END

-- Add some sample reviews
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES 
    (1, 1, 5, N'Sản phẩm rất tốt, chất lượng cao, đúng như mô tả.', DATEADD(DAY, -5, GETDATE())),
    (2, 1, 4, N'Tôi rất hài lòng với sản phẩm này, giao hàng nhanh.', DATEADD(DAY, -3, GETDATE())),
    (3, 2, 5, N'Áo rất đẹp, form chuẩn, mặc rất thoải mái.', DATEADD(DAY, -7, GETDATE())),
    (4, 3, 4, N'Quần jean chất lượng tốt, đường may đẹp.', DATEADD(DAY, -10, GETDATE())),
    (5, 5, 5, N'Áo sơ mi trắng rất đẹp, vải mềm và thoáng mát.', DATEADD(DAY, -2, GETDATE()));

-- Add some sample wishlist items
INSERT INTO Wishlist (CustomerID, ProductID, AddedDate)
VALUES 
    (1, 2, DATEADD(DAY, -3, GETDATE())),
    (1, 5, DATEADD(DAY, -2, GETDATE())),
    (2, 3, DATEADD(DAY, -5, GETDATE())),
    (3, 1, DATEADD(DAY, -1, GETDATE())),
    (4, 9, DATEADD(DAY, -4, GETDATE()));

-- Add some sample contact messages
INSERT INTO ContactMessages (Name, Email, Subject, Message, SubmitDate, Status)
VALUES 
    (N'Nguyễn Văn A', 'nguyenvana@example.com', N'Hỏi về chính sách đổi trả', N'Tôi muốn biết thêm về chính sách đổi trả của cửa hàng. Cảm ơn!', DATEADD(DAY, -7, GETDATE()), 'Answered'),
    (N'Trần Thị B', 'tranthib@example.com', N'Vấn đề về đơn hàng', N'Đơn hàng của tôi bị chậm giao, mã đơn hàng là #123. Mong được hỗ trợ.', DATEADD(DAY, -3, GETDATE()), 'Processing'),
    (N'Lê Văn C', 'levanc@example.com', N'Hợp tác kinh doanh', N'Tôi muốn hợp tác kinh doanh với cửa hàng của bạn. Vui lòng liên hệ lại với tôi.', DATEADD(DAY, -1, GETDATE()), 'New');

-- Add some sample newsletter subscribers
INSERT INTO NewsletterSubscribers (Email, SubscribeDate, IsActive)
VALUES 
    ('subscriber1@example.com', DATEADD(DAY, -30, GETDATE()), 1),
    ('subscriber2@example.com', DATEADD(DAY, -25, GETDATE()), 1),
    ('subscriber3@example.com', DATEADD(DAY, -20, GETDATE()), 1),
    ('subscriber4@example.com', DATEADD(DAY, -15, GETDATE()), 1),
    ('subscriber5@example.com', DATEADD(DAY, -10, GETDATE()), 1);

-- Create a view for product ratings
go
CREATE OR ALTER VIEW vw_ProductRatings AS
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
go

-- Create ProductComments table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ProductComments')
BEGIN
    CREATE TABLE ProductComments (
        CommentID INT PRIMARY KEY IDENTITY(1,1),
        CustomerID INT FOREIGN KEY REFERENCES Customers(CustomerID),
        ProductID INT FOREIGN KEY REFERENCES Products(ProductID),
        Content NVARCHAR(MAX) NOT NULL,
        CommentDate DATETIME DEFAULT GETDATE(),
        AdminReply NVARCHAR(MAX) NULL,
        ReplyDate DATETIME NULL,
        IsVisible BIT DEFAULT 1
    );
END

-- Add some sample comments
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES 
    (1, 1, N'Sản phẩm rất đẹp, đúng như mô tả. Tôi rất hài lòng với chất lượng vải.', DATEADD(DAY, -7, GETDATE()), 
     N'Cảm ơn bạn đã mua hàng và đánh giá sản phẩm. Chúng tôi rất vui khi bạn hài lòng!', DATEADD(DAY, -6, GETDATE()), 1),
    
    (2, 1, N'Tôi đã mua áo này cho chồng tôi, anh ấy rất thích. Size vừa vặn, màu sắc đẹp.', DATEADD(DAY, -5, GETDATE()), 
     NULL, NULL, 1),
    
    (3, 2, N'Áo thun chất lượng tốt, nhưng tôi nghĩ màu hơi khác so với hình ảnh trên website.', DATEADD(DAY, -4, GETDATE()), 
     N'Xin lỗi vì sự khác biệt về màu sắc. Đôi khi màu sắc có thể hiển thị khác nhau tùy thuộc vào màn hình. Nếu bạn không hài lòng, bạn có thể đổi trả trong vòng 30 ngày.', DATEADD(DAY, -3, GETDATE()), 1),
    
    (4, 3, N'Quần jean rất thoải mái, form dáng đẹp. Tôi sẽ mua thêm màu khác.', DATEADD(DAY, -3, GETDATE()), 
     NULL, NULL, 1),
    
    (5, 5, N'Áo sơ mi trắng rất đẹp, nhưng hơi nhỏ so với size thông thường. Nên đặt size lớn hơn 1.', DATEADD(DAY, -2, GETDATE()), 
     N'Cảm ơn bạn đã chia sẻ kinh nghiệm. Chúng tôi sẽ cập nhật thông tin về kích thước trong mô tả sản phẩm.', DATEADD(DAY, -1, GETDATE()), 1);

-- Tạo bảng để lưu trữ token đặt lại mật khẩu
CREATE TABLE PasswordResetTokens (
    TokenID INT PRIMARY KEY IDENTITY(1,1),
    CustomerID INT NOT NULL,
    Token VARCHAR(100) NOT NULL,
    ExpiryDate DATETIME NOT NULL,
    IsUsed BIT DEFAULT 0,
    CreatedAt DATETIME DEFAULT GETDATE(),
    FOREIGN KEY (CustomerID) REFERENCES Customers(CustomerID)
);

-- Thêm cột để lưu trạng thái dark mode cho người dùng
ALTER TABLE Customers
ADD DarkModeEnabled BIT DEFAULT 0;

-- Thêm bình luận đa dạng có phản hồi cho từng sản phẩm
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 1, N'Giao hàng hơi chậm một chút.', '2025-05-21 07:26:10', N'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 1, N'Không quá đặc biệt nhưng dùng được.', '2025-05-21 07:26:10', N'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-22 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 1, N'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-16 07:26:10', N'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-17 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 2, N'Mua lần 2 rồi, vẫn rất thích.', '2025-05-17 07:26:10', N'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-18 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 2, N'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-17 07:26:10', N'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-18 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 2, N'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-16 07:26:10', N'Nếu bạn cần hỗ trợ thêm, hãy liên hệ hotline hoặc fanpage.', '2025-05-18 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (10, 3, N'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-18 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (11, 3, N'Size không chuẩn, mặc hơi chật.', '2025-05-18 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (12, 3, N'Mua lần 2 rồi, vẫn rất thích.', '2025-05-18 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (13, 4, N'Đường may chưa được đẹp.', '2025-05-22 07:26:10', N'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-24 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (14, 4, N'Không giống hình, thất vọng nhẹ.', '2025-05-18 07:26:10', N'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (15, 4, N'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', N'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (16, 5, N'Vải hơi thô, không như mong đợi.', '2025-05-18 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (17, 5, N'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (18, 5, N'Size không chuẩn, mặc hơi chật.', '2025-05-22 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (19, 6, N'Mua lần 2 rồi, vẫn rất thích.', '2025-05-17 07:26:10', N'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (20, 6, N'Vải hơi thô, không như mong đợi.', '2025-05-15 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (1, 6, N'Form chuẩn, mặc rất vừa.', '2025-05-18 07:26:10', N'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (2, 7, N'Không quá đặc biệt nhưng dùng được.', '2025-05-21 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-22 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (3, 7, N'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-15 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 7, N'Vải hơi thô, không như mong đợi.', '2025-05-15 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-16 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 8, N'Màu bị phai sau khi giặt lần đầu.', '2025-05-16 07:26:10', N'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-17 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 8, N'Mua lần 2 rồi, vẫn rất thích.', '2025-05-20 07:26:10', N'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-22 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 8, N'Giao hàng hơi chậm một chút.', '2025-05-22 07:26:10', N'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 9, N'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', N'Nếu bạn cần hỗ trợ thêm, hãy liên hệ hotline hoặc fanpage.', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 9, N'Màu bị phai sau khi giặt lần đầu.', '2025-05-19 07:26:10', N'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-20 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (10, 9, N'Cũng được, không có gì nổi bật.', '2025-05-20 07:26:10', N'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-22 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (11, 10, N'Sản phẩm rất đẹp và chất lượng.', '2025-05-15 07:26:10', N'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-16 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (12, 10, N'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-22 07:26:10', N'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (13, 10, N'Form chuẩn, mặc rất vừa.', '2025-05-17 07:26:10', N'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-18 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (14, 11, N'Không quá đặc biệt nhưng dùng được.', '2025-05-17 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (15, 11, N'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-19 07:26:10', N'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-21 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (16, 11, N'Không quá đặc biệt nhưng dùng được.', '2025-05-17 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-18 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (17, 12, N'Màu bị phai sau khi giặt lần đầu.', '2025-05-15 07:26:10', N'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-17 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (18, 12, N'Mua lần 2 rồi, vẫn rất thích.', '2025-05-21 07:26:10', N'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (19, 12, N'Size không chuẩn, mặc hơi chật.', '2025-05-19 07:26:10', N'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-20 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (20, 13, N'Size không chuẩn, mặc hơi chật.', '2025-05-15 07:26:10', N'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-17 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (1, 13, N'Đường may chưa được đẹp.', '2025-05-19 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (2, 13, N'Màu bị phai sau khi giặt lần đầu.', '2025-05-19 07:26:10', N'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-21 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (3, 14, N'Giao hàng hơi chậm một chút.', '2025-05-20 07:26:10', N'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-22 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 14, N'Đường may chưa được đẹp.', '2025-05-18 07:26:10', N'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-20 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 14, N'Mua lần 2 rồi, vẫn rất thích.', '2025-05-20 07:26:10', N'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-21 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 15, N'Size không chuẩn, mặc hơi chật.', '2025-05-15 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-16 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 15, N'Size không chuẩn, mặc hơi chật.', '2025-05-22 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 15, N'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-18 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 16, N'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', N'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-18 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (10, 16, N'Màu bị phai sau khi giặt lần đầu.', '2025-05-15 07:26:10', N'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-17 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (11, 16, N'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-18 07:26:10', N'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (12, 17, N'Sản phẩm rất đẹp và chất lượng.', '2025-05-19 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (13, 17, N'Form chuẩn, mặc rất vừa.', '2025-05-19 07:26:10', N'Nếu bạn cần hỗ trợ thêm, hãy liên hệ hotline hoặc fanpage.', '2025-05-21 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (14, 17, N'Giao hàng hơi chậm một chút.', '2025-05-20 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (15, 18, N'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-18 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (16, 18, N'Cũng được, không có gì nổi bật.', '2025-05-18 07:26:10', N'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-20 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (17, 18, N'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-20 07:26:10', NULL, NULL, 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (18, 19, N'Cũng được, không có gì nổi bật.', '2025-05-20 07:26:10', N'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-21 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (19, 19, N'Màu bị phai sau khi giặt lần đầu.', '2025-05-18 07:26:10', N'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-19 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (20, 19, N'Giao hàng hơi chậm một chút.', '2025-05-21 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (1, 20, N'Size không chuẩn, mặc hơi chật.', '2025-05-22 07:26:10', N'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (2, 20, N'Sản phẩm rất đẹp và chất lượng.', '2025-05-22 07:26:10', N'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-24 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (3, 20, N'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-22 07:26:10', N'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-24 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 21, N'Không giống hình, thất vọng nhẹ.', '2025-05-20 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-22 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 21, N'Mình rất hài lòng, giao hàng nhanh.', '2025-05-21 07:26:10', N'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 21, N'Mua lần 2 rồi, vẫn rất thích.', '2025-05-21 07:26:10', N'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-23 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 22, N'Sản phẩm rất đẹp và chất lượng.', '2025-05-17 07:26:10', N'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-18 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 22, N'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-20 07:26:10', N'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-21 07:26:10', 1);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 22, N'Size không chuẩn, mặc hơi chật.', '2025-05-20 07:26:10', N'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-21 07:26:10', 1);

-- Thêm đánh giá sản phẩm
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 1, 5, N'Sản phẩm tuyệt vời!', '2025-05-16 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (13, 1, 1, N'Không hài lòng, sản phẩm lỗi.', '2025-05-23 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 1, 4, N'Hàng tốt, giao nhanh.', '2025-05-19 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (1, 2, 4, N'Mình thích sản phẩm này.', '2025-05-20 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (2, 2, 1, N'Khác xa ảnh, thất vọng.', '2025-05-12 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 2, 3, N'Cũng được nhưng không ấn tượng.', '2025-05-22 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 3, 1, N'Không hài lòng, sản phẩm lỗi.', '2025-05-17 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 3, 4, N'Mình thích sản phẩm này.', '2025-05-24 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (6, 3, 2, N'Chất lượng chưa như mong đợi.', '2025-05-16 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (2, 4, 2, N'Màu hơi khác hình.', '2025-05-13 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 4, 3, N'Hàng ổn so với giá.', '2025-05-17 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 4, 1, N'Giao sai màu, chất vải xấu.', '2025-05-16 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 5, 4, N'Tạm ổn, giống mô tả.', '2025-05-15 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 5, 2, N'Màu hơi khác hình.', '2025-05-19 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (5, 5, 4, N'Hàng tốt, giao nhanh.', '2025-05-14 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 6, 5, N'Chất lượng vượt mong đợi.', '2025-05-20 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 6, 3, N'Bình thường, không quá đặc biệt.', '2025-05-20 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (13, 6, 3, N'Bình thường, không quá đặc biệt.', '2025-05-24 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (14, 7, 1, N'Khác xa ảnh, thất vọng.', '2025-05-12 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (1, 7, 5, N'Sản phẩm tuyệt vời!', '2025-05-15 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 7, 2, N'Chất lượng chưa như mong đợi.', '2025-05-22 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 8, 4, N'Tạm ổn, giống mô tả.', '2025-05-22 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 8, 3, N'Hàng ổn so với giá.', '2025-05-17 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 8, 5, N'Sản phẩm tuyệt vời!', '2025-05-13 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 9, 2, N'Form hơi lệch, cần cải thiện.', '2025-05-14 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 9, 5, N'Rất hài lòng, sẽ mua lại.', '2025-05-12 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 9, 1, N'Khác xa ảnh, thất vọng.', '2025-05-22 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 10, 1, N'Giao sai màu, chất vải xấu.', '2025-05-24 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 10, 2, N'Màu hơi khác hình.', '2025-05-19 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 10, 4, N'Tạm ổn, giống mô tả.', '2025-05-24 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 11, 2, N'Màu hơi khác hình.', '2025-05-11 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 11, 1, N'Giao sai màu, chất vải xấu.', '2025-05-14 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 11, 3, N'Hàng ổn so với giá.', '2025-05-22 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 12, 2, N'Màu hơi khác hình.', '2025-05-24 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 12, 3, N'Bình thường, không quá đặc biệt.', '2025-05-18 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 12, 1, N'Khác xa ảnh, thất vọng.', '2025-05-22 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 13, 3, N'Cũng được nhưng không ấn tượng.', '2025-05-13 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 13, 5, N'Sản phẩm tuyệt vời!', '2025-05-21 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 13, 1, N'Giao sai màu, chất vải xấu.', '2025-05-16 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (6, 14, 4, N'Tạm ổn, giống mô tả.', '2025-05-18 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 14, 1, N'Khác xa ảnh, thất vọng.', '2025-05-20 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 14, 5, N'Sản phẩm tuyệt vời!', '2025-05-14 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 15, 2, N'Chất lượng chưa như mong đợi.', '2025-05-13 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 15, 5, N'Sản phẩm tuyệt vời!', '2025-05-18 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (13, 15, 4, N'Tạm ổn, giống mô tả.', '2025-05-24 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 16, 5, N'Sản phẩm tuyệt vời!', '2025-05-11 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 16, 4, N'Mình thích sản phẩm này.', '2025-05-14 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 16, 3, N'Cũng được nhưng không ấn tượng.', '2025-05-19 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 17, 2, N'Màu hơi khác hình.', '2025-05-24 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 17, 3, N'Bình thường, không quá đặc biệt.', '2025-05-17 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 17, 3, N'Bình thường, không quá đặc biệt.', '2025-05-21 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (12, 18, 4, N'Hàng tốt, giao nhanh.', '2025-05-18 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (3, 18, 1, N'Không hài lòng, sản phẩm lỗi.', '2025-05-15 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 18, 3, N'Cũng được nhưng không ấn tượng.', '2025-05-15 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (3, 19, 4, N'Hàng tốt, giao nhanh.', '2025-05-20 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (1, 19, 5, N'Sản phẩm tuyệt vời!', '2025-05-13 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 19, 5, N'Chất lượng vượt mong đợi.', '2025-05-22 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 20, 2, N'Form hơi lệch, cần cải thiện.', '2025-05-16 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 20, 3, N'Cũng được nhưng không ấn tượng.', '2025-05-20 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 20, 4, N'Tạm ổn, giống mô tả.', '2025-05-16 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (5, 21, 5, N'Chất lượng vượt mong đợi.', '2025-05-17 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 21, 4, N'Mình thích sản phẩm này.', '2025-05-17 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 21, 3, N'Cũng được nhưng không ấn tượng.', '2025-05-12 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 22, 1, N'Không hài lòng, sản phẩm lỗi.', '2025-05-15 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 22, 4, N'Mình thích sản phẩm này.', '2025-05-11 07:53:02');
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 22, 1, N'Khác xa ảnh, thất vọng.', '2025-05-21 07:53:02');