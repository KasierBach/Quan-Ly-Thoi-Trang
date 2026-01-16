FROM python:3.11-slim

# Cài đặt các gói hệ thống cần thiết cho PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Copy mã nguồn vào container
COPY . /app

# Cài thư viện Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Chạy ứng dụng bằng Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "run:app"]