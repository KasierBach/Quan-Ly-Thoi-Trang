FROM python:3.11-slim

# Cài các thư viện hệ thống và driver SQL Server
RUN apt-get update && apt-get install -y \
    gnupg2 \
    curl \
    apt-transport-https \
    unixodbc \
    unixodbc-dev \
    libunwind8 \
    libssl1.1

# Cài Microsoft ODBC Driver 17 for SQL Server
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql17

# Tạo thư mục làm việc và copy mã nguồn
WORKDIR /app
COPY . /app

# Cài các thư viện Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Chạy app Flask
CMD ["python", "app.py"]