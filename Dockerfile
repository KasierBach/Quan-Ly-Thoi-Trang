FROM python:3.11-slim

# Cài gói hệ thống cần thiết (KHÔNG có libssl1.1 vì đã bị loại bỏ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg2 \
    curl \
    apt-transport-https \
    unixodbc \
    unixodbc-dev \
    libunwind8

# Thêm repo của Microsoft để cài driver SQL Server
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql17

# Tạo thư mục làm việc
WORKDIR /app

# Copy mã nguồn vào container
COPY . /app

# Cài thư viện Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Chạy ứng dụng Flask
CMD ["python", "app.py"]