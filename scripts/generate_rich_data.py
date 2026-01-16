import os
import random
import decimal
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

# Config
BASE_DIR = r"d:\SQL\dbmstestfileshit\thua 2.0"
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "postgresql_data_full.sql")

# Password for all sample users: '123456'
PASSWORD_HASH = 'pbkdf2:sha256:600000$XDV5QUQ3okhGw4Yr$89c269aa7832d6cb668604d0dec99cb4280306451ce2a418478bb7b6375e8ce3'

CATEGORIES = [
    (1, 'Áo nam', 'Các loại áo dành cho nam giới'),
    (2, 'Quần nam', 'Các loại quần dành cho nam giới'),
    (3, 'Áo nữ', 'Các loại áo dành cho nữ giới'),
    (4, 'Quần nữ', 'Các loại quần dành cho nữ giới'),
    (5, 'Váy đầm', 'Các loại váy và đầm dành cho nữ giới'),
    (6, 'Phụ kiện', 'Các loại phụ kiện thời trang')
]

COLORS = ['Đen', 'Trắng', 'Đỏ', 'Xanh dương', 'Xanh lá', 'Vàng', 'Hồng', 'Xám', 'Nâu', 'Tím', 'Cam', 'Kem']
SIZES_CLOTHES = ['S', 'M', 'L', 'XL', 'XXL']
SIZES_PANTS = ['28', '29', '30', '31', '32', '33', '34']

# Original Data from SQL Server
ORIGINAL_CUSTOMERS = [
    (1, 'Nguyễn Văn An', 'an.nguyen@example.com', '0901234567', '123 Đường Lê Lợi, Quận 1, TP.HCM'),
    (2, 'Trần Thị Bình', 'binh.tran@example.com', '0912345678', '456 Đường Nguyễn Huệ, Quận 1, TP.HCM'),
    (3, 'Lê Văn Cường', 'cuong.le@example.com', '0923456789', '789 Đường Cách Mạng Tháng 8, Quận 3, TP.HCM'),
    (4, 'Phạm Thị Dung', 'dung.pham@example.com', '0934567890', '101 Đường Võ Văn Tần, Quận 3, TP.HCM'),
    (5, 'Hoàng Văn Em', 'em.hoang@example.com', '0945678901', '202 Đường Nguyễn Thị Minh Khai, Quận 1, TP.HCM'),
    (6, 'Nguyễn Thị Hương', 'huong.nguyen@example.com', '0987654321', '25 Đường Lý Tự Trọng, Quận 1, TP.HCM'),
    (7, 'Trần Văn Minh', 'minh.tran@example.com', '0976543210', '42 Đường Nguyễn Đình Chiểu, Quận 3, TP.HCM'),
    (8, 'Lê Thị Lan', 'lan.le@example.com', '0965432109', '78 Đường Trần Hưng Đạo, Quận 5, TP.HCM'),
    (9, 'Phạm Văn Đức', 'duc.pham@example.com', '0954321098', '15 Đường Lê Duẩn, Quận 1, TP.HCM'),
    (10, 'Vũ Thị Mai', 'mai.vu@example.com', '0943210987', '63 Đường Nguyễn Trãi, Quận 5, TP.HCM'),
    (11, 'Admin', 'admin123@gmail.com', '0000000000', 'Quản trị viên')
]

ORIGINAL_PRODUCTS = [
    (1, 'Áo sơ mi nam trắng', 'Áo sơ mi nam màu trắng chất liệu cotton cao cấp, thiết kế đơn giản, lịch sự', 350000, 1),
    (2, 'Áo thun nam đen', 'Áo thun nam màu đen chất liệu cotton, thiết kế đơn giản, thoải mái', 250000, 1),
    (3, 'Quần jean nam xanh', 'Quần jean nam màu xanh đậm, chất liệu denim co giãn, form slim fit', 450000, 2),
    (4, 'Quần kaki nam nâu', 'Quần kaki nam màu nâu, chất liệu kaki cao cấp, form regular', 400000, 2),
    (5, 'Áo sơ mi nữ trắng', 'Áo sơ mi nữ màu trắng chất liệu lụa, thiết kế thanh lịch', 320000, 3),
    (6, 'Áo thun nữ hồng', 'Áo thun nữ màu hồng pastel, chất liệu cotton mềm mại', 220000, 3),
    (7, 'Quần jean nữ xanh nhạt', 'Quần jean nữ màu xanh nhạt, chất liệu denim co giãn, form skinny', 420000, 4),
    (8, 'Váy đầm suông đen', 'Váy đầm suông màu đen, chất liệu vải mềm, thiết kế đơn giản, thanh lịch', 550000, 5),
    (9, 'Váy đầm xòe hoa', 'Váy đầm xòe họa tiết hoa, chất liệu vải mềm mại, phù hợp mùa hè', 650000, 5),
    (10, 'Thắt lưng da nam', 'Thắt lưng da bò màu đen, khóa kim loại cao cấp', 300000, 6),
    (11, 'Áo sơ mi nam kẻ sọc', 'Áo sơ mi nam kẻ sọc xanh trắng, chất liệu cotton thoáng mát', 380000, 1),
    (12, 'Áo polo nam thể thao', 'Áo polo nam thể thao, chất liệu thun co giãn, thoáng khí', 280000, 1),
    (13, 'Quần short nam kaki', 'Quần short nam kaki, phù hợp mùa hè, form regular', 320000, 2),
    (14, 'Quần jogger nam', 'Quần jogger nam chất liệu nỉ, co giãn tốt, phù hợp thể thao', 350000, 2),
    (15, 'Áo kiểu nữ công sở', 'Áo kiểu nữ công sở, thiết kế thanh lịch, chất liệu lụa cao cấp', 420000, 3),
    (16, 'Áo khoác nữ nhẹ', 'Áo khoác nữ nhẹ chất liệu dù, chống nắng, chống gió nhẹ', 450000, 3),
    (17, 'Quần culottes nữ', 'Quần culottes nữ ống rộng, chất liệu vải mềm, thoáng mát', 380000, 4),
    (18, 'Quần legging nữ thể thao', 'Quần legging nữ thể thao, co giãn 4 chiều, thoát mồ hôi tốt', 250000, 4),
    (19, 'Váy liền thân công sở', 'Váy liền thân công sở, thiết kế thanh lịch, kín đáo', 580000, 5),
    (20, 'Đầm maxi đi biển', 'Đầm maxi đi biển, chất liệu voan nhẹ, họa tiết hoa', 620000, 5),
    (21, 'Mũ bucket thời trang', 'Mũ bucket thời trang, chất liệu cotton, phù hợp đi chơi, dã ngoại', 180000, 6),
    (22, 'Túi xách nữ công sở', 'Túi xách nữ công sở, chất liệu da PU cao cấp, nhiều ngăn tiện lợi', 480000, 6)
]

# Additional Data templates (starting from ID 23)
PRODUCT_TEMPLATES = [
    (1, 'Áo khoác nam da lộn', 'Chất liệu da lộn mềm mại, lót lông ấm áp', 850000),
    (2, 'Quần Jeans nam xám khói', 'Màu xám khói hiện đại, wash nhẹ cá tính', 490000),
    (3, 'Áo len nữ cổ lọ', 'Len dệt sợi to, phong cách vintage', 390000),
    (4, 'Quần Jogger nữ thun', 'Dáng basic, cạp chun thoải mái', 250000),
    (5, 'Chân váy dập ly', 'Vải voan 2 lớp, độ xòe rộng', 320000),
    (6, 'Kính mắt thời trang', 'Chống tia UV400, gọng nhựa bền bỉ', 150000),
    (1, 'Áo Hoodie nam nỉ', 'Nỉ bông dày dặn, in hình trẻ trung', 330000),
    (2, 'Quần Kaki nam xanh rêu', 'Chất vải bền màu, form đứng dáng', 380000),
    (3, 'Áo Croptop nữ cá tính', 'Áo ôm dáng, cổ tim gợi cảm', 180000),
    (4, 'Quần Short nữ lửng', 'Phong cách street style, vải thô', 220000),
    (5, 'Đầm suông cổ yếm', 'Váy lụa hở lưng đi tiệc', 590000),
    (6, 'Ví da nữ mini', 'Da bò thật, thiết kế nhỏ gọn', 420000),
    (1, 'Áo Vest nam lịch lãm', 'Form chuẩn doanh nhân, màu đen sọc', 1200000),
    (3, 'Áo dạ nữ dáng dài', 'Màu be trung tính, sang trọng', 950000),
    (5, 'Chân váy chữ A', 'Vải tuyết mưa, công sở trẻ trung', 280000),
    (6, 'Dây chuyền bạc Ý', 'Mặt đá lấp lánh, quà tặng ý nghĩa', 450000),
    (1, 'Áo Gió nam 2 lớp', 'Chống thấm nước, có mũ tháo rời', 450000),
    (2, 'Quần Tây nam cao cấp', 'Chất liệu vải không nhăn, độ bền cao', 550000)
]

REVIEWS_TEMPLATES = [
    (5, "Sản phẩm cực kỳ chất lượng, đáng đồng tiền bát gạo."),
    (5, "Giao hàng rất nhanh, đóng gói đẹp. Sẽ quay lại ủng hộ."),
    (5, "Tuyệt vời! Vải mặc rất thích, đúng kích cỡ."),
    (4, "Hàng ổn, form đẹp. Tuy nhiên màu hơi khác ảnh một tẹo."),
    (4, "Giao hàng hơi chậm nhưng bù lại chất lượng quá ok."),
    (3, "Bình thường, không quá đặc biệt so với giá."),
    (2, "Hơi thất vọng, chỉ may còn thừa nhiều quá."),
    (1, "Sản phẩm tệ, không giống mô tả. Không nên mua.")
]

COMMENTS_TEMPLATES = [
    "Sản phẩm này còn size L không shop?",
    "Minh cao 1m7 nặng 70kg mặc size nào vừa?",
    "Có màu xanh dương không ạ?",
    "Ship về Đà Nẵng mất bao lâu vậy shop?",
    "Cho mình xin ảnh thật sản phẩm với.",
    "Bên mình có được kiểm tra hàng trước khi thanh toán không?",
    "Shop ơi, bao lâu thì có hàng lại ạ?",
    "Mẫu này đẹp quá, chốt đơn!"
]

# Realistic Data Generators
VIET_LAST_NAMES = ['Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Phan', 'Vũ', 'Đặng', 'Bùi', 'Đỗ', 'Hồ', 'Ngô', 'Võ', 'Lý', 'Dương']
VIET_MIDDLE_NAMES_MALE = ['Văn', 'Hữu', 'Đức', 'Thành', 'Minh', 'Quang', 'Anh', 'Tất', 'Công', 'Trọng', 'Thế', 'Bảo']
VIET_FIRST_NAMES_MALE = ['An', 'Bình', 'Cường', 'Dũng', 'Em', 'Hùng', 'Kiên', 'Long', 'Minh', 'Nam', 'Phúc', 'Quân', 'Sơn', 'Tùng', 'Việt', 'Khải', 'Thịnh', 'Duy']
VIET_MIDDLE_NAMES_FEMALE = ['Thị', 'Ngọc', 'Huyền', 'Quỳnh', 'Thu', 'Thanh', 'Diệu', 'Phương', 'Mai', 'Ánh', 'Bảo', 'Minh']
VIET_FIRST_NAMES_FEMALE = ['An', 'Bình', 'Chi', 'Dung', 'Hoa', 'Hương', 'Lan', 'Mai', 'Ngọc', 'Phương', 'Quỳnh', 'Thảo', 'Trang', 'Vy', 'Linh', 'Hà', 'Nhi']

EMAIL_DOMAINS = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'fpt.edu.vn', 'vnu.edu.vn']

CITY_DISTRICTS = {
    'TP. Hồ Chí Minh': ['Quận 1', 'Quận 3', 'Quận 5', 'Quận 7', 'Quận 10', 'Quận Bình Thạnh', 'Quận Gò Vấp', 'Quận Tân Bình', 'Q.Thủ Đức'],
    'Hà Nội': ['Quận Hoàn Kiếm', 'Quận Ba Đình', 'Quận Đống Đa', 'Quận Hai Bà Trưng', 'Quận Cầu Giấy', 'Quận Tây Hồ', 'Quận Hà Đông'],
    'Đà Nẵng': ['Quận Hải Châu', 'Quận Thanh Khê', 'Quận Sơn Trà', 'Quận Ngũ Hành Sơn', 'Quận Liên Chiểu'],
    'Cần Thơ': ['Quận Ninh Kiều', 'Quận Bình Thủy', 'Quận Cái Răng', 'Quận Ô Môn'],
    'Hải Phòng': ['Quận Hồng Bàng', 'Quận Ngô Quyền', 'Quận Lê Chân', 'Quận Hải An']
}

STREETS = [
    'Lê Lợi', 'Nguyễn Huệ', 'Trần Hưng Đạo', 'Lý Tự Trọng', 'Hai Bà Trưng', 'Điện Biên Phủ', 
    'Cách Mạng Tháng 8', 'Nguyễn Thị Minh Khai', 'Lê Duẩn', 'Đồng Khởi', 'Phan Chu Trinh', 
    'Lý Thường Kiệt', 'Bạch Đằng', 'Trần Phú', 'Hùng Vương'
]

def generate_viet_name():
    is_male = random.choice([True, False])
    last = random.choice(VIET_LAST_NAMES)
    if is_male:
        mid = random.choice(VIET_MIDDLE_NAMES_MALE)
        first = random.choice(VIET_FIRST_NAMES_MALE)
    else:
        mid = random.choice(VIET_MIDDLE_NAMES_FEMALE)
        first = random.choice(VIET_FIRST_NAMES_FEMALE)
    return f"{last} {mid} {first}"

def generate_random_address():
    city = random.choice(list(CITY_DISTRICTS.keys()))
    district = random.choice(CITY_DISTRICTS[city])
    street = random.choice(STREETS)
    num = random.randint(1, 450)
    suffix = random.choice(['', 'A', 'B', '/12', '/45', '/2'])
    return f"{num}{suffix} Đường {street}, {district}, {city}"

def remove_accents(text):
    # Basic mapping for Vietnamese accents
    accents = {
        'àáảãạăằắẳẵặâầấẩẫậ': 'a',
        'èéẻẽẹêềếểễệ': 'e',
        'ìíỉĩị': 'i',
        'òóỏõọôồốổỗộơờớởỡợ': 'o',
        'ùúủũụưừứửữự': 'u',
        'ỳýỷỹỵ': 'y',
        'đ': 'd',
        'ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬ': 'a',
        'ÈÉẺẼẸÊỀẾỂỀỆ': 'e',
        'ÌÍỈĨỊ': 'i',
        'ÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ': 'o',
        'ÙÚỦŨỤƯỪỨỬỮỰ': 'u',
        'ỲÝỶỸỴ': 'y',
        'Đ': 'd'
    }
    res = text
    for k, v in accents.items():
        for char in k:
            res = res.replace(char, v)
    return res

def generate_random_email(full_name, index):
    # Convert name to unaccented lowercase
    clean_name = remove_accents(full_name).lower()
    parts = clean_name.split()
    
    if len(parts) >= 3:
        # e.g. "nguyen van anh" -> "anh.nv" or "nguyen.anh"
        variants = [
            f"{parts[-1]}.{parts[0]}",
            f"{parts[-1]}{parts[0]}{random.randint(10, 99)}",
            f"{parts[0]}.{parts[-1]}",
            f"{parts[-1]}.{parts[1][0]}{parts[0][0]}"
        ]
    elif len(parts) == 2:
        variants = [
            f"{parts[1]}.{parts[0]}",
            f"{parts[0]}.{parts[1]}",
            f"{parts[1]}{parts[0]}{random.randint(10, 99)}"
        ]
    else:
        variants = [f"{parts[0]}{index}"]

    domain = random.choice(EMAIL_DOMAINS)
    prefix = random.choice(variants)
    return f"{prefix}@{domain}"


def main():
    sql_lines = []
    sql_lines.append("-- RICH DATA GENERATOR OUTPUT")
    sql_lines.append("TRUNCATE TABLE OrderDetails, Orders, ProductVariants, ProductComments, Reviews, Wishlist, Products, Categories, Colors, Sizes, Customers, NewsletterSubscribers, PasswordResetTokens RESTART IDENTITY CASCADE;")

    # 1. Categories
    sql_lines.append("-- 1. Categories")
    for cat in CATEGORIES:
        sql_lines.append(f"INSERT INTO Categories (CategoryID, CategoryName, Description) VALUES ({cat[0]}, '{cat[1]}', '{cat[2]}');")

    # 2. Colors
    sql_lines.append("\n-- 2. Colors")
    for i, name in enumerate(COLORS, 1):
        sql_lines.append(f"INSERT INTO Colors (ColorID, ColorName) VALUES ({i}, '{name}');")

    # 3. Sizes
    sql_lines.append("\n-- 3. Sizes")
    all_sizes = SIZES_CLOTHES + SIZES_PANTS
    for i, name in enumerate(all_sizes, 1):
        sql_lines.append(f"INSERT INTO Sizes (SizeID, SizeName) VALUES ({i}, '{name}');")

    # 4. Customers (Restore 11 Original + Expand to 200)
    sql_lines.append("\n-- 4. Customers (200)")
    sql_lines.append("INSERT INTO Customers (CustomerID, FullName, Email, Password, PhoneNumber, Address, IsAdmin, CreatedAt) VALUES")
    
    customers_data = []
    # Add Original 11 first (preserving their real data)
    for oc in ORIGINAL_CUSTOMERS:
        customers_data.append(f"({oc[0]}, '{oc[1]}', '{oc[2]}', '{PASSWORD_HASH}', '{oc[3]}', '{oc[4]}', {'TRUE' if oc[0]==11 else 'FALSE'}, CURRENT_TIMESTAMP)")
    
    # Add Expand 189 with realistic random data
    for i in range(12, 201):
        full_name = generate_viet_name()
        email = generate_random_email(full_name, i)
        # Random password for each
        random_pass = f"pass_{random.randint(100000, 999999)}"
        h = generate_password_hash(random_pass)
        phone = f"09{random.randint(10000000, 99999999)}"
        addr = generate_random_address()
        customers_data.append(f"({i}, '{full_name}', '{email}', '{h}', '{phone}', '{addr}', FALSE, CURRENT_TIMESTAMP - (random() * 365 || ' days')::interval)")
    
    sql_lines.append(",\n".join(customers_data) + ";")

    # 5. Products (Restore 22 Original + Expand 18 = 40)
    sql_lines.append("\n-- 5. Products (40)")
    sql_lines.append("INSERT INTO Products (ProductID, ProductName, Description, Price, CategoryID, CreatedAt, ImageURL) VALUES")
    products_data = []
    # Add Original 22
    for op in ORIGINAL_PRODUCTS:
        products_data.append(f"({op[0]}, '{op[1]}', '{op[2]}', {op[3]}, {op[4]}, CURRENT_TIMESTAMP, 'images/{op[0]}.jpg')")
    
    # Add Expansion 18
    for i, pt in enumerate(PRODUCT_TEMPLATES, 23):
        products_data.append(f"({i}, '{pt[1]}', '{pt[2]}', {pt[3]}, {pt[0]}, CURRENT_TIMESTAMP, 'images/{i}.jpg')")
    
    sql_lines.append(",\n".join(products_data) + ";")

    # 6. Product Variants
    sql_lines.append("\n-- 6. Product Variants")
    variants_sql = []
    v_id = 1
    for pid in range(1, 41):
        if pid <= 22:
            cat_id = ORIGINAL_PRODUCTS[pid-1][4]
        else:
            cat_id = PRODUCT_TEMPLATES[pid-23][0]
            
        sizes = SIZES_CLOTHES if cat_id in [1, 3, 5] else SIZES_PANTS
        # For accessories (cat 6), usually one size
        if cat_id == 6: sizes = ['Free Size']
        
        # Pick 2-4 colors and 2-4 sizes for each product
        selected_colors = random.sample(range(1, 13), random.randint(2, 4))
        for cid in selected_colors:
            num_s = 1 if cat_id == 6 else random.randint(2, len(sizes))
            # Get size IDs
            if cat_id == 6:
                # Add Free Size to DB if not exists? No, let's just use existing ones or add it.
                # Actually I'll use existing SIZES_CLOTHES[0] for accessories for simplicity
                selected_sizes = [1] 
            else:
                base_idx = 1 if cat_id in [1, 3, 5] else 6
                selected_sizes = random.sample(range(base_idx, base_idx + len(sizes)), num_s)
                
            for sid in selected_sizes:
                qty = random.randint(20, 100)
                variants_sql.append(f"({pid}, {cid}, {sid}, {qty})")
                v_id += 1
    
    sql_lines.append("INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity) VALUES")
    sql_lines.append(",\n".join(variants_sql) + ";")

    # 7. Engagement (Reviews & Comments)
    sql_lines.append("\n-- 7. Reviews")
    reviews_sql = []
    for pid in range(1, 41):
        num_r = random.randint(5, 15)
        reviewers = random.sample(range(2, 201), num_r)
        for cid in reviewers:
            rating, text = random.choice(REVIEWS_TEMPLATES)
            date = f"CURRENT_TIMESTAMP - (random() * 60 || ' days')::interval"
            reviews_sql.append(f"({cid}, {pid}, {rating}, '{text}', {date})")
    
    sql_lines.append("INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate) VALUES")
    sql_lines.append(",\n".join(reviews_sql) + " ON CONFLICT DO NOTHING;")

    sql_lines.append("\n-- 8. Product Comments")
    comments_sql = []
    for pid in range(1, 41):
        num_c = random.randint(3, 8)
        commenters = random.sample(range(2, 201), num_c)
        for cid in commenters:
            text = random.choice(COMMENTS_TEMPLATES)
            date = f"CURRENT_TIMESTAMP - (random() * 30 || ' days')::interval"
            comments_sql.append(f"({cid}, {pid}, '{text}', {date}, TRUE)")
    
    sql_lines.append("INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, IsVisible) VALUES")
    sql_lines.append(",\n".join(comments_sql) + ";")

    # 9. Orders (1000)
    sql_lines.append("\n-- 9. Orders (1000 Generated via PL/PGSQL)")
    order_gen_sql = """
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
    FOR i IN 1..1000 LOOP
        v_CustomerId := floor(random() * 199 + 2)::int;
        v_Date := CURRENT_TIMESTAMP - (random() * 730 || ' days')::interval;
        
        INSERT INTO Orders (CustomerID, OrderDate, TotalAmount, Status, PaymentMethod, ShippingAddress)
        VALUES (v_CustomerId, v_Date, 0, 
                CASE floor(random() * 4)::int 
                    WHEN 0 THEN 'Delivered' 
                    WHEN 1 THEN 'Processing' 
                    WHEN 2 THEN 'Shipped' 
                    ELSE 'Delivered' END,
                CASE floor(random() * 2)::int WHEN 0 THEN 'COD' ELSE 'Bank Transfer' END,
                'Address Info')
        RETURNING OrderID INTO v_OrderId;
        
        FOR j IN 1..floor(random() * 4 + 1)::int LOOP
            v_ProductId := floor(random() * 40 + 1)::int;
            SELECT VariantID INTO v_VariantId FROM ProductVariants WHERE ProductID = v_ProductId AND Quantity > 10 LIMIT 1;
            
            IF v_VariantId IS NOT NULL THEN
                SELECT Price INTO v_Price FROM Products WHERE ProductID = v_ProductId;
                INSERT INTO OrderDetails (OrderID, VariantID, Quantity, Price)
                VALUES (v_OrderId, v_VariantId, floor(random() * 2 + 1)::int, v_Price);
            END IF;
        END LOOP;
        
        UPDATE Orders SET TotalAmount = COALESCE((SELECT SUM(Quantity * Price) FROM OrderDetails WHERE OrderID = v_OrderId), 0) WHERE OrderID = v_OrderId;
    END LOOP;
END $$;
"""
    sql_lines.append(order_gen_sql)

    # 10. Sequences
    sql_lines.append("\n-- 10. Reset Sequences")
    sql_lines.append("SELECT setval('categories_categoryid_seq', (SELECT MAX(categoryid) FROM categories));")
    sql_lines.append("SELECT setval('colors_colorid_seq', (SELECT MAX(colorid) FROM colors));")
    sql_lines.append("SELECT setval('sizes_sizeid_seq', (SELECT MAX(sizeid) FROM sizes));")
    sql_lines.append("SELECT setval('customers_customerid_seq', (SELECT MAX(customerid) FROM customers));")
    sql_lines.append("SELECT setval('products_productid_seq', (SELECT MAX(productid) FROM products));")
    sql_lines.append("SELECT setval('productvariants_variantid_seq', (SELECT MAX(variantid) FROM productvariants));")
    sql_lines.append("SELECT setval('orders_orderid_seq', COALESCE((SELECT MAX(orderid) FROM orders), 1));")
    sql_lines.append("SELECT setval('orderdetails_orderdetailid_seq', COALESCE((SELECT MAX(orderdetailid) FROM orderdetails), 1));")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_lines))

    print(f"Dataset generated at {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
