# Proxify Architecture

## Phase 1 Optimization (Vòng 10 Blueprint)

Dựa trên kết quả tranh luận giữa các Agents, chúng ta đang triển khai Kiến trúc mới (Vòng 10 Blueprint).

### 1. Radix Trie Router (Cây Tiền Tố)
Thay vì lặp qua toàn bộ Plugins O(N) với mỗi request, hệ thống mới sử dụng `ProxyRouter` (`proxify/core/router.py`). 
- Router phân tách tên miền (VD: `api.facebook.com` thành `['com', 'facebook', 'api']`).
- Các Interceptor được đăng ký vào các node của Trie. Tốc độ tìm kiếm là O(depth) - cực kỳ nhanh và hỗ trợ tốt wildcard subdomains.

### 2. Tách Biệt Read-Only và Mutating (CQRS cho Proxy)
- `IObserverInterceptor`: Các addon chuyên dùng để đọc/lắng nghe (như ghi log vào Database). Router sẽ ném chúng vào `asyncio.create_task` chạy nền (Fire and forget) để không làm chậm luồng proxy.
- `IMutatorInterceptor`: Các addon sửa đổi (như tiêm JS, sửa Header). Router sẽ dùng `await` để buộc Proxy phải chờ hoàn tất mới đi tiếp.

### 3. Hướng Đi Tiếp Theo (Next Steps)
- Migrate Database sang `asyncpg`.
- Xây dựng bảng `raw_payloads` và luồng xử lý Offline Worker.
- Tích hợp `AsyncEventBus` có hỗ trợ Backpressure.
