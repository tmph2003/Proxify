# Tài liệu Công cụ: Cập nhật Macro Benchmark Harness (`benchmark_proxy.py`)

## Tóm tắt thay đổi
Cập nhật script benchmark tải vĩ mô `scripts/benchmark_proxy.py`:
1. Mở rộng cấu hình mock server: bind trên `0.0.0.0` thay vì chỉ `127.0.0.1`, chuyển đổi từ `socketserver.TCPServer` đơn luồng sang `ThreadedTCPServer` đa luồng (`daemon_threads=True`, `request_queue_size=256`, `allow_reuse_address=True`) cho phép kết nối song song tải cao mà không bị nghẽn socket backlog.
2. Thêm tham số `--mock-host` (mặc định `host.docker.internal`), cho phép proxy trong container định tuyến chính xác đến mock upstream chạy trên host machine.
3. Tích hợp khả năng đo đạc bộ nhớ thực tế của tiến trình container thông qua `docker stats proxify_app` tự động, ghi nhận chính xác Memory Footprint trước và sau đợt chạy tải.

## Mục đích & Ý nghĩa
- Cho phép thực thi macro load test thực tế 100% trong môi trường containerized Docker mà không gặp lỗi `502 Bad Gateway` do sai khác network boundary (localhost isolation).
- Cung cấp số liệu chính xác về QPS (Queries Per Second), phân phối độ trễ (p50, p90, p95, p99), tỉ lệ thành công (Success Rate), và mức tiêu thụ RAM thực tế của Proxify v2.0 dưới tải cao.

## Mối liên hệ
- Tương thích trực tiếp với container `proxify_app` trong `docker-compose.yml`.
- Dữ liệu đầu ra JSON (`scripts/benchmark_results.json`) được dùng để tổng hợp báo cáo hiệu năng tại `docs/performance/final_benchmark_report.md`.

## Rủi ro (Risks & Edge Cases)
- **Tường lửa (Windows Defender Firewall)**: Khi Python bind port ephemeral trên `0.0.0.0`, Windows có thể hiển thị cảnh báo tường lửa nếu port bị chặn. `host.docker.internal` yêu cầu Docker Desktop DNS resolution hoạt động bình thường.
- **Connection Limits**: Chạy với concurrency quá cao trên máy trạm Windows có thể chạm giới hạn ephemeral socket ports (`TIME_WAIT`). Mức khuyến nghị tiêu chuẩn là 20-50 worker threads.
