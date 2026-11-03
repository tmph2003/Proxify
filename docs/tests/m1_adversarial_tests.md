# Tài Liệu Kỹ Thuật: Bộ Kiểm Thử Đối Kháng Milestone 1 (M1 Adversarial Tests)

## 1. Tóm tắt thay đổi
Bổ sung bộ kiểm thử đối kháng tự động chuyên sâu `tests/m1_adversarial_tests.rs` và cấu hình mục tiêu kiểm thử trong `Cargo.toml`. Bộ test này đóng vai trò là hàng rào kiểm định độc lập của Challenger 2 đối với Milestone 1: Concurrency & Boundary Verification.

Các bài test bao gồm:
1. `test_adv_storage_shutdown_flushes_under_high_backlog`: Kiểm thử xả hàng đợi ghi nhận request khi shutdown dưới tải dồn dập (burst 150 records liên tục), xác minh không xảy ra deadlock và bảo toàn 100% dữ liệu vào PostgreSQL nếu DB sẵn sàng.
2. `test_adv_storage_concurrent_multi_shutdown_deadlock_safety`: 10 tác vụ bất đồng bộ đồng thời gọi `shutdown()` và `flush()`, xác thực cơ chế barrier đồng bộ hóa kênh oneshot không gây tranh chấp hoặc treo tiến trình.
3. `test_adv_large_payload_streaming_10mb_preserves_content_length`: Kiểm thử truyền phát stream nhị phân dung lượng cực lớn (10MB), xác thực header `Content-Length: 10485760` được bảo toàn nguyên vẹn từ upstream đến client, dữ liệu byte-level khớp tuyệt đối không bị biến dạng.
4. `test_adv_large_payload_streaming_chunked_no_content_length`: Truyền phát stream 5MB không có `Content-Length` theo chuẩn `Transfer-Encoding: chunked`, đảm bảo proxy Hyper stream trơn tru.
5. `test_adv_large_stream_client_abrupt_disconnect_safety`: Client chủ động ngắt kết nối TCP đột ngột sau khi nhận 64KB đầu tiên của luồng 10MB. Xác thực proxy thu hồi tài nguyên an toàn, không panic và tiếp tục phục vụ các kết nối kế tiếp bình thường.
6. `test_adv_websocket_fragmented_handshake_accumulation`: Upstream phân mảnh gói tin phản hồi `101 Switching Protocols` thành từng khối 3 bytes kèm độ trễ, theo sau là frame WebSocket thô ngay lập tức, xác thực bộ tích lũy `read_http_headers` hoạt động chính xác.
7. `test_adv_dns_single_flight_thundering_herd`: 50 luồng đồng thời phân giải cùng một tên miền, xác thực cơ chế single-flight trên `DashMap` và `broadcast::channel` không bị deadlock hay rò rỉ.

## 2. Mục đích & Ý nghĩa
- **Kiểm định Shutdown An toàn**: Đảm bảo khi hệ thống nhận tín hiệu dừng (Ctrl+C hoặc shutdown signal), toàn bộ các bản ghi lưu vết mạng đang nằm trong hàng đợi bộ đệm phải được commit trọn vẹn vào cơ sở dữ liệu PostgreSQL trước khi tiến trình tắt hoàn toàn, ngăn chặn việc thất thoát dữ liệu lưu vết (data loss).
- **Kiểm định Zero-Copy Streaming & Bộ nhớ**: Kiểm chứng rằng Proxify không tải toàn bộ payload lớn (10MB+) vào RAM mà chuyển tiếp trực tiếp bằng `StreamBody` bất đồng bộ, đồng thời không tự ý loại bỏ header `Content-Length` gây lỗi giao thức HTTP/1.1 ở phía client.
- **Khả năng chịu lỗi (Resilience)**: Đảm bảo proxy sống sót trước các sự cố mạng thực tế như client ngắt kết nối giữa chừng, gói tin TCP bị phân mảnh đến từng byte.

## 3. Mối liên hệ
- Liên kết trực tiếp với module lưu trữ `crates/proxify-core/src/storage.rs` (hàm `enqueue`, `flush`, `shutdown`, `flush_batch`).
- Liên kết với data plane `crates/proxify-core/src/proxy.rs` (các hàm `should_stream_response_headers`, `convert_reqwest_to_stream_response`, `read_http_headers`, `Ipv4PreferredDnsResolver`).
- Liên kết với tiến trình host `crates/proxify-server/src/main.rs` (vòng lặp graceful shutdown).
- Tích hợp vào bộ test tổng thể của workspace, được thực thi tự động qua `cargo test --workspace`.

## 4. Rủi ro (Risks & Edge Cases)
- **Hàng đợi channel tràn dung lượng**: `RequestStorage` sử dụng kênh bounded dung lượng 2000 (`mpsc::channel(2000)`). Khi hệ thống chịu tải vượt quá khả năng ghi của DB (> 2000 items chưa flush), phương thức `enqueue` sử dụng `try_send` sẽ bỏ qua (drop) các item vượt ngưỡng. Đây là thiết kế bảo vệ bộ nhớ có chủ đích để tránh OOM trong trường hợp database bị nghẽn, nhưng cần được giám sát qua chỉ số telemetry.
- **Timeout của Shutdown**: Nếu DB phản hồi chậm, thao tác `flush_batch` có thể kéo dài. Trong môi trường production, cần thiết lập timeout hợp lý (ví dụ: 10 giây) để tránh tiến trình bị kẹt vĩnh viễn khi tắt container.
