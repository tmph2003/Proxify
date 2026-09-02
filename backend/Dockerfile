# Sử dụng Python 3.10 slim để tối ưu dung lượng
FROM python:3.10-slim

WORKDIR /app

# 1. Cài đặt các thư viện hệ thống
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Cài đặt requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Cài đặt Playwright OS dependencies
RUN pip install playwright && playwright install-deps chromium

# 4. Copy và cài đặt CloakBrowser
COPY CloakBrowser /app/CloakBrowser
RUN pip install -e /app/CloakBrowser

# 5. Copy toàn bộ mã nguồn Proxify
COPY . /app
RUN pip install -e .

# Mở port 8080 (Proxy) và 8888 (Dashboard Backend API)
EXPOSE 8080 8888

# Set biến môi trường để mitmproxy lắng nghe trên 0.0.0.0
ENV PROXY_HOST=0.0.0.0
ENV PROXY_PORT=8080
ENV DASHBOARD_PORT=8888

# Lệnh chạy mặc định
CMD ["python", "-m", "proxify"]
