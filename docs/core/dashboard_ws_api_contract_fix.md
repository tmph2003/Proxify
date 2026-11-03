# Đồng bộ Hợp đồng Giao diện (API & WebSocket Contract) giữa Rust Core và React Dashboard

## Tóm tắt thay đổi
- **`crates/proxify-core/src/proxy.rs`**:
  - Gỡ bỏ bộ đếm giả lập trên RAM `LIVE_REQUEST_SEQ` trong `observe_and_record`.
  - Sinh định danh `req_uuid` (UUID v4) cho mỗi request live, phát sự kiện WebSocket `new_request` với `"id": 0` (trạng thái `LIVE`), đồng thời chuẩn hóa đầy đủ các trường mà React Frontend yêu cầu: `req_uuid`, `domain` (song song với `host`), `response_content_type` (song song với `content_type`), `response_size` (song song với `size_bytes`), và `timestamp` định dạng ISO-8601 RFC3339 (tránh lỗi hiển thị `1970-01-21 02:11:53` do JavaScript `new Date()` hiểu nhầm giây thành mili-giây).
  - Bổ sung hỗ trợ giải nén `zstd` trong `decompress_body` bên cạnh `gzip`, `deflate` và `br`.
- **`crates/proxify-core/src/storage.rs` & `crates/proxify-server/src/main.rs`**:
  - Bổ sung `RequestStorage::with_event_bus` và `enqueue_tracked(record, req_uuid)` (giữ nguyên `RequestStorage::new` và `enqueue` để tương thích ngược 100%).
  - Nâng cấp câu lệnh chèn lô vector hóa `INSERT INTO public.requests (...) VALUES (...) RETURNING id` trong `flush_batch` để lấy danh sách khóa chính PostgreSQL thực tế ngay trong cùng 1 vòng truy vấn mạng, sau khi `commit` thành công sẽ phát sự kiện WebSocket `update_id` (`{ req_uuid, row_id }`) để UI tự động cập nhật `LIVE` sang ID thật trong Database.
  - Chuẩn hóa `query_requests` trả về trực tiếp mảng JSON (`Value::Array`) thay vì bọc trong object phân trang, đồng thời bổ sung các trường `requests`, `domains`, `graphql` vào `get_stats`.
- **`crates/proxify-core/src/dashboard.rs`**:
  - Chuẩn hóa `GET /api/domains` trả về mảng JSON trực tiếp (`Value::Array`), và mở rộng `RequestsQuery` hỗ trợ đồng thời cả `status`/`status_code` lẫn `graphql`/`graphql_only`.
- **`Dockerfile`**:
  - Bổ sung `build-essential` (cần thiết để biên dịch C allocator `libmimalloc-sys`) và đồng bộ đầy đủ cấu trúc workspace (`Cargo.lock`, `src/`, `crates/`, `tests/`, `benches/`) cho quá trình đóng gói production image `proxify-server`.

## Mục đích & Ý nghĩa
- Khắc phục triệt để lỗi trên giao diện `localhost:8888` khi bấm vào một dòng request nhưng khung chi tiết bên phải không hiển thị Response/Headers (`404 Request not found` do WebSocket gửi ID bộ đếm RAM `1..5210` không khớp với ID thực `8505xx` trong PostgreSQL).
- Khắc phục lỗi cột `Content-Type` luôn hiện `-`, cột `Size` luôn hiện `0 B`, mất tên miền trước đường dẫn URL, cột `Time` kẹt cứng ở `02:11:53`, thanh thống kê góc phải (`Requests / Domains / GraphQL`) bị trống, và khi bấm `F5` không tải được danh sách request lịch sử từ PostgreSQL.
- Đồng thời đưa toàn bộ bản tối ưu hiệu năng Zero-Copy / Async CA / Vectorized Batch Insert lên container runtime `proxify_app`.

## Mối liên hệ
- Liên kết trực tiếp giữa tầng Infrastructure/Presentation của Rust (`crates/proxify-core/src/proxy.rs`, `storage.rs`, `dashboard.rs`, `crates/proxify-server/src/main.rs`) với ứng dụng React SPA (`frontend/src/hooks/useRequests.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/layouts/MainLayout.tsx`) và tiện ích mở rộng Chrome (`backend/chrome_extension/popup.js`).

## Rủi ro (Risks & Edge Cases)
- **Chế độ Tắt Ghi DB (`save_to_db = false`) hoặc Domain bị lọc bỏ**: Khi tắt ghi DB, sự kiện `new_request` vẫn hiển thị tức thời trên UI với nhãn `LIVE` (`id = 0`), và sẽ không có sự kiện `update_id`. Giao diện `Dashboard.tsx` đã xử lý sẵn nhánh `selectedId === 0` để thông báo rõ cho người dùng biết request đang ở chế độ Live chưa lưu DB, tránh gọi API `GET /api/requests/0` gây lỗi 404.
- **Hiệu năng Batch Insert khi thêm `RETURNING id`**: Việc thêm `RETURNING id` trên lô 50 bản ghi chỉ trả thêm 50 số nguyên 4-byte (`~200 bytes`) trong cùng một gói phản hồi TCP của PostgreSQL, không làm tăng số lượng round-trip và vẫn giữ nguyên tốc độ ghi vector hóa.
