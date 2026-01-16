-- =============================================
-- DỮ LIỆU MẪU CHUẨN HÓA CHO FASHIONSTOREDB (POSTGRESQL)
-- =============================================

-- Xóa dữ liệu cũ và reset sequence
TRUNCATE TABLE OrderDetails, Orders, ProductVariants, ProductComments, Reviews, Wishlist, Products, Categories, Colors, Sizes, Customers, NewsletterSubscribers, PasswordResetTokens RESTART IDENTITY CASCADE;

-- 1. Categories
INSERT INTO Categories (CategoryID, CategoryName, Description) VALUES 
(1, 'Áo nam', 'Các loại áo dành cho nam giới'),
(2, 'Quần nam', 'Các loại quần dành cho nam giới'),
(3, 'Áo nữ', 'Các loại áo dành cho nữ giới'),
(4, 'Quần nữ', 'Các loại quần dành cho nữ giới'),
(5, 'Váy đầm', 'Các loại váy và đầm dành cho nữ giới'),
(6, 'Phụ kiện', 'Các loại phụ kiện thời trang');

-- 2. Colors
INSERT INTO Colors (ColorID, ColorName) VALUES 
(1, 'Đen'), (2, 'Trắng'), (3, 'Đỏ'), (4, 'Xanh dương'), (5, 'Xanh lá'),
(6, 'Vàng'), (7, 'Hồng'), (8, 'Xám'), (9, 'Nâu');

-- 3. Sizes
INSERT INTO Sizes (SizeID, SizeName) VALUES 
(1, 'S'), (2, 'M'), (3, 'L'), (4, 'XL'), (5, 'XXL'),
(6, '28'), (7, '29'), (8, '30'), (9, '31'), (10, '32'), (11, '33'), (12, '34');

-- 4. Customers (11 Customers)
INSERT INTO Customers (CustomerID, FullName, Email, Password, PhoneNumber, Address, IsAdmin, CreatedAt) VALUES 
(1, 'Nguyễn Văn An', 'an.nguyen@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0901234567', '123 Đường Lê Lợi, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(2, 'Trần Thị Bình', 'binh.tran@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0912345678', '456 Đường Nguyễn Huệ, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(3, 'Lê Văn Cường', 'cuong.le@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0923456789', '789 Đường Cách Mạng Tháng 8, Quận 3, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(4, 'Phạm Thị Dung', 'dung.pham@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0934567890', '101 Đường Võ Văn Tần, Quận 3, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(5, 'Hoàng Văn Em', 'em.hoang@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0945678901', '202 Đường Nguyễn Thị Minh Khai, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(6, 'Nguyễn Thị Hương', 'huong.nguyen@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0987654321', '25 Đường Lý Tự Trọng, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(7, 'Trần Văn Minh', 'minh.tran@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0976543210', '42 Đường Nguyễn Đình Chiểu, Quận 3, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(8, 'Lê Thị Lan', 'lan.le@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0965432109', '78 Đường Trần Hưng Đạo, Quận 5, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(9, 'Phạm Văn Đức', 'duc.pham@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0954321098', '15 Đường Lê Duẩn, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(10, 'Vũ Thị Mai', 'mai.vu@example.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0943210987', '63 Đường Nguyễn Trãi, Quận 5, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(11, 'Admin', 'admin123@gmail.com', 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3', '0000000000', 'Quản trị viên', TRUE, CURRENT_TIMESTAMP);

-- 5. Products (22 Products)
INSERT INTO Products (ProductID, ProductName, Description, Price, CategoryID, CreatedAt, ImageURL) VALUES 
(1, 'Áo sơ mi nam trắng', 'Áo sơ mi nam màu trắng chất liệu cotton cao cấp, thiết kế đơn giản, lịch sự', 350000, 1, CURRENT_TIMESTAMP, 'images/1.jpg'),
(2, 'Áo thun nam đen', 'Áo thun nam màu đen chất liệu cotton, thiết kế đơn giản, thoải mái', 250000, 1, CURRENT_TIMESTAMP, 'images/2.jpg'),
(3, 'Quần jean nam xanh', 'Quần jean nam màu xanh đậm, chất liệu denim co giãn, form slim fit', 450000, 2, CURRENT_TIMESTAMP, 'images/3.jpg'),
(4, 'Quần kaki nam nâu', 'Quần kaki nam màu nâu, chất liệu kaki cao cấp, form regular', 400000, 2, CURRENT_TIMESTAMP, 'images/4.jpg'),
(5, 'Áo sơ mi nữ trắng', 'Áo sơ mi nữ màu trắng chất liệu lụa, thiết kế thanh lịch', 320000, 3, CURRENT_TIMESTAMP, 'images/5.jpg'),
(6, 'Áo thun nữ hồng', 'Áo thun nữ màu hồng pastel, chất liệu cotton mềm mại', 220000, 3, CURRENT_TIMESTAMP, 'images/6.jpg'),
(7, 'Quần jean nữ xanh nhạt', 'Quần jean nữ màu xanh nhạt, chất liệu denim co giãn, form skinny', 420000, 4, CURRENT_TIMESTAMP, 'images/7.jpg'),
(8, 'Váy đầm suông đen', 'Váy đầm suông màu đen, chất liệu vải mềm, thiết kế đơn giản, thanh lịch', 550000, 5, CURRENT_TIMESTAMP, 'images/8.jpg'),
(9, 'Váy đầm xòe hoa', 'Váy đầm xòe họa tiết hoa, chất liệu vải mềm mại, phù hợp mùa hè', 650000, 5, CURRENT_TIMESTAMP, 'images/9.jpg'),
(10, 'Thắt lưng da nam', 'Thắt lưng da bò màu đen, khóa kim loại cao cấp', 300000, 6, CURRENT_TIMESTAMP, 'images/10.jpg'),
(11, 'Áo sơ mi nam kẻ sọc', 'Áo sơ mi nam kẻ sọc xanh trắng, chất liệu cotton thoáng mát', 380000, 1, CURRENT_TIMESTAMP, 'images/11.jpg'),
(12, 'Áo polo nam thể thao', 'Áo polo nam thể thao, chất liệu thun co giãn, thoáng khí', 280000, 1, CURRENT_TIMESTAMP, 'images/12.jpg'),
(13, 'Quần short nam kaki', 'Quần short nam kaki, phù hợp mùa hè, form regular', 320000, 2, CURRENT_TIMESTAMP, 'images/13.jpg'),
(14, 'Quần jogger nam', 'Quần jogger nam chất liệu nỉ, co giãn tốt, phù hợp thể thao', 350000, 2, CURRENT_TIMESTAMP, 'images/14.jpg'),
(15, 'Áo kiểu nữ công sở', 'Áo kiểu nữ công sở, thiết kế thanh lịch, chất liệu lụa cao cấp', 420000, 3, CURRENT_TIMESTAMP, 'images/15.jpg'),
(16, 'Áo khoác nữ nhẹ', 'Áo khoác nữ nhẹ chất liệu dù, chống nắng, chống gió nhẹ', 450000, 3, CURRENT_TIMESTAMP, 'images/16.jpg'),
(17, 'Quần culottes nữ', 'Quần culottes nữ ống rộng, chất liệu vải mềm, thoáng mát', 380000, 4, CURRENT_TIMESTAMP, 'images/17.jpg'),
(18, 'Quần legging nữ thể thao', 'Quần legging nữ thể thao, co giãn 4 chiều, thoát mồ hôi tốt', 250000, 4, CURRENT_TIMESTAMP, 'images/18.jpg'),
(19, 'Váy liền thân công sở', 'Váy liền thân công sở, thiết kế thanh lịch, kín đáo', 580000, 5, CURRENT_TIMESTAMP, 'images/19.jpg'),
(20, 'Đầm maxi đi biển', 'Đầm maxi đi biển, chất liệu voan nhẹ, họa tiết hoa', 620000, 5, CURRENT_TIMESTAMP, 'images/20.jpg'),
(21, 'Mũ bucket thời trang', 'Mũ bucket thời trang, chất liệu cotton, phù hợp đi chơi, dã ngoại', 180000, 6, CURRENT_TIMESTAMP, 'images/21.jpg'),
(22, 'Túi xách nữ công sở', 'Túi xách nữ công sở, chất liệu da PU cao cấp, nhiều ngăn tiện lợi', 480000, 6, CURRENT_TIMESTAMP, 'images/22.jpg');

-- 6. Product Variants
INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity) VALUES 
(1, 2, 1, 20), (1, 2, 2, 30), (1, 2, 3, 25), (1, 2, 4, 15),
(2, 1, 1, 25), (2, 1, 2, 35), (2, 1, 3, 30), (2, 1, 4, 20), (2, 8, 1, 15), (2, 8, 2, 25), (2, 8, 3, 20), (2, 8, 4, 10),
(3, 4, 6, 15), (3, 4, 7, 20), (3, 4, 8, 25), (3, 4, 9, 20), (3, 4, 10, 15), (3, 4, 11, 10),
(4, 9, 6, 10), (4, 9, 7, 15), (4, 9, 8, 20), (4, 9, 9, 15), (4, 9, 10, 10), (4, 9, 11, 5),
(5, 2, 1, 20), (5, 2, 2, 30), (5, 2, 3, 20),
(6, 7, 1, 25), (6, 7, 2, 35), (6, 7, 3, 25), (6, 2, 1, 20), (6, 2, 2, 30), (6, 2, 3, 20),
(7, 4, 6, 15), (7, 4, 7, 20), (7, 4, 8, 15), (7, 4, 9, 10),
(8, 1, 1, 15), (8, 1, 2, 25), (8, 1, 3, 15),
(9, 7, 1, 10), (9, 7, 2, 20), (9, 7, 3, 10),
(10, 1, 1, 30), (10, 9, 1, 25),
(11, 4, 1, 15), (11, 4, 2, 25), (11, 4, 3, 20), (11, 4, 4, 10),
(12, 1, 1, 20), (12, 1, 2, 30), (12, 1, 3, 25), (12, 4, 1, 15), (12, 4, 2, 25), (12, 4, 3, 20), (12, 3, 1, 10), (12, 3, 2, 15), (12, 3, 3, 10),
(13, 1, 8, 20), (13, 1, 9, 15), (13, 1, 10, 10), (13, 9, 8, 15), (13, 9, 9, 10), (13, 9, 10, 5), (13, 8, 8, 15), (13, 8, 9, 10), (13, 8, 10, 5),
(14, 1, 1, 25), (14, 1, 2, 35), (14, 1, 3, 30), (14, 8, 1, 20), (14, 8, 2, 30), (14, 8, 3, 25), (14, 5, 1, 15), (14, 5, 2, 25), (14, 5, 3, 20),
(15, 2, 1, 20), (15, 2, 2, 30), (15, 2, 3, 15), (15, 1, 1, 15), (15, 1, 2, 25), (15, 1, 3, 10), (15, 7, 1, 10), (15, 7, 2, 20), (15, 7, 3, 5),
(16, 1, 1, 15), (16, 1, 2, 25), (16, 1, 3, 10), (16, 4, 1, 10), (16, 4, 2, 20), (16, 4, 3, 5), (16, 7, 1, 10), (16, 7, 2, 15), (16, 7, 3, 5),
(17, 1, 1, 20), (17, 1, 2, 30), (17, 1, 3, 15), (17, 9, 1, 15), (17, 9, 2, 25), (17, 9, 3, 10), (17, 8, 1, 10), (17, 8, 2, 20), (17, 8, 3, 5),
(18, 1, 1, 25), (18, 1, 2, 35), (18, 1, 3, 20), (18, 8, 1, 15), (18, 8, 2, 25), (18, 8, 3, 10), (18, 4, 1, 10), (18, 4, 2, 20), (18, 4, 3, 5),
(19, 1, 1, 15), (19, 1, 2, 25), (19, 1, 3, 10), (19, 9, 1, 10), (19, 9, 2, 20), (19, 9, 3, 5), (19, 4, 1, 10), (19, 4, 2, 15), (19, 4, 3, 5),
(20, 4, 1, 15), (20, 4, 2, 25), (20, 4, 3, 10), (20, 7, 1, 20), (20, 7, 2, 30), (20, 7, 3, 15), (20, 6, 1, 10), (20, 6, 2, 20), (20, 6, 3, 5),
(21, 1, 1, 30), (21, 2, 1, 25), (21, 4, 1, 20), (21, 7, 1, 15),
(22, 1, 1, 20), (22, 9, 1, 15), (22, 3, 1, 10);

-- 7. Reviews (Remapped CustomerIDs to 1-10)
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate) VALUES 
(1, 1, 5, 'Sản phẩm rất tốt!', CURRENT_TIMESTAMP),
(2, 1, 4, 'Hài lòng!', CURRENT_TIMESTAMP),
(3, 2, 5, 'Rất đẹp!', CURRENT_TIMESTAMP),
(4, 3, 4, 'Chất lượng tốt!', CURRENT_TIMESTAMP),
(5, 5, 5, 'Thoáng mát!', CURRENT_TIMESTAMP),
(6, 1, 5, 'Tuyệt vời!', '2025-05-16 07:53:02'),
(3, 1, 1, 'Không hài lòng.', '2025-05-23 07:53:02'),
(9, 1, 4, 'Giao nhanh.', '2025-05-19 07:53:02'),
(1, 2, 4, 'Thích sản phẩm.', '2025-05-20 07:53:02'),
(2, 2, 3, 'Ổn.', '2025-05-12 07:53:02'),
(7, 2, 3, 'Bình thường.', '2025-05-22 07:53:02'),
(8, 3, 5, 'Hàng chuẩn.', '2025-05-17 07:53:02'),
(10, 3, 4, 'Good!', '2025-05-24 07:53:02'),
(1, 4, 4, 'Màu đẹp.', '2025-05-13 07:53:02'),
(7, 4, 3, 'Tạm được.', '2025-05-17 07:53:02'),
(1, 5, 2, 'Hơi mỏng.', '2025-05-16 07:53:02'),
(9, 5, 4, 'Mềm mại.', '2025-05-15 07:53:02'),
(7, 6, 4, 'Đẹp.', '2025-05-19 07:53:02'),
(5, 6, 4, 'Hài lòng.', '2025-05-14 07:53:02'),
(9, 8, 5, 'Chất lượng.', '2025-05-20 07:53:02'),
(10, 8, 3, 'Ok.', '2025-05-20 07:53:02'),
(3, 9, 3, 'Tạm.', '2025-05-24 07:53:02'),
(4, 7, 2, 'Hơi rộng.', '2025-05-12 07:53:02');

-- 8. Product Comments (Remapped CustomerIDs to 1-10)
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible) VALUES 
(1, 1, 'Sản phẩm rất đẹp!', CURRENT_TIMESTAMP, 'Cảm ơn bạn!', CURRENT_TIMESTAMP, TRUE),
(2, 1, 'Size vừa vặn.', CURRENT_TIMESTAMP, NULL, NULL, TRUE),
(3, 2, 'Màu sắc hơi khác.', CURRENT_TIMESTAMP, 'Xin lỗi vì sự khác biệt!', CURRENT_TIMESTAMP, TRUE),
(4, 3, 'Vải đẹp.', CURRENT_TIMESTAMP, NULL, NULL, TRUE);

-- 9. Wishlist, Messages
INSERT INTO Wishlist (CustomerID, ProductID, AddedDate) VALUES 
(1, 2, CURRENT_TIMESTAMP), (1, 5, CURRENT_TIMESTAMP);

INSERT INTO ContactMessages (Name, Email, Subject, Message, SubmitDate, Status) VALUES 
('Khách hàng mẫu', 'test@example.com', 'Hỗ trợ', 'Cần hỗ trợ tư vấn size.', CURRENT_TIMESTAMP, 'New');

-- Synchronize sequences
SELECT setval('categories_categoryid_seq', (SELECT MAX(categoryid) FROM categories));
SELECT setval('colors_colorid_seq', (SELECT MAX(colorid) FROM colors));
SELECT setval('sizes_sizeid_seq', (SELECT MAX(sizeid) FROM sizes));
SELECT setval('customers_customerid_seq', (SELECT MAX(customerid) FROM customers));
SELECT setval('products_productid_seq', (SELECT MAX(productid) FROM products));
SELECT setval('productvariants_variantid_seq', (SELECT MAX(variantid) FROM productvariants));
SELECT setval('orders_orderid_seq', COALESCE((SELECT MAX(orderid) FROM orders), 1));
SELECT setval('orderdetails_orderdetailid_seq', COALESCE((SELECT MAX(orderdetailid) FROM orderdetails), 1));
SELECT setval('reviews_reviewid_seq', (SELECT MAX(reviewid) FROM reviews));
SELECT setval('productcomments_commentid_seq', (SELECT MAX(commentid) FROM productcomments));
