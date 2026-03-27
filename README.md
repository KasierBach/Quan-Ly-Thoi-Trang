# 👕 HỆ THỐNG QUẢN LÝ CỬA HÀNG THỜI TRANG (FASHION STORE MANAGEMENT)

[![Flask](https://img.shields.io/badge/Flask-2.3.3-blue.svg)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-blue.svg)](https://www.docker.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Socket.io](https://img.shields.io/badge/Socket.io-Realtime-orange.svg)](https://socket.io/)
[![Python](https://img.shields.io/badge/Python-3.11-green.svg)](https://www.python.org/)

Hệ thống Quản lý Cửa hàng Thời trang là một ứng dụng web toàn diện được thiết kế để tối ưu hóa quy trình kinh doanh và trải nghiệm khách hàng. Dự án này được xây dựng theo mô hình MVC (Model-View-Controller) và tuân thủ các nguyên lý thiết kế phần mềm hiện đại như SOLID, đảm bảo tính mở rộng và dễ bảo trì.

---

## 📂 Cấu Trúc Thư Mục Dự Án (Project Structure)

```text
thua-2.0/
├── app/                        # Thư mục chính của ứng dụng
│   ├── routes/                 # Quản lý điều hướng (Blueprints)
│   │   ├── admin.py            # Chức năng quản trị viên
│   │   ├── auth.py             # Xác thực người dùng
│   │   ├── cart.py             # Quản lý giỏ hàng
│   │   ├── chat.py             # Xử lý trò chuyện thời gian thực
│   │   ├── main.py             # Trang chủ và logic chung
│   │   └── product.py          # Quản lý danh mục và sản phẩm
│   ├── services/               # Lớp xử lý logic nghiệp vụ (Business Logic)
│   ├── static/                 # Tài nguyên tĩnh (CSS, JS, Images)
│   ├── templates/              # Giao diện Jinja2 (HTML)
│   ├── __init__.py             # Khởi tạo App Factory & Extensions
│   ├── config.py               # Cấu hình hệ thống (Environment variables)
│   ├── database.py             # Cấu hình kết nối PostgreSQL & SQLAlchemy
│   ├── sockets.py              # Xử lý sự kiện WebSocket (Socket.IO)
│   └── utils.py                # Các hàm tiện ích bổ trợ
├── .data/                      # Thư mục lưu trữ dữ liệu cục bộ
├── .scripts/                   # Các script hỗ trợ tự động hóa
├── Dockerfile                  # Cấu hình Docker image
├── docker-compose.yml          # Cấu hình điều phối container (App & DB)
├── .dockerignore               # Loại bỏ tệp rác khỏi Docker context
├── .env                        # Chứa các biến môi trường nhạy cảm
├── requirements.txt            # Danh sách các thư viện Python cần thiết
├── run.py                      # Điểm khởi chạy ứng dụng (Entry point)
├── render.yaml                 # Cấu hình triển khai lên Render.com
└── vercel.json                 # Cấu hình triển khai lên Vercel
```

---

## 🏗️ Kiến Trúc Hệ Thống (System Architecture)

Hệ thống được thiết kế theo kiến trúc phân lớp, tách biệt rõ ràng giữa các thành phần:

1.  **Presentation Layer (Jinja2 Templates)**: Giao diện người dùng tương tác, thực hiện render phía server để tối ưu SEO.
2.  **Controller Layer (Flask Blueprints)**: Điều hướng yêu cầu và phản hồi từ người dùng.
3.  **Service Layer**: Chứa toàn bộ logic nghiệp vụ, giúp mã nguồn tại Controller gọn gàng và dễ kiểm tra (Unit Test).
4.  **Data Access Layer (SQLAlchemy ORM + Psycopg2)**: Giao tiếp với cơ sở dữ liệu PostgreSQL. Hệ thống sử dụng **ThreadedConnectionPool** để tối ưu hóa hiệu suất truy vấn trong môi trường đa luồng.
5.  **Real-time Layer (Socket.IO)**: Duy trì kết nối song công (Full-duplex) để phục vụ tính năng Chat hỗ trợ khách hàng tức thì.

---

## 🚀 Tính Năng Chính (Key Features)

### Đối với Khách Hàng:
- **Duyệt sản phẩm**: Xem danh sách theo danh mục, tìm kiếm nâng cao (tích hợp Pixabay API cho hình ảnh minh họa).
- **Giỏ hàng**: Trải nghiệm thêm/sửa/xóa sản phẩm không cần tải lại trang (AJAX).
- **Thanh toán**: Quy trình đặt hàng trực quan.
- **Hỗ trợ trực tuyến**: Chat trực tiếp với admin để được giải đáp thắc mắc.

### Đối với Quản Trị Viên (Admin):
- **Dashboard**: Thống kê tổng quan tình hình kinh doanh.
- **Quản lý kho**: Thêm, sửa, xóa sản phẩm và danh mục linh hoạt.
- **Quản lý đơn hàng**: Theo dõi trạng thái và xử lý đơn hàng của khách.
- **Quản lý người dùng**: Kiểm soát quyền hạn và thông tin tài khoản.

---

## 🔧 Hướng Dẫn Vận Hành

### Sử dụng Docker (Professional Environment)
Dự án đã được container hóa hoàn toàn, giúp triển khai đồng nhất trên mọi môi trường:

```powershell
# Cài đặt và chạy đồng thời App và Cơ sở dữ liệu
docker compose up --build -d
```
*Hệ thống sẽ tự động khởi tạo database PostgreSQL 15 và kết nối với Flask qua mạng nội bộ của Docker.*

### Biến môi trường quan trọng (.env)
| Biến | Mô tả |
| :--- | :--- |
| `SECRET_KEY` | Mã khóa bảo mật phiên làm việc |
| `DATABASE_URL` | Đường dẫn kết nối PostgreSQL |
| `MAIL_SERVER` | Server gửi email (mặc định smtp.gmail.com) |
| `PIXABAY_API_KEY` | API Key để tìm kiếm hình ảnh sản phẩm |

---

## 📈 Hướng Phát Triển (Future Roadmap)
- [ ] Tích hợp cổng thanh toán trực tuyến (VNPay, Momo).
- [ ] Áp dụng AI để gợi ý sản phẩm dựa trên hành vi người dùng.
- [ ] Xây dựng Ứng dụng di động (React Native) kết nối qua API hiện có.

---

## 🎓 Tài Liệu Tham Khảo cho Tiểu Luận
- Kiến trúc phần mềm: MVC, SOLID.
- Công nghệ: Python Flask, PostgreSQL, WebSocket, Docker Virtualization.
- Quy trình: Agile/Scrum (giả định).

---
**Dự án được thực hiện bởi: [Tên của bạn]**  
*Mã số sinh viên: [MSSV của bạn]*  
*Trường: [Tên Trường của bạn]*
