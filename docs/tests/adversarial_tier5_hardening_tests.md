# Tài Liệu Kỹ Thuật: Bộ Kiểm Thử Tier 5 Phản Biện Chuyên Sâu (Tier 5 Adversarial Coverage Hardening Test Suite)

## 1. Tóm Tắt Thay Đổi
Tạo mới file kiểm thử tích hợp phản biện hộp trắng (white-box adversarial stress test suite) tại `tests/adversarial_tier5_hardening_tests.rs` và đăng ký target kiểm thử trong `Cargo.toml`.

Bộ test bao gồm 10 kịch bản kiểm thử tải nặng, áp lực tranh chấp đa luồng và các trạng thái mạng bất thường:
1. **`test_tier5_adv_cert_gen_100_concurrent_distinct_domains`**: Kiểm thử phát sinh chứng chỉ TLS động đồng thời cho 100 domain khác nhau với 100 tác vụ Tokio song song.
2. **`test_tier5_adv_cert_gen_100_concurrent_thundering_herd`**: Kiểm thử hiện tượng dồn sóng (thundering herd) khi 100 tác vụ cùng yêu cầu một domain chưa lưu cache tại cùng một thời điểm, kiểm tra tính duy nhất qua `Arc::ptr_eq`.
3. **`test_tier5_adv_cert_lru_cache_bounded_4096_eviction_and_renewal`**: Kiểm thử giới hạn kích thước LRU cache nghiêm ngặt ở ngưỡng 4096 mục, tự động loại bỏ (evict) 512 mục cũ nhất khi vượt ngưỡng và bảo toàn các mục vừa được truy cập lại (access counter renewal).
4. **`test_tier5_adv_single_flight_cancellation_and_channel_cleanup`**: Kiểm thử hủy tác vụ (task abortion / cancellation) giữa chừng đối với các tác vụ Single-Flight leader trong CA và DNS, đảm bảo RAII Drop Guard dọn dẹp sạch sẽ kênh broadcast mà không làm nghẽn hoặc rò rỉ tài nguyên.
5. **`test_tier5_adv_storage_high_load_batch_overflow_and_backpressure`**: Kiểm thử áp lực ghi cơ sở dữ liệu với 5.000 bản ghi gửi vào kênh hàng đợi giới hạn 2.000 phần tử, xác minh cơ chế áp lực ngược (backpressure) qua `try_send`, cắt gọt payload vượt kích thước zero-copy (`max_body_size`) và xả hàng đợi (`flush`) an toàn.
6. **`test_tier5_adv_half_closed_http11_client_write_shutdown`**: Kiểm thử kết nối HTTP/1.1 nửa đóng (Half-Closed TCP connection), khi client hoàn tất gửi request kèm `Content-Length: 0` và đóng chiều ghi (`shutdown(Write)` / gửi TCP FIN) nhưng vẫn mở chiều đọc để nhận response từ proxy.
7. **`test_tier5_adv_malformed_headers_and_bad_requests`**: Kiểm thử khả năng chống chịu các header dị dạng (thiếu dấu hai chấm `:`, byte nhị phân rác, phiên bản HTTP sai, bảo vệ ngập header với mã chuẩn RFC 6585 `431 Request Header Fields Too Large`) mà không làm sập proxy.
8. **`test_tier5_adv_abrupt_client_rst_and_slowloris`**: Kiểm thử ngắt kết nối đột ngột (TCP RST / drop socket) và tấn công Slowloris truyền chậm giọt từng byte, đảm bảo các kết nối bình thường khác không bị nghẽn (starvation).
9. **`test_tier5_adv_stealth_circuit_breaker_concurrency_stress`**: Kiểm thử máy trạng thái `CrawlCircuitBreaker` dưới áp lực 50 luồng đồng thời gọi các hàm ghi nhận lỗi/thành công/cho phép request.
10. **`test_tier5_adv_router_radix_trie_adversarial_matrix`**: Kiểm thử định tuyến Radix-Trie với ma trận domain phức tạp, tiền chuẩn hóa quy tắc stream, đường dẫn stream và quy tắc loại trừ stream (`should_stream_request`, `is_stream_excluded`).

---

## 2. Mục Đích & Ý Nghĩa
- **Giải quyết bài toán kiểm thử sức chịu đựng cực hạn (Adversarial Stress Testing)**: Trong môi trường sản xuất thực tế, hệ thống proxy mạng không chỉ nhận các yêu cầu HTTP chuẩn mực mà liên tục đối mặt với bão kết nối (concurrency spikes), ngắt kết nối bất thường từ client, dữ liệu gói tin bị phân mảnh hoặc cố ý làm sai lệch để tấn công DoS/hang threads.
- **Chứng minh tính đúng đắn theo thời gian thực (Zero Memory Leaks & Bound Invariants)**: Xác minh bằng thực nghiệm rằng bộ nhớ cache không tăng vô hạn (unbounded growth), kênh truyền thông single-flight không rò rỉ bộ nhớ khi hủy tương tác, và luồng sự kiện không xảy ra deadlock.

---

## 3. Mối Liên Hệ
- **`crates/proxify-core/src/ca.rs`**: Kiểm thử toàn diện `CertificateAuthority`, giải thuật LRU cache với `AtomicU64`, và cơ chế Single-Flight qua `broadcast::channel`.
- **`crates/proxify-core/src/storage.rs`**: Kiểm thử `RequestStorage`, hàng đợi `mpsc::channel(2000)`, và hàm `flush`/`shutdown`.
- **`crates/proxify-core/src/proxy.rs`**: Kiểm thử `MitmProxyServer`, `Ipv4PreferredDnsResolver`, và engine xử lý HTTP/1.1 thông qua `hyper_util`.
- **`crates/proxify-core/src/stealth.rs`**: Kiểm thử bộ ngắt mạch bảo vệ chống crawl `CrawlCircuitBreaker`.
- **`crates/proxify-core/src/router.rs`**: Kiểm thử engine tiền chuẩn hóa tiền tố/hậu tố domain `ProxyRouter`.
- **`src/test_helpers.rs`**: Sử dụng harness `TestProxyServer`, `MockHttpUpstream`, `send_raw_proxy_request`.

---

## 4. Rủi Ro (Risks & Edge Cases)
- **Cạn kiệt tài nguyên hệ điều hành (File Descriptor exhaustion)**: Khi mở 100 kết nối TCP hoặc 100 tác vụ đồng thời, nếu hệ điều hành hoặc container giới hạn ulimit thấp, có thể gây lỗi `Too many open files`. Giải pháp là các bài test sử dụng port cục bộ ephemeral và tự động đóng stream khi xong.
- **Thời gian chờ (Timeout) trong môi trường CI/Container**: Việc sinh 4.000+ chứng chỉ x509 tiêu tốn CPU đáng kể. Bộ test tối ưu hóa bằng cách kết hợp gọi trực tiếp `server_config_for_host_async` với các tác vụ đa luồng để hoàn thành trong vài giây.
- **Khả năng xung đột trạng thái dùng chung (Shared Global State)**: `DNS_CACHE` là biến tĩnh Lazy, các bài test sử dụng IP trực tiếp `127.0.0.1` để tránh phụ thuộc vào DNS upstream.
