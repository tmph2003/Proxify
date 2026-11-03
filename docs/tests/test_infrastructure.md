# Kiến Trúc Hạ Tầng Kiểm Thử & Benchmark (Test Infrastructure & Benchmark Suite)

## 1. Tóm tắt thay đổi (Summary of Changes)
- **Thiết kế và cài đặt bộ kiểm thử tích hợp 4-Tier Opaque-Box**:
  - `tests/e2e_proxy_tests.rs`: Bao gồm 14 ca kiểm thử cho Tier 1 (chuyển tiếp HTTP/1.1 cơ bản, GET/POST, URL preservation, status codes, keep-alive, streaming fastpath, stream rules) và Tier 2 (TLS MITM CONNECT, đa giá trị `Set-Cookie`, chunked transfer, large payload 2MB, giải nén gzip, xử lý lỗi 502, TLS passthrough).
  - `tests/e2e_websocket_tests.rs`: Bao gồm 5 ca kiểm thử cho Tier 3 (nâng cấp giao thức HTTP/1.1 101 Switching Protocols, chuyển tiếp hai chiều frame payload, streaming nhiều frame liên tục, phân mảnh gói tin 101 handshake, đóng kết nối an toàn).
  - `tests/e2e_extension_tests.rs`: Bao gồm 7 ca kiểm thử cho Tier 4 (chặn quảng cáo YouTube trả về 204 No Content, gỡ bỏ quảng cáo JSON Innertube, tiêm script anti-AFK với CSP nonce, lọc ghi log video, quan sát GraphQL Facebook gửi event bus, định tuyến Radix-Trie nhiều cấp độ, chuỗi mutator tùy biến).
- **Thiết kế và cài đặt bộ Benchmark Suite**:
  - `benches/proxy_micro_benches.rs`: Benchmark micro mức nanosecond bằng Criterion cho tra cứu `ProxyRouter`, chuyển đổi `HeaderMap`, và bộ nhớ đệm `CertificateAuthority` leaf cert cache.
  - `scripts/benchmark_proxy.py`: Script đo tải macro đo đạc thông lượng QPS, phân vị độ trễ (p50, p90, p95, p99), tỷ lệ lỗi và bộ nhớ RAM.
  - `scripts/bench.sh`: Shell script thực thi tự động cả micro và macro benchmarks.
- **Tiện ích dùng chung và cấu hình Workspace**:
  - `src/lib.rs` & `src/test_helpers.rs`: Cung cấp mock upstream HTTP/TLS/WebSocket server trên cổng ngẫu nhiên (`127.0.0.1:0`), mock event bus, và client gửi raw proxy request.
  - Cập nhật `Cargo.toml`: Thêm `[package]` root, các target `[[test]]`, `[[bench]]`, và dependency `criterion`.
  - Khởi tạo `TEST_INFRA.md` và `TEST_READY.md` tại thư mục gốc.

---

## 2. Mục đích & Ý nghĩa (Purpose & Significance)
- **Đảm bảo tính đúng đắn tuyệt đối (Correctness & Reliability)**: Kiểm tra hệ thống proxy dưới dạng "hộp đen" (opaque-box), giả lập hành vi thực tế của client và upstream server mà không can thiệp vào mã nội bộ.
- **Phát hiện sớm lỗi hồi quy (Zero Regressions)**: Đảm bảo các giai đoạn tối ưu hóa hiệu năng (M2: Zero-Copy, Async Signing) và tái cấu trúc mã (M3: Decoupling) không làm thay đổi hay phá vỡ các đặc tả giao thức mạng RFC chuẩn (RFC 7230, RFC 2817, RFC 6455).
- **Đo lường định lượng trước và sau tối ưu (Performance Verification)**: Cung cấp công cụ đo đạc chính xác cả mức vi mô (Criterion cho các hàm cốt lõi) và mức vĩ mô (tải đồng thời nhiều luồng) nhằm chứng minh hiệu quả tối ưu hoá hiệu năng.
- **Tự trị và cách ly (Self-Contained & Isolated)**: Các bài kiểm thử sử dụng cổng mạng ngẫu nhiên và ngắt kết nối cơ sở dữ liệu bên ngoài (`set_saving(false)`), giúp bộ test chạy siêu nhanh, không bị ảnh hưởng bởi môi trường bên ngoài và hoàn toàn tin cậy trong môi trường CI/CD hoặc Docker container.

---

## 3. Mối liên hệ (Module Interactions & Dependencies)
- **`proxify-core`**:
  - `proxy.rs`: Kiểm thử trực tiếp `MitmProxyServer`, xử lý CONNECT, phân tích URL, streaming fast-path và kết nối upstream.
  - `ca.rs`: Kiểm thử dynamic leaf certificate signing và đo đạc hiệu năng cache hit/miss trong Criterion.
  - `router.rs`: Kiểm thử thuật toán Radix-Trie tra cứu quan sát viên (observers), bộ đột biến (mutators), và quy tắc stream rules.
  - `storage.rs`: Tích hợp với `RequestStorage` ở chế độ decoupled để tránh phụ thuộc PostgreSQL thật khi chạy unit/e2e tests.
- **`proxify-sdk`**:
  - Sử dụng các cấu trúc `FlowRequest`, `FlowResponse`, `HttpFlow` và các trait `ObserverInterceptor`, `MutatorInterceptor`, `RecordFilter`, `EventPublisher`.
- **Extension Crates**:
  - `ext-youtube`: Kiểm thử `YouTubePlugin`, `YouTubeRecordFilter`, làm sạch JSON Innertube và tiêm script Anti-AFK.
  - `ext-facebook`: Kiểm thử `FacebookGraphQLObserver` và xuất bản sự kiện sang event bus.
  - `ext-zalo`: Kiểm thử stream rules (`*.zadn.vn`) và bộ đột biến hook Zalo.
- **Hạ tầng thực thi**:
  - Liên kết với `Cargo.toml` root manifest, cho phép chạy trực tiếp qua `cargo test --test ...` hoặc bên trong container Docker `rust:slim-bookworm`.

---

## 4. Rủi ro & Trường hợp biên (Risks & Edge Cases)
- **Xung đột cổng khi chạy song song**: Mọi mock server đều bind cổng `127.0.0.1:0` (ephemeral port do OS cấp phát), triệt tiêu hoàn toàn rủi ro xung đột cổng khi chạy test song song đa luồng.
- **Phân mảnh gói tin TCP (Segmented Handshake)**: Đã thiết kế riêng ca kiểm thử `test_tier3_websocket_segmented_101_handshake` gửi status line và header cách nhau 30ms để phát hiện và ngăn chặn nguy cơ socket bị treo nếu buffer không tích lũy đủ `\r\n\r\n`.
- **Ghi đè nhiều header Set-Cookie**: Kiểm thử rõ ràng trường hợp upstream trả về nhiều dòng `Set-Cookie`, đảm bảo không bị `HashMap` ghi đè thành 1 cookie duy nhất.
- **Rò rỉ tài nguyên (Socket / Memory Leaks)**: Các ca kiểm thử đóng kết nối (half-close, shutdown) đảm bảo Tokio task không bị treo vĩnh viễn trong vòng lặp `accept()`.
- **Lỗi biên dịch phụ thuộc (Defect Escalation)**: Trong quá trình kiểm tra workspace, đã phát hiện lỗi cú pháp trong `crates/proxify-core/src/router.rs` (khai báo `pub type ResolvedInterceptors` bên trong khối `impl ProxyRouter`), đã lập tức ghi nhận và báo cáo lên Orchestrator để nhánh implementer xử lý.
