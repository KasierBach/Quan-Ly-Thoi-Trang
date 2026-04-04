# 👕 HỆ THỐNG QUẢN LÝ CỬA HÀNG THỜI TRANG (FASHION STORE)

[![Flask](https://img.shields.io/badge/Flask-2.3.3-blue.svg)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-blue.svg)](https://www.docker.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Socket.io](https://img.shields.io/badge/Socket.io-Realtime-orange.svg)](https://socket.io/)
[![Python](https://img.shields.io/badge/Python-3.11-green.svg)](https://www.python.org/)

Hệ thống Quản lý Cửa hàng Thời trang là một ứng dụng web toàn diện được thiết kế để tối ưu hóa quy trình kinh doanh và trải nghiệm khách hàng. Dự án này được xây dựng theo mô hình **MVC (Model-View-Controller)** và tuân thủ các nguyên lý thiết kế phần mềm hiện đại như **SOLID**, đảm bảo tính mở rộng và dễ bảo trì.

---

## 📂 Cấu Trúc Thư Mục Dự Án (Project Structure)

```text
thua-2.0/
├── app/                        # Thư mục chính của ứng dụng
│   ├── routes/                 # Quản lý điều hướng (Blueprints)
│   │   ├── admin/              # Module quản trị (Sản phẩm, Đơn hàng, Thống kê)
│   │   ├── auth.py             # Xác thực người dùng (Login, Register, Password Reset)
│   │   ├── cart.py             # Quản lý giỏ hàng & Thanh toán
│   │   ├── chat.py             # API cho hệ thống trò chuyện
│   │   ├── main.py             # Trang chủ & Logic chung
│   │   └── product.py          # Hiển thị & tìm kiếm sản phẩm
│   ├── services/               # Lớp xử lý logic nghiệp vụ (Business Logic)
│   │   ├── auth_service.py     # Xử lý xác thực & phân quyền
│   │   ├── product_service.py  # Xử lý dữ liệu sản phẩm & kho
│   │   └── chat_service.py     # Logic tin nhắn & thời gian thực
│   ├── static/                 # Tài nguyên tĩnh (CSS, JS, Images)
│   ├── templates/              # Giao diện Jinja2 (HTML)
│   ├── __init__.py             # Khởi tạo App Factory & Extensions
│   ├── config.py               # Cấu hình hệ thống (Environment variables)
│   ├── database.py             # Cấu hình kết nối PostgreSQL (Pooled Connection)
│   ├── sockets.py              # Xử lý sự kiện WebSocket (Socket.IO)
│   └── utils.py                # Các hàm tiện ích (Email, Slugify, Image Resolver)
├── .data/                      # Script SQL khởi tạo (Schema & Data)
├── .scripts/                   # Công cụ hỗ trợ (Import DB, Generate Data, Locust Test)
├── Dockerfile                  # Cấu hình Docker image
├── docker-compose.yml          # Cấu hình App & Database containers
├── requirements.txt            # Danh sách thư viện Python
└── run.py                      # Điểm khởi chạy ứng dụng (Entry point)
```

---

## 🏗️ Kiến Trúc & Công Nghệ (Technical Stack)

### Backend
- **Flask Framework**: Sử dụng `Blueprint` để module hóa các chức năng.
- **PostgreSQL**: Cơ sở dữ liệu quan hệ mạnh mẽ.
- **Psycopg2 with ThreadedConnectionPool**: Tối ưu hóa hiệu suất truy vấn, hỗ trợ đa luồng.
- **SQLAlchemy (Core/ORM)**: Hỗ trợ quản lý session và cấu trúc bảng.
- **Flask-SocketIO**: Hỗ trợ giao tiếp song công (Full-duplex) cho tính năng chat.

### Frontend
- **Jinja2**: Server-side rendering cho tính tương thích SEO cao.
- **Vanilla CSS & JavaScript (AJAX)**: Đảm bảo trải nghiệm người dùng mượt mà mà không làm nặng trang.
- **FontAwesome & Google Fonts**: Giao diện hiện đại, chuyên nghiệp.

---

## ⚙️ Hướng Dẫn Cài Đặt (Installation)

### 🐳 Cách 1: Sử dụng Docker (Khuyên dùng)
Dự án đã được đóng gói hoàn chỉnh, giúp chạy ngay lập tức mà không cần cài đặt môi trường máy local:

1. **Cấu hình biến môi trường:**
   Đảm bảo bạn đã có file `.env` chứa chuỗi kết nối Cloud Database (ví dụ: Supabase).
   `DATABASE_URL=postgresql://user:password@aws-host.supabase.com:6543/postgres`

2. **Khởi động dịch vụ Web bằng Docker:**
   ```powershell
   # Di chuyển vào thư mục dự án
   cd thua-2.0
   
   # Build và khởi động container
   docker-compose up --build -d
   ```

3. **Khởi tạo Database (Chỉ áp dụng lần đầu):**
   Nếu cơ sở dữ liệu Supabase của bạn trống, hãy chạy lệnh sau để tự tạo bảng và nạp dữ liệu mẫu:
   ```powershell
   docker-compose exec web python .scripts/import_db.py
   ```
   *Truy cập tại: `http://localhost:4000`* (Cổng mặc định theo file cấu hình)

### 💻 Cách 2: Cài đặt Thủ công (Local)
Nếu bạn muốn chạy trực tiếp trên máy tính:

1. **Yêu cầu:** Đã cài đặt Python 3.10+
2. **Khởi tạo môi trường ảo:**
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. **Cài đặt thư viện:**
   ```powershell
   pip install -r requirements.txt
   ```
4. **Cấu hình biến môi trường (`.env`):**
   Tạo file `.env` từ `.env.example` và điền thông tin `DATABASE_URL` của Supabase hoặc PostgreSQL.
5. **Khởi tạo Database:**
   ```powershell
   python .scripts/import_db.py
   ```
6. **Chạy ứng dụng:**
   ```powershell
   python run.py
   ```

---

## 📊 Kiến Trúc Dữ Liệu (Database Schema)

Hệ thống sử dụng các stored procedures (SP) để xử lý logic phức tạp ở tầng DB, giúp tăng tốc độ và bảo mật:

- **Bảng chính:**
    - `Customers`: Thông tin tài khoản, vai trò (admin/customer), địa chỉ.
    - `Products`: Thông tin chung về sản phẩm.
    - `ProductVariants`: Quản lý tồn kho theo Màu sắc & Kích thước.
    - `Orders` & `OrderDetails`: Lưu trữ lịch sử giao dịch.
    - `Messages`: Lưu trữ lịch sử chat.
- **Stored Procedures tiêu biểu:**
    - `sp_AddProduct`: Tự tạo sản phẩm mới và gán thuộc tính.
    - `sp_CreateOrder`: Xử lý transaction đặt hàng và trừ tồn kho.
    - `sp_SearchProducts`: Tìm kiếm nâng cao với nhiều bộ lọc.

---

## 🛡️ Bảo Mật (Security Implementation)

Dự án ưu tiên tính an toàn dữ liệu với các biện pháp:
1.  **Chống SQL Injection**: Sử dụng *Parameterized Queries* thông qua thư viện psycopg2.
2.  **Xác thực mật khẩu**: Sử dụng `PBKDF2` (Werkzeug hashing) để lưu trữ mật khẩu an toàn.
3.  **CSRF Protection**: Tích hợp `Flask-WTF` bảo vệ toàn bộ các form nhập liệu.
4.  **Phân quyền (RBAC)**: Hệ thống Decorator (`@admin_required`) kiểm soát chặt chẽ quyền truy cập.
5.  **Bảo mật Session**: Cấu hình Secure Cookies để ngăn chặn các cuộc tấn công đánh cắp phiên.

---

## 📱 Tính Năng Real-time Chat

Hệ thống hỗ trợ khách hàng tích hợp sẵn cho phép:
- Khách vãng lai chat trực tiếp với Admin thông qua ID phiên (Session ID).
- Người dùng đã đăng nhập có thể xem lại lịch sử trò chuyện.
- Thông báo trạng thái Online/Offline và Đang nhập liệu (Typing indicator).

---

## 🚀 Lộ Trình Phát Triển (Future Roadmap)
- [ ] Tích hợp cổng thanh toán trực tuyến (VNPay/Momo).
- [ ] Xây dựng hệ thống gợi ý sản phẩm dựa trên AI (Collaborative Filtering).
- [ ] Phát triển phiên bản Mobile App sử dụng React Native.
