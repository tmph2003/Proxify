# Sử dụng Python 3.10 slim để tối ưu dung lượng
FROM python:3.10-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Cài đặt các thư viện hệ thống cần thiết cho mitmproxy và psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements và cài đặt trước để tận dụng cache của Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn
COPY . .

# Cài đặt package hiện tại
RUN pip install -e .

# Cài đặt Playwright (Chromium only)
RUN pip install playwright && playwright install chromium --with-deps

# Mở port 8080 (Proxy) và 8888 (Dashboard)
EXPOSE 8080 8888

# Set biến môi trường để mitmproxy lắng nghe trên 0.0.0.0 (NAT ra ngoài) thay vì 127.0.0.1
ENV PROXY_HOST=0.0.0.0
ENV PROXY_PORT=8080
ENV DASHBOARD_PORT=8888

# Lệnh chạy mặc định
CMD ["python", "-m", "proxify"]
