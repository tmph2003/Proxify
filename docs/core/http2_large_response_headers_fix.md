# Khắc phục lỗi HTTP 502 (HTTP/2 `SETTINGS_MAX_HEADER_LIST_SIZE`) khi truy cập YouTube & CDN hiện đại trên Chrome 156+

## 1. Tóm tắt thay đổi
- **`crates/proxify-core/src/proxy.rs`**:
  - Khai báo hằng số [`HTTP2_MAX_HEADER_LIST_SIZE`](../../crates/proxify-core/src/proxy.rs) = `262_144` bytes (**256 KiB**, đồng bộ với chuẩn `SETTINGS_MAX_HEADER_LIST_SIZE` mặc định của nhân trình duyệt Chromium/Chrome).
  - Cấu hình `.http2_max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE)` cho cả hai HTTP client kết nối ra ngoài (`upstream_client` phục vụ luồng MITM giải mã/ghi log và `stream_client` phục vụ luồng zero-copy streaming).
  - Cấu hình `conn_builder.http2().max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE)` cho cả hai chiều nhận kết nối từ trình duyệt (`MitmProxyServer::run` và hầm TLS MITM trong `MitmProxyServer::handle_connect`).
  - Bổ sung hàm [`MitmProxyServer::format_reqwest_error`](../../crates/proxify-core/src/proxy.rs) duyệt toàn bộ chuỗi nguyên nhân gốc (`std::error::Error::source`) thay vì chỉ gọi `e.to_string()`, giúp hiển thị rõ lỗi tầng `hyper` / `h2` / `rustls` khi xảy ra sự cố kết nối upstream.
- **`crates/proxify-core/src/stealth.rs`**:
  - Áp dụng `.http2_max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE)` và `.http2_adaptive_window(true)` cho HTTP client của [`StealthSessionManager`](../../crates/proxify-core/src/stealth.rs).
- **`tests/e2e_proxy_tests.rs`**:
  - Bổ sung integration test [`test_tier2_http2_large_response_headers_exceeding_16kib_default`](../../tests/e2e_proxy_tests.rs) dựng máy chủ TLS + ALPN `h2` trả về bộ response headers > 26 KiB (`connection-allowlist-report-only`, `permissions-policy`, `reporting-endpoints`), kiểm chứng cả luồng MITM buffered lẫn luồng `.js` streaming đều trả về `200 OK` và bảo toàn đầy đủ header.

## 2. Mục đích & Ý nghĩa
- **Giải quyết triệt để lỗi `Proxify Upstream Error: error sending request for url (https://www.youtube.com/)` (HTTP 502)**:
  - Khi trình duyệt Chrome hiện đại (ví dụ Chrome 156) gửi `User-Agent` lên `https://www.youtube.com/`, hệ thống biên Google `ESF` trả về khối response headers nặng khoảng **19,308 bytes** (~19.3 KB), do đính kèm các header bảo mật thử nghiệm thế hệ mới của Chromium như `connection-allowlist-report-only` (~12+ KB), `permissions-policy`, `reporting-endpoints`, `report-to`, và `content-security-policy`.
  - Crate `h2` (được `hyper` và `reqwest` sử dụng bên dưới) đặt giới hạn mặc định `SETTINGS_MAX_HEADER_LIST_SIZE` chỉ ở mức **16,384 bytes (16 KiB)** theo giá trị tối thiểu bảo thủ, trong khi Chromium thực tế quảng bá giới hạn **256 KiB**. Sự lệch pha cấu hình giao thức này khiến `h2` lập tức hủy stream HTTP/2 khi nhận response 19.3 KB từ YouTube và ném lỗi `error sending request for url (...)`.
  - Việc nâng giới hạn `SETTINGS_MAX_HEADER_LIST_SIZE` lên **256 KiB** giúp tầng Infrastructure (Transport/Proxy Data Plane) tương thích hoàn toàn với hành vi của Chrome thật, loại bỏ cả lỗi 502 lẫn nguy cơ bị nhận diện bất thường qua HTTP/2 SETTINGS frame fingerprint.
- **Tăng khả năng quan sát lỗi tầng Transport (Observability)**:
  - Trước đây `reqwest::Error::to_string()` che khuất chuỗi `source()` bên dưới khiến việc chẩn đoán lỗi `h2` hay TLS alert rất khó khăn. Chuỗi lỗi đầy đủ nay được ghi nhận rõ trong log `warn!` và thông điệp `502`.

## 3. Mối liên hệ
- **`crates/proxify-core/src/proxy.rs`** ↔ **`crates/proxify-core/src/stealth.rs`**: Dùng chung hằng số `HTTP2_MAX_HEADER_LIST_SIZE` để đảm bảo cả lưu lượng trình duyệt đi qua MITM Proxy lẫn các request chủ động từ Stealth Crawler (Facebook, Zalo, YouTube extractor) đều không bị ngắt kết nối khi máy chủ đích trả header lớn.
- **`crates/proxify-core/src/ca.rs`**: Cấu hình chứng chỉ lá MITM (`alpn_protocols = ["http/1.1", "h2"]`) phối hợp trực tiếp với `hyper_util::server::conn::auto::Builder` trong `proxy.rs`.
- **`tests/e2e_proxy_tests.rs`**: Kiểm thử hộp đen (opaque-box) toàn trình từ HTTP Client -> MITM Proxy -> TLS/ALPN `h2` Upstream.

## 4. Rủi ro (Risks & Edge Cases)
- **Tiêu thụ bộ nhớ trên mỗi HTTP/2 stream (Memory Amplification / HPACK Bomb)**:
  - Cho phép danh sách header tối đa 256 KiB mỗi stream đồng nghĩa một máy chủ độc hại hoặc client gửi song song hàng nghìn stream với header 256 KiB có thể làm tăng lượng RAM cấp phát tạm thời. Tuy nhiên, Proxify là local/controlled MITM debugging proxy và mức 256 KiB khớp chính xác với giới hạn an toàn mặc định của Chromium; ngoài ra `h2` vẫn giới hạn chặt kích thước bảng nén động HPACK (`HEADER_TABLE_SIZE` mặc định 4 KiB).
- **Giới hạn ở các reverse proxy trung gian khác**:
  - Nếu người dùng đặt thêm một lớp Nginx hoặc Envoy phía trước/sau Proxify với `large_client_header_buffers` mặc định (8–16 KiB), lớp ngoài đó vẫn có thể từ chối header > 16 KiB dù Proxify đã xử lý thành công.
- **Thông tin chi tiết trong thông báo lỗi 502**:
  - Việc nối chuỗi `Error::source()` vào nội dung phản hồi `502 Bad Gateway` rất hữu ích cho công cụ local MITM proxy như Proxify, nhưng nếu triển khai làm public gateway đa người dùng thì chỉ nên hiển thị chi tiết lỗi nội bộ ở log server thay vì trả về trình duyệt.
