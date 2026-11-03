# Tài liệu Kiểm thử Đối kháng Milestone 1 (Adversarial Verification Suite)

## 1. Tóm tắt thay đổi
- Bổ sung bộ kiểm thử đối kháng tích hợp chuyên biệt tại `tests/adversarial_m1_tests.rs` và đăng ký target `[[test]] name = "adversarial_m1_tests"` trong `Cargo.toml`.
- Thiết kế và triển khai 8 kịch bản kiểm thử độc lập phủ 4 hướng tấn công và điều kiện biên phức tạp của Milestone 1:
  1. **WebSocket Framing Adversarial Test**: Phân tách ký tự biên `\r\n\r\n` xuyên qua 2 chunk TCP, 3 chunk TCP và từng byte đơn lẻ (1-byte trickle delivery) để thử thách hàm `read_http_headers`. Đồng thời kiểm thử E2E phân mảnh gói tin kèm khung dữ liệu (immediate frame payload) đi liền ngay sau handshake.
  2. **Facebook Passthrough Verification**: Thử nghiệm ma trận 14 tên miền của Facebook đối chiếu với `should_passthrough_tls` đảm bảo không bị bypass, đồng thời kích hoạt luồng E2E TLS MITM interception đối với `FacebookGraphQLObserver` qua `MitmProxyServer`.
  3. **Multi-Value Header Stress**: Gửi 5 header `Set-Cookie` có thuộc tính phức tạp (bao gồm ký tự dấu phẩy `,` trong ngày hết hạn chuẩn RFC 1123 `Expires=Wed, 21 Oct 2026 07:28:00 GMT`), cùng nhiều header trùng tên như `X-Trace-Node`, `Vary`, `Accept` để chứng minh không bị ghi đè hoặc cắt xén dữ liệu.
  4. **DNS Stampede Stress**: Bắn đồng thời 50 tác vụ bất đồng bộ truy vấn phân giải tên miền chưa được lưu cache (`localhost` và UUID domain ngẫu nhiên), cùng bài kiểm tra 100 tác vụ song song trên 5 tên miền khác nhau để kiểm chứng cơ chế deduplication single-flight qua `tokio::sync::broadcast` không sinh ra duplicate queries, race conditions hoặc deadlock.

## 2. Mục đích & Ý nghĩa
- Đảm bảo tính trung thực và khách quan tuyệt đối của quy trình kiểm thử (Empirical Challenger). Không dựa dẫm vào các khẳng định hay log từ worker trước đó.
- Chủ động tìm kiếm các lỗi tiềm ẩn (silent failure modes) trong môi trường mạng thực tế:
  - Hiện tượng phân mảnh TCP (packet segmentation / MTU boundary) làm vỡ định dạng HTTP/1.1 101 Switching Protocols.
  - Xung đột xử lý dấu phẩy của `Set-Cookie` khi gộp header.
  - Thundering herd / stampede làm nghẽn CPU hoặc treo worker thread khi nhiều request cùng phân giải một tên miền mới.
  - Nguy cơ lọt gói tin mã hóa của Facebook do cấu hình whitelist TLS passthrough lỏng lẻo.

## 3. Mối liên hệ
- Liên kết trực tiếp với các module lõi:
  - `crates/proxify-core/src/proxy.rs`: Kiểm chứng logic `read_http_headers`, `find_header_end`, `should_passthrough_tls`, `Ipv4PreferredDnsResolver`, và pipeline xử lý header `Set-Cookie`.
  - `crates/ext-facebook`: Kiểm chứng `FacebookGraphQLObserver` được kích hoạt thực sự khi proxy giải mã TLS HTTPS.
  - `src/test_helpers.rs`: Tái sử dụng `TestProxyServer`, `MockHttpUpstream`, `MockEventBus` và các bộ sinh chứng chỉ test.
  - `Cargo.toml`: Tích hợp bộ test vào workspace test suite.

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro rò rỉ bộ đệm khi phân mảnh (Buffer Leaks & Truncation)**: Nếu buffer tích lũy không ngắt đúng vị trí 4 byte `\r\n\r\n`, phần dữ liệu payload đi kèm ngay sau packet cuối sẽ bị mất hoặc gộp nhầm vào header của HTTP. Bộ test đã xác nhận `leftover` tách biệt hoàn toàn và chính xác từng byte.
- **Rủi ro kênh Broadcast Lagged trong DNS Single-Flight**: Khi có nhiều hơn 50 task đăng ký nhận kết quả phân giải cùng lúc, nếu kênh `broadcast::channel(1)` không kịp đọc có thể dẫn đến `RecvError::Lagged`. Bộ test đã kiểm tra xử lý lỗi `Err` fallback mượt mà và không gây crash.
- **Rủi ro định dạng ngày trong Cookie**: Chuẩn RFC 1123 của `Expires` luôn có dấu phẩy (`Wed, 21 Oct 2026`). Việc một số proxy dùng logic nối chuỗi bằng dấu phẩy thông thường sẽ làm vỡ định dạng cookie này. Việc tách riêng `Set-Cookie` bằng ký tự xuống dòng `\n` đã ngăn ngừa triệt để rủi ro này.
