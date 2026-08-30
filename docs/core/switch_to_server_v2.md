# Chuyển đổi Entrypoint sang Server v2

## Tóm tắt thay đổi
1. **`proxify/__main__.py`**:
   - Thay đổi hàm khởi chạy chính (`main`) từ việc import `proxify.server` sang `proxify.server_v2.run_server`.
   - Bọc luồng khởi chạy trong `asyncio.run()`.
2. **`proxify/server_v2.py`**:
   - Chỉnh lại phần binding cổng cho Mitmproxy để đọc từ biến `PROXY_PORT` (mặc định là `8080`), thay vì fix cứng `8081`. 
   - Điều chỉnh cổng của Dashboard để đọc từ biến môi trường `DASHBOARD_PORT` (mặc định là `8888`), thay vì fix cứng `8889`. 
3. **`requirements.txt`**:
   - Bổ sung thư viện `asyncpg` (module kết nối database tốc độ cao dành riêng cho `server_v2`).

## Mục đích & Ý nghĩa
- Kích hoạt chính thức kiến trúc mới (`server_v2.py`) cho toàn bộ dự án khi chạy lệnh `python -m proxify` hoặc khi khởi động bằng Docker.
- `server_v2.py` giải quyết được vấn đề chạy chung Mitmproxy và Aiohttp trên cùng một Event Loop, giúp hệ thống hoạt động mượt mà hơn và tránh bị xung đột socket.
- Việc đọc cấu hình từ biến môi trường giúp Server hoạt động trơn tru với `docker-compose.yml` (ánh xạ chính xác ra cổng 8080 và 8888 của máy chủ vật lý).

## Mối liên hệ
- Lệnh `docker-compose up -d` giờ đây sẽ tự động cài thêm Playwright, Chromium, Asyncpg và sử dụng `server_v2.py` nhờ sự thay đổi trong `__main__.py`.

## Rủi ro (Risks & Edge Cases)
- Tiến trình build Docker mất khoảng vài phút do phải cài đặt thư viện hệ thống và Playwright Chromium (tầm 150MB).
- `server_v2` có thể còn một số module nhỏ chưa được migrate đầy đủ từ `server.py` cũ (ví dụ: Zalo, Tiktok), hiện tại nó đang tập trung vào module Facebook. Nếu phát sinh lỗi khi chạy các platform khác, cần migrate nốt router của chúng sang kiến trúc v2.
