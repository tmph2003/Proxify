# Auto Documentation: Hợp nhất Event Loop & Cấu trúc Platform

## 1. Tóm tắt thay đổi
- Đã tách lớp logic của Facebook ra thành `FacebookPlatform` (tuân thủ OCP) trong `proxify/platforms/facebook/platform.py`.
- Tách luồng bắt dữ liệu GraphQL cũ thành `FacebookGraphQLObserver` (chỉ đọc, không làm nghẽn Proxy). Dữ liệu này giờ được đẩy vào `AsyncEventBus`.
- Khởi tạo file `proxify/server_v2.py`: Đóng gói cả Mitmproxy (`DumpMaster`) và API (`aiohttp`) chạy song song trên **cùng một Event Loop duy nhất**.

## 2. Mục đích & Ý nghĩa
- Gỡ bỏ hoàn toàn mớ bòng bong liên lạc đa luồng (thread-safe queues) giữa Proxy và Dashboard ở phiên bản cũ.
- Giữ được hiệu năng cao nhất nhờ cơ chế CQRS (Bắt nhanh - xử lý chậm bằng EventBus).
- Mở đường để chuyển dần các nền tảng khác (Zalo) sang mô hình mới mà không làm hỏng app hiện tại (do đang chạy nháp trên `server_v2.py`).

## 3. Rủi ro (Risks & Edge Cases)
- **API Legacy:** Tạm thời `FacebookPlatform` vẫn phải `import FacebookPlugin` cũ để mượn tạm hàm `get_api_routes()`. Nếu gọi API lúc này có thể phát sinh lỗi do nó vẫn chọc vào biến toàn cục của file cũ. Sẽ cần di dời toàn bộ API này sang `proxify/platforms/facebook/api.py` ở bước sau.
- Cần tạo Background Worker độc lập để bóc tách `core.raw_payloads` thành các bảng `posts`, `comments`.
