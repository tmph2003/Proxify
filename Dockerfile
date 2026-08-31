# Sử dụng Python 3.10 slim để tối ưu dung lượng
FROM python:3.10-slim

WORKDIR /app

# 1. Cài đặt các thư viện hệ thống (Layer này không bao giờ thay đổi trừ khi đổi HĐH)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Cài đặt requirements.txt (Layer này chỉ thay đổi khi requirements.txt thay đổi)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Cài đặt Playwright OS dependencies (Layer này tốn thời gian nhất nhưng sẽ được Cache vĩnh viễn)
RUN pip install playwright && playwright install-deps chromium

# 4. Copy và cài đặt CloakBrowser (Thay đổi hiếm khi, chỉ khi bạn code lại CloakBrowser)
COPY CloakBrowser /app/CloakBrowser
RUN pip install -e /app/CloakBrowser

# 5. Copy toàn bộ mã nguồn Proxify (Thay đổi liên tục mỗi khi bạn code)
COPY . /app
RUN pip install -e .

# Mở port 8080 (Proxy) và 8888 (Dashboard)
EXPOSE 8080 8888

# Set biến môi trường để mitmproxy lắng nghe trên 0.0.0.0 (NAT ra ngoài) thay vì 127.0.0.1
ENV PROXY_HOST=0.0.0.0
ENV PROXY_PORT=8080
ENV DASHBOARD_PORT=8888

# Lệnh chạy mặc định
CMD ["python", "-m", "proxify"]
