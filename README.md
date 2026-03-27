# 👕 Hệ Thống Quản Lý Cửa Hàng Thời Trang

[![Flask](https://img.shields.io/badge/Flask-2.3.3-blue.svg)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-blue.svg)](https://www.docker.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Socket.io](https://img.shields.io/badge/Socket.io-Realtime-orange.svg)](https://socket.io/)

Một ứng dụng web hiện đại được xây dựng để quản lý cửa hàng thời trang, hỗ trợ đầy đủ các tính năng từ mua hàng, giỏ hàng đến quản trị viên và trò chuyện trực tuyến thời gian thực.

---

## 🚀 Các Tính Năng Nổi Bật

- **🔐 Xác thực người dùng**: Đăng ký, đăng nhập và quản lý phiên làm việc bảo mật.
- **🛍️ Quản lý sản phẩm**: Hiển thị danh sách sản phẩm theo danh mục, tìm kiếm và chi tiết sản phẩm.
- **🛒 Giỏ hàng thông minh**: Thêm, sửa, xóa sản phẩm trong giỏ hàng một cách nhanh chóng.
- **💬 Trò chuyện trực tuyến**: Hệ thống chat realtime giữa khách hàng và quản trị viên sử dụng Socket.IO.
- **🛠️ Bảng điều khiển Admin**: Quản lý sản phẩm, đơn hàng và người dùng chuyên nghiệp.
- **📧 Thông báo email**: Tích hợp Flask-Mail để gửi thông báo cho người dùng.
- **📱 Giao diện tương thích**: Hoạt động mượt mà trên cả desktop và thiết bị di động.

---

## 🛠️ Công Nghệ Sử Dụng

### Backend
- **Ngôn ngữ**: Python 3.11
- **Framework**: Flask
- **Database**: PostgreSQL (với Flask-SQLAlchemy)
- **Real-time**: Flask-SocketIO (với Gevent)
- **WSGI Server**: Gunicorn

### Frontend
- **Template Engine**: Jinja2
- **Styling**: Vanilla CSS / Bootstrap (tùy cấu hình)
- **Script**: JavaScript (xử lý Socket.IO và UI)

---

## 📦 Hướng Dẫn Cài Đặt

### 1. Sử dụng Docker (Khuyên dùng) - Nhanh chóng & Tiện lợi

Yêu cầu: Đã cài đặt [Docker](https://docs.docker.com/get-docker/) và [Docker Compose](https://docs.docker.com/compose/install/).

```powershell
# Khởi chạy toàn bộ hệ thống (App + Database)
docker compose up --build -d
```

Ứng dụng sẽ khả dụng tại: `http://localhost:4000`

### 2. Cài đặt thủ công (Local Development)

Yêu cầu: Python 3.11+ và PostgreSQL.

1. **Clone dự án**:
   ```bash
   git clone <url-cua-ban>
   cd thua-2.0
   ```

2. **Tạo môi trường ảo và cài đặt thư viện**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Hoặc venv\Scripts\activate trên Windows
   pip install -r requirements.txt
   ```

3. **Cấu hình môi trường**:
   - Sao chép tệp `.env.example` thành `.env`.
   - Cập nhật các thông số `DATABASE_URL`, `SECRET_KEY`, v.v.

4. **Chạy ứng dụng**:
   ```bash
   python run.py
   ```

---

## 🐳 Cấu Hình Docker

Hệ thống được thiết kế với kiến trúc Microservices đơn giản:
- **Web Service**: Chạy Flask với Gunicorn (Gevent worker) để hỗ trợ async tốt nhất.
- **DB Service**: Chạy PostgreSQL 15-alpine, hỗ trợ volume lưu trữ dữ liệu bền vững.

Dữ liệu database được lưu tại volume: `postgres_data`.

---

## 📝 Tài Liệu Tiểu Luận

Dự án này tuân thủ các nguyên tắc thiết kế phần mềm sạch (Clean Code) và nguyên lý SOLID:
- **Modular Design**: Các chức năng được chia nhỏ thành các Blueprint (Auth, Product, Admin, etc.).
- **Service Layer**: Tách biệt logic xử lý dữ liệu khỏi Controller.
- **Real-time Architecture**: Sử dụng WebSocket để tối ưu hóa trải nghiệm người dùng trong tính năng Chat.

---
⭐ Nếu bạn thấy dự án này hữu ích, hãy cho nó 1 sao nhé!
