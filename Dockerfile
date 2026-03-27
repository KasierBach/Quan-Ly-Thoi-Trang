# Sử dụng Python slim image để giảm kích thước
FROM python:3.11-slim

# Ngăn Python tạo ra tệp .pyc và bật log không đệm
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Cài đặt các gói hệ thống cần thiết cho PostgreSQL và build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Tạo người dùng không phải root để bảo mật
RUN adduser --disabled-password --gecos "" appuser

# Copy requirements.txt trước để tận dụng layer caching
COPY requirements.txt .

# Cài đặt dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn
COPY . .

# Thay đổi quyền sở hữu cho appuser
RUN chown -R appuser:appuser /app
USER appuser

# Mở cổng 4000 (mặc định của run.py)
EXPOSE 4000

# Chạy ứng dụng bằng Gunicorn với gevent worker để hỗ trợ Socket.IO
CMD ["gunicorn", "--worker-class", "gevent", "--workers", "1", "--bind", "0.0.0.0:4000", "run:app"]