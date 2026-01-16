-- AUTOMATICALLY GENERATED FROM SQL SERVER DATA MIGRATION
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
(1, 'Nguyễn Văn An', 'an.nguyen@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0901234567', '123 Đường Lê Lợi, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(2, 'Trần Thị Bình', 'binh.tran@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0912345678', '456 Đường Nguyễn Huệ, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(3, 'Lê Văn Cường', 'cuong.le@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0923456789', '789 Đường Cách Mạng Tháng 8, Quận 3, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(4, 'Phạm Thị Dung', 'dung.pham@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0934567890', '101 Đường Võ Văn Tần, Quận 3, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(5, 'Hoàng Văn Em', 'em.hoang@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0945678901', '202 Đường Nguyễn Thị Minh Khai, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(6, 'Nguyễn Thị Hương', 'huong.nguyen@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0987654321', '25 Đường Lý Tự Trọng, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(7, 'Trần Văn Minh', 'minh.tran@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0976543210', '42 Đường Nguyễn Đình Chiểu, Quận 3, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(8, 'Lê Thị Lan', 'lan.le@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0965432109', '78 Đường Trần Hưng Đạo, Quận 5, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(9, 'Phạm Văn Đức', 'duc.pham@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0954321098', '15 Đường Lê Duẩn, Quận 1, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(10, 'Vũ Thị Mai', 'mai.vu@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0943210987', '63 Đường Nguyễn Trãi, Quận 5, TP.HCM', FALSE, CURRENT_TIMESTAMP),
(11, 'Admin', 'admin123@gmail.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0000000000', 'Quản trị viên', TRUE, CURRENT_TIMESTAMP),
(12, 'Customer 12', 'customer12@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000012', 'Address 12', FALSE, CURRENT_TIMESTAMP),
(13, 'Customer 13', 'customer13@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000013', 'Address 13', FALSE, CURRENT_TIMESTAMP),
(14, 'Customer 14', 'customer14@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000014', 'Address 14', FALSE, CURRENT_TIMESTAMP),
(15, 'Customer 15', 'customer15@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000015', 'Address 15', FALSE, CURRENT_TIMESTAMP),
(16, 'Customer 16', 'customer16@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000016', 'Address 16', FALSE, CURRENT_TIMESTAMP),
(17, 'Customer 17', 'customer17@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000017', 'Address 17', FALSE, CURRENT_TIMESTAMP),
(18, 'Customer 18', 'customer18@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000018', 'Address 18', FALSE, CURRENT_TIMESTAMP),
(19, 'Customer 19', 'customer19@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000019', 'Address 19', FALSE, CURRENT_TIMESTAMP),
(20, 'Customer 20', 'customer20@example.com', 'pbkdf2:sha256:600000$Kd3120b68bed6615c89a50d41e6caa0a', '0900000020', 'Address 20', FALSE, CURRENT_TIMESTAMP);

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


-- Reviews from SQL Server
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES 
    (1, 1, 5, 'Sản phẩm rất tốt, chất lượng cao, đúng như mô tả.', CURRENT_TIMESTAMP - INTERVAL '5 days'),
    (2, 1, 4, 'Tôi rất hài lòng với sản phẩm này, giao hàng nhanh.', CURRENT_TIMESTAMP - INTERVAL '3 days'),
    (3, 2, 5, 'Áo rất đẹp, form chuẩn, mặc rất thoải mái.', CURRENT_TIMESTAMP - INTERVAL '7 days'),
    (4, 3, 4, 'Quần jean chất lượng tốt, đường may đẹp.', CURRENT_TIMESTAMP - INTERVAL '10 days'),
    (5, 5, 5, 'Áo sơ mi trắng rất đẹp, vải mềm và thoáng mát.', CURRENT_TIMESTAMP - INTERVAL '2 days') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 1, 5, 'Sản phẩm tuyệt vời!', '2025-05-16 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (13, 1, 1, 'Không hài lòng, sản phẩm lỗi.', '2025-05-23 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 1, 4, 'Hàng tốt, giao nhanh.', '2025-05-19 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (1, 2, 4, 'Mình thích sản phẩm này.', '2025-05-20 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (2, 2, 1, 'Khác xa ảnh, thất vọng.', '2025-05-12 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 2, 3, 'Cũng được nhưng không ấn tượng.', '2025-05-22 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 3, 1, 'Không hài lòng, sản phẩm lỗi.', '2025-05-17 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 3, 4, 'Mình thích sản phẩm này.', '2025-05-24 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (6, 3, 2, 'Chất lượng chưa như mong đợi.', '2025-05-16 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (2, 4, 2, 'Màu hơi khác hình.', '2025-05-13 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 4, 3, 'Hàng ổn so với giá.', '2025-05-17 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 4, 1, 'Giao sai màu, chất vải xấu.', '2025-05-16 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 5, 4, 'Tạm ổn, giống mô tả.', '2025-05-15 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 5, 2, 'Màu hơi khác hình.', '2025-05-19 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (5, 5, 4, 'Hàng tốt, giao nhanh.', '2025-05-14 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 6, 5, 'Chất lượng vượt mong đợi.', '2025-05-20 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 6, 3, 'Bình thường, không quá đặc biệt.', '2025-05-20 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (13, 6, 3, 'Bình thường, không quá đặc biệt.', '2025-05-24 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (14, 7, 1, 'Khác xa ảnh, thất vọng.', '2025-05-12 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (1, 7, 5, 'Sản phẩm tuyệt vời!', '2025-05-15 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 7, 2, 'Chất lượng chưa như mong đợi.', '2025-05-22 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 8, 4, 'Tạm ổn, giống mô tả.', '2025-05-22 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 8, 3, 'Hàng ổn so với giá.', '2025-05-17 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 8, 5, 'Sản phẩm tuyệt vời!', '2025-05-13 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 9, 2, 'Form hơi lệch, cần cải thiện.', '2025-05-14 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 9, 5, 'Rất hài lòng, sẽ mua lại.', '2025-05-12 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (11, 9, 1, 'Khác xa ảnh, thất vọng.', '2025-05-22 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 10, 1, 'Giao sai màu, chất vải xấu.', '2025-05-24 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 10, 2, 'Màu hơi khác hình.', '2025-05-19 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 10, 4, 'Tạm ổn, giống mô tả.', '2025-05-24 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 11, 2, 'Màu hơi khác hình.', '2025-05-11 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 11, 1, 'Giao sai màu, chất vải xấu.', '2025-05-14 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 11, 3, 'Hàng ổn so với giá.', '2025-05-22 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 12, 2, 'Màu hơi khác hình.', '2025-05-24 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 12, 3, 'Bình thường, không quá đặc biệt.', '2025-05-18 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 12, 1, 'Khác xa ảnh, thất vọng.', '2025-05-22 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (4, 13, 3, 'Cũng được nhưng không ấn tượng.', '2025-05-13 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 13, 5, 'Sản phẩm tuyệt vời!', '2025-05-21 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 13, 1, 'Giao sai màu, chất vải xấu.', '2025-05-16 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (6, 14, 4, 'Tạm ổn, giống mô tả.', '2025-05-18 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 14, 1, 'Khác xa ảnh, thất vọng.', '2025-05-20 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 14, 5, 'Sản phẩm tuyệt vời!', '2025-05-14 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 15, 2, 'Chất lượng chưa như mong đợi.', '2025-05-13 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 15, 5, 'Sản phẩm tuyệt vời!', '2025-05-18 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (13, 15, 4, 'Tạm ổn, giống mô tả.', '2025-05-24 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 16, 5, 'Sản phẩm tuyệt vời!', '2025-05-11 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (18, 16, 4, 'Mình thích sản phẩm này.', '2025-05-14 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (7, 16, 3, 'Cũng được nhưng không ấn tượng.', '2025-05-19 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (9, 17, 2, 'Màu hơi khác hình.', '2025-05-24 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 17, 3, 'Bình thường, không quá đặc biệt.', '2025-05-17 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 17, 3, 'Bình thường, không quá đặc biệt.', '2025-05-21 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (12, 18, 4, 'Hàng tốt, giao nhanh.', '2025-05-18 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (3, 18, 1, 'Không hài lòng, sản phẩm lỗi.', '2025-05-15 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 18, 3, 'Cũng được nhưng không ấn tượng.', '2025-05-15 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (3, 19, 4, 'Hàng tốt, giao nhanh.', '2025-05-20 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (1, 19, 5, 'Sản phẩm tuyệt vời!', '2025-05-13 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 19, 5, 'Chất lượng vượt mong đợi.', '2025-05-22 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 20, 2, 'Form hơi lệch, cần cải thiện.', '2025-05-16 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 20, 3, 'Cũng được nhưng không ấn tượng.', '2025-05-20 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (20, 20, 4, 'Tạm ổn, giống mô tả.', '2025-05-16 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (5, 21, 5, 'Chất lượng vượt mong đợi.', '2025-05-17 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (17, 21, 4, 'Mình thích sản phẩm này.', '2025-05-17 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (8, 21, 3, 'Cũng được nhưng không ấn tượng.', '2025-05-12 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (10, 22, 1, 'Không hài lòng, sản phẩm lỗi.', '2025-05-15 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (19, 22, 4, 'Mình thích sản phẩm này.', '2025-05-11 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
VALUES (16, 22, 1, 'Khác xa ảnh, thất vọng.', '2025-05-21 07:53:02') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
-- Wishlist from SQL Server
INSERT INTO Wishlist (CustomerID, ProductID, AddedDate)
VALUES 
    (1, 2, CURRENT_TIMESTAMP - INTERVAL '3 days'),
    (1, 5, CURRENT_TIMESTAMP - INTERVAL '2 days'),
    (2, 3, CURRENT_TIMESTAMP - INTERVAL '5 days'),
    (3, 1, CURRENT_TIMESTAMP - INTERVAL '1 days'),
    (4, 9, CURRENT_TIMESTAMP - INTERVAL '4 days') ON CONFLICT (CustomerID, ProductID) DO NOTHING;
-- ContactMessages from SQL Server
INSERT INTO ContactMessages (Name, Email, Subject, Message, SubmitDate, Status)
VALUES 
    ('Nguyễn Văn A', 'nguyenvana@example.com', 'Hỏi về chính sách đổi trả', 'Tôi muốn biết thêm về chính sách đổi trả của cửa hàng. Cảm ơn!', CURRENT_TIMESTAMP - INTERVAL '7 days', 'Answered'),
    ('Trần Thị B', 'tranthib@example.com', 'Vấn đề về đơn hàng', 'Đơn hàng của tôi bị chậm giao, mã đơn hàng là #123. Mong được hỗ trợ.', CURRENT_TIMESTAMP - INTERVAL '3 days', 'Processing'),
    ('Lê Văn C', 'levanc@example.com', 'Hợp tác kinh doanh', 'Tôi muốn hợp tác kinh doanh với cửa hàng của bạn. Vui lòng liên hệ lại với tôi.', CURRENT_TIMESTAMP - INTERVAL '1 days', 'New');
-- NewsletterSubscribers from SQL Server
INSERT INTO NewsletterSubscribers (Email, SubscribeDate, IsActive)
VALUES 
    ('subscriber1@example.com', CURRENT_TIMESTAMP - INTERVAL '30 days', TRUE),
    ('subscriber2@example.com', CURRENT_TIMESTAMP - INTERVAL '25 days', TRUE),
    ('subscriber3@example.com', CURRENT_TIMESTAMP - INTERVAL '20 days', TRUE),
    ('subscriber4@example.com', CURRENT_TIMESTAMP - INTERVAL '15 days', TRUE),
    ('subscriber5@example.com', CURRENT_TIMESTAMP - INTERVAL '10 days', TRUE) ON CONFLICT (Email) DO NOTHING;
-- ProductComments from SQL Server
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES 
    (1, 1, 'Sản phẩm rất đẹp, đúng như mô tả. Tôi rất hài lòng với chất lượng vải.', CURRENT_TIMESTAMP - INTERVAL '7 days', 
     'Cảm ơn bạn đã mua hàng và đánh giá sản phẩm. Chúng tôi rất vui khi bạn hài lòng!', CURRENT_TIMESTAMP - INTERVAL '6 days', TRUE),
    
    (2, 1, 'Tôi đã mua áo này cho chồng tôi, anh ấy rất thích. Size vừa vặn, màu sắc đẹp.', CURRENT_TIMESTAMP - INTERVAL '5 days', 
     NULL, NULL, TRUE),
    
    (3, 2, 'Áo thun chất lượng tốt, nhưng tôi nghĩ màu hơi khác so với hình ảnh trên website.', CURRENT_TIMESTAMP - INTERVAL '4 days', 
     'Xin lỗi vì sự khác biệt về màu sắc. Đôi khi màu sắc có thể hiển thị khác nhau tùy thuộc vào màn hình. Nếu bạn không hài lòng, bạn có thể đổi trả trong vòng 30 ngày.', CURRENT_TIMESTAMP - INTERVAL '3 days', TRUE),
    
    (4, 3, 'Quần jean rất thoải mái, form dáng đẹp. Tôi sẽ mua thêm màu khác.', CURRENT_TIMESTAMP - INTERVAL '3 days', 
     NULL, NULL, TRUE),
    
    (5, 5, 'Áo sơ mi trắng rất đẹp, nhưng hơi nhỏ so với size thông thường. Nên đặt size lớn hơn 1.', CURRENT_TIMESTAMP - INTERVAL '2 days', 
     'Cảm ơn bạn đã chia sẻ kinh nghiệm. Chúng tôi sẽ cập nhật thông tin về kích thước trong mô tả sản phẩm.', CURRENT_TIMESTAMP - INTERVAL '1 days', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 1, 'Giao hàng hơi chậm một chút.', '2025-05-21 07:26:10', 'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 1, 'Không quá đặc biệt nhưng dùng được.', '2025-05-21 07:26:10', 'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-22 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 1, 'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-16 07:26:10', 'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-17 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 2, 'Mua lần 2 rồi, vẫn rất thích.', '2025-05-17 07:26:10', 'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-18 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 2, 'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-17 07:26:10', 'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-18 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 2, 'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-16 07:26:10', 'Nếu bạn cần hỗ trợ thêm, hãy liên hệ hotline hoặc fanpage.', '2025-05-18 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (10, 3, 'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-18 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (11, 3, 'Size không chuẩn, mặc hơi chật.', '2025-05-18 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (12, 3, 'Mua lần 2 rồi, vẫn rất thích.', '2025-05-18 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (13, 4, 'Đường may chưa được đẹp.', '2025-05-22 07:26:10', 'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-24 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (14, 4, 'Không giống hình, thất vọng nhẹ.', '2025-05-18 07:26:10', 'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (15, 4, 'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', 'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (16, 5, 'Vải hơi thô, không như mong đợi.', '2025-05-18 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (17, 5, 'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (18, 5, 'Size không chuẩn, mặc hơi chật.', '2025-05-22 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (19, 6, 'Mua lần 2 rồi, vẫn rất thích.', '2025-05-17 07:26:10', 'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (20, 6, 'Vải hơi thô, không như mong đợi.', '2025-05-15 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (1, 6, 'Form chuẩn, mặc rất vừa.', '2025-05-18 07:26:10', 'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (2, 7, 'Không quá đặc biệt nhưng dùng được.', '2025-05-21 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-22 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (3, 7, 'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-15 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 7, 'Vải hơi thô, không như mong đợi.', '2025-05-15 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-16 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 8, 'Màu bị phai sau khi giặt lần đầu.', '2025-05-16 07:26:10', 'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-17 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 8, 'Mua lần 2 rồi, vẫn rất thích.', '2025-05-20 07:26:10', 'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-22 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 8, 'Giao hàng hơi chậm một chút.', '2025-05-22 07:26:10', 'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 9, 'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', 'Nếu bạn cần hỗ trợ thêm, hãy liên hệ hotline hoặc fanpage.', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 9, 'Màu bị phai sau khi giặt lần đầu.', '2025-05-19 07:26:10', 'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-20 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (10, 9, 'Cũng được, không có gì nổi bật.', '2025-05-20 07:26:10', 'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-22 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (11, 10, 'Sản phẩm rất đẹp và chất lượng.', '2025-05-15 07:26:10', 'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-16 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (12, 10, 'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-22 07:26:10', 'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (13, 10, 'Form chuẩn, mặc rất vừa.', '2025-05-17 07:26:10', 'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-18 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (14, 11, 'Không quá đặc biệt nhưng dùng được.', '2025-05-17 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (15, 11, 'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-19 07:26:10', 'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-21 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (16, 11, 'Không quá đặc biệt nhưng dùng được.', '2025-05-17 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-18 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (17, 12, 'Màu bị phai sau khi giặt lần đầu.', '2025-05-15 07:26:10', 'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-17 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (18, 12, 'Mua lần 2 rồi, vẫn rất thích.', '2025-05-21 07:26:10', 'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (19, 12, 'Size không chuẩn, mặc hơi chật.', '2025-05-19 07:26:10', 'Phản hồi của bạn là động lực để chúng tôi phát triển sản phẩm tốt hơn.', '2025-05-20 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (20, 13, 'Size không chuẩn, mặc hơi chật.', '2025-05-15 07:26:10', 'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-17 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (1, 13, 'Đường may chưa được đẹp.', '2025-05-19 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (2, 13, 'Màu bị phai sau khi giặt lần đầu.', '2025-05-19 07:26:10', 'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-21 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (3, 14, 'Giao hàng hơi chậm một chút.', '2025-05-20 07:26:10', 'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-22 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 14, 'Đường may chưa được đẹp.', '2025-05-18 07:26:10', 'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-20 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 14, 'Mua lần 2 rồi, vẫn rất thích.', '2025-05-20 07:26:10', 'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-21 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 15, 'Size không chuẩn, mặc hơi chật.', '2025-05-15 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-16 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 15, 'Size không chuẩn, mặc hơi chật.', '2025-05-22 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 15, 'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-18 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 16, 'Sản phẩm tạm ổn, đúng như mô tả.', '2025-05-17 07:26:10', 'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-18 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (10, 16, 'Màu bị phai sau khi giặt lần đầu.', '2025-05-15 07:26:10', 'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-17 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (11, 16, 'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-18 07:26:10', 'Rất tiếc vì trải nghiệm chưa tốt, bạn có thể liên hệ CSKH để được hỗ trợ đổi trả.', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (12, 17, 'Sản phẩm rất đẹp và chất lượng.', '2025-05-19 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (13, 17, 'Form chuẩn, mặc rất vừa.', '2025-05-19 07:26:10', 'Nếu bạn cần hỗ trợ thêm, hãy liên hệ hotline hoặc fanpage.', '2025-05-21 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (14, 17, 'Giao hàng hơi chậm một chút.', '2025-05-20 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (15, 18, 'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-18 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (16, 18, 'Cũng được, không có gì nổi bật.', '2025-05-18 07:26:10', 'Cảm ơn bạn đã góp ý. Chúng tôi sẽ lưu ý để điều chỉnh sản phẩm.', '2025-05-20 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (17, 18, 'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-20 07:26:10', NULL, NULL, TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (18, 19, 'Cũng được, không có gì nổi bật.', '2025-05-20 07:26:10', 'Bạn vui lòng để lại mã đơn hàng để chúng tôi hỗ trợ tốt hơn nhé.', '2025-05-21 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (19, 19, 'Màu bị phai sau khi giặt lần đầu.', '2025-05-18 07:26:10', 'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-19 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (20, 19, 'Giao hàng hơi chậm một chút.', '2025-05-21 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (1, 20, 'Size không chuẩn, mặc hơi chật.', '2025-05-22 07:26:10', 'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (2, 20, 'Sản phẩm rất đẹp và chất lượng.', '2025-05-22 07:26:10', 'Cảm ơn bạn đã tin tưởng và ủng hộ cửa hàng!', '2025-05-24 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (3, 20, 'Tư vấn nhiệt tình, sẽ ủng hộ tiếp.', '2025-05-22 07:26:10', 'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-24 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (4, 21, 'Không giống hình, thất vọng nhẹ.', '2025-05-20 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-22 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (5, 21, 'Mình rất hài lòng, giao hàng nhanh.', '2025-05-21 07:26:10', 'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (6, 21, 'Mua lần 2 rồi, vẫn rất thích.', '2025-05-21 07:26:10', 'Chúng tôi xin lỗi vì sự bất tiện và sẽ cải thiện dịch vụ.', '2025-05-23 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (7, 22, 'Sản phẩm rất đẹp và chất lượng.', '2025-05-17 07:26:10', 'Rất vui khi bạn hài lòng. Mong bạn tiếp tục ủng hộ!', '2025-05-18 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (8, 22, 'Màu không giống ảnh lắm nhưng vẫn ổn.', '2025-05-20 07:26:10', 'Cảm ơn bạn đã phản hồi! Chúng tôi sẽ cố gắng cải thiện hơn nữa.', '2025-05-21 07:26:10', TRUE);
INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible)
VALUES (9, 22, 'Size không chuẩn, mặc hơi chật.', '2025-05-20 07:26:10', 'Cảm ơn bạn. Hy vọng sẽ phục vụ bạn ở những lần mua tiếp theo!', '2025-05-21 07:26:10', TRUE);

-- Generate Random Orders for Reports
DO $$
DECLARE
    v_CustomerId INT;
    v_OrderId INT;
    v_ProductId INT;
    v_VariantId INT;
    v_Price DECIMAL(18,2);
    v_Date TIMESTAMP;
    i INT;
    j INT;
BEGIN
    -- Generate 50 orders over the last 2 years
    FOR i IN 1..50 LOOP
        -- Random Customer 1-20
        v_CustomerId := floor(random() * 20 + 1)::int;
        -- Random Date
        v_Date := CURRENT_TIMESTAMP - (random() * 700 || ' days')::interval;
        
        INSERT INTO Orders (CustomerID, OrderDate, TotalAmount, Status, PaymentMethod, ShippingAddress)
        VALUES (v_CustomerId, v_Date, 0, 'Delivered', 'COD', 'Address')
        RETURNING OrderID INTO v_OrderId;
        
        -- Add 1-3 items
        FOR j IN 1..floor(random() * 3 + 1)::int LOOP
            -- Random Product 1-22
            v_ProductId := floor(random() * 22 + 1)::int;
            
            -- Get a Variant for this product
            SELECT VariantID INTO v_VariantId FROM ProductVariants WHERE ProductID = v_ProductId LIMIT 1;
            
            IF v_VariantId IS NOT NULL THEN
                SELECT Price INTO v_Price FROM Products WHERE ProductID = v_ProductId;
                
                INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
                VALUES (v_OrderId, v_VariantId, floor(random() * 2 + 1)::int, v_Price);
            END IF;
        END LOOP;
        
        -- Update Total
        UPDATE Orders SET TotalAmount = (SELECT SUM(Quantity * Price) FROM OrderDetails WHERE OrderID = v_OrderId) WHERE OrderID = v_OrderId;
    END LOOP;
END $$;


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
