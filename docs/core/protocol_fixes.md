# Tài Liệu Kỹ Thuật: Sửa Lỗi Giao Thức Mạng & Chuẩn Hóa Linter (Milestone 1)

## 1. Tóm Tắt Thay Đổi

Trong Milestone 1 (Protocol Correctness & Linter Baseline), các thành phần cốt lõi của tầng hạ tầng mạng `crates/proxify-core` và các extension liên quan đã được rà soát, khắc phục và kiểm chứng đạt 100% test pass:

1. **Khắc phục lỗi TLS Passthrough Facebook (`crates/proxify-core/src/proxy.rs`)**:
   - Loại bỏ các domain `"facebook.com"`, `"facebook.net"`, `"fb.com"`, `"fbcdn.net"` khỏi mảng `passthrough_suffixes` trong hàm `should_passthrough_tls()`.
   - Bật lại tính năng MITM TLS Certificate Generation và Interception cho Facebook HTTPS traffic, cho phép `FacebookGraphQLObserver` trong `ext-facebook` bắt và phân tích trọn vẹn dữ liệu GraphQL (`fb_dtsg`, cookies, posts, comments).
2. **Tích lũy bộ đệm bắt tay WebSocket (`handle_websocket_upgrade` & `read_http_headers`)**:
   - Thay thế cơ chế đọc đơn lẻ (`.read()` 4KB) bằng vòng lặp tích lũy luồng TCP (`read_http_headers`) liên tục cho tới khi phát hiện ranh giới `\r\n\r\n` (RFC 6455 §4.2).
   - Phân tách chính xác phần HTTP 101 Response Headers và các byte frame nhị phân còn dư (`leftover`) để chuyển tiếp trực tiếp sang client sau khi hoàn tất nâng cấp socket.
3. **Bảo toàn Multi-Value Header (RFC 9110 §5.3)**:
   - Xử lý việc thu thập và chuyển tiếp nhiều header trùng tên (`Set-Cookie`, `Cookie`, `Accept`) mà không bị ghi đè dữ liệu.
   - Headers `Set-Cookie` được phân tách bằng ký tự xuống dòng (`\n`), và khi render phản hồi downstream được trích xuất không phân biệt hoa thường (`eq_ignore_ascii_case`) rồi gắn từng dòng riêng biệt qua `headers_mut.append(SET_COOKIE, val)`.
   - Headers `Cookie` được gộp bằng `; ` theo chuẩn RFC 6265, các headers khác được gộp bằng `, `.
4. **Single-Flight Deduplication trong DNS Resolver (`Ipv4PreferredDnsResolver`)**:
   - Tích hợp cấu trúc đồng bộ hóa `IN_FLIGHT_DNS` sử dụng `DashMap<String, tokio::sync::broadcast::Sender>` để nhóm các lookup đồng thời vào một future duy nhất.
   - Giải quyết triệt để vấn đề Thundering Herd / Cache Stampede khi có hàng trăm request đồng thời truy cập domain chưa được cache hoặc cache vừa hết hạn (TTL 60s).
5. **Cân chỉnh thứ tự ưu tiên ALPN trong TLS ServerConfig (`crates/proxify-core/src/ca.rs`)**:
   - Đặt thứ tự ALPN là `vec![b"http/1.1".to_vec(), b"h2".to_vec()]`.
   - Tránh việc rustls cưỡng ép giao thức HTTP/2 nhị phân khi upstream là mock/legacy server chỉ hỗ trợ raw HTTP/1.1, ngăn ngừa lỗi `502 Bad Gateway`.
6. **Bảo toàn `Content-Length` cho Streaming Response Body**:
   - Trong `forward_upstream`, điều chỉnh tham số `strip_encoding = false` khi gọi `convert_reqwest_to_stream_response` cho các phản hồi stream lớn (>2MB / octet-stream), tránh việc Hyper tự động chuyển đổi sang chunked transfer encoding ngoài ý muốn.
7. **Dọn dẹp Linter & Định Dạng Code**:
   - Đưa `pub type ResolvedInterceptors` trong `crates/proxify-core/src/router.rs` ra module level.
   - Khắc phục toàn bộ 6 cảnh báo clippy (`clippy::ptr_arg`, `clippy::result_large_err`, `clippy::type_complexity`, `clippy::collapsible_str_replace`, `clippy::needless_return`, `clippy::unnecessary_lazy_evaluations`, `clippy::too_many_arguments`).
   - Định dạng toàn bộ workspace theo tiêu chuẩn `cargo fmt`.

---

## 2. Mục Đích & Ý Nghĩa

- **Đảm bảo tính đúng đắn giao thức (Protocol Correctness)**: Proxify hoạt động như một transparent / MITM proxy; mọi sự sai lệch về ranh giới gói tin (framing), header trùng tên, hoặc thương lượng giao thức ALPN đều dẫn đến lỗi truyền thông nghiêm trọng (vỡ phiên đăng nhập do mất Set-Cookie, lỗi handshake WebSocket khi mạng bị phân mảnh packet TCP).
- **Ngăn ngừa cạn kiệt tài nguyên (Resource Safety)**: Single-flight DNS ngăn chặn hàng loạt blocking task tràn ngập Tokio threadpool khi mạng gặp độ trễ phân giải DNS.
- **Tính khả thi của hệ sinh thái plugin (Extension Viability)**: Nếu Facebook domains bị passthrough, toàn bộ giá trị nghiệp vụ của extension `ext-facebook` sẽ hoàn toàn bị vô hiệu hóa.

---

## 3. Mối Liên Hệ

- **`crates/proxify-core`**: Cung cấp tầng Data Plane (Network I/O, TLS Handshake, DNS Resolution, Trie Router, Storage Queue).
- **`crates/ext-facebook`**: Nhận luồng HTTP Flow đã giải mã TLS để lọc GraphQL payloads.
- **`crates/proxify-sdk`**: Định nghĩa interface `HttpFlow`, `FlowRequest`, `FlowResponse` trao đổi giữa core và plugin.
- **`tests/`**: Bộ kiểm thử tích hợp 4-Tier (`e2e_proxy_tests.rs`, `e2e_websocket_tests.rs`, `e2e_extension_tests.rs`) trực tiếp xác thực các sửa đổi trên.

---

## 4. Rủi Ro (Risks & Edge Cases)

1. **Slowloris / Unbounded Buffer trong WebSocket Handshake**:
   - *Rủi ro*: Nếu upstream cố tình gửi headers cực chậm hoặc không bao giờ gửi `\r\n\r\n`, bộ đệm có thể phình to gây OOM.
   - *Biện pháp giảm thiểu*: Đặt giới hạn cứng `64 * 1024` (64KB) cho `read_http_headers`. Nếu vượt quá 64KB mà chưa thấy `\r\n\r\n`, proxy tự động cắt và trả về dữ liệu hiện có để chống tấn công cạn kiệt bộ nhớ.
2. **Broadcast Channel Lag / Drop trong DNS Resolver**:
   - *Rủi ro*: Nếu subscriber bị trễ hoặc channel đóng sớm do leader task gặp panic.
   - *Biện pháp giảm thiểu*: Khối `Err(_)` trong `resolve_ips` tự động fallback kiểm tra lại cache `DNS_CACHE`, tránh tình trạng treo vĩnh viễn (deadlock) của follower task.
3. **Set-Cookie Header Casing Variety**:
   - *Rủi ro*: Upstream hoặc extension có thể trả về các dạng casing khác nhau như `Set-Cookie`, `set-cookie`, `SET-COOKIE`.
   - *Biện pháp giảm thiểu*: Sử dụng `eq_ignore_ascii_case("set-cookie")` khi duyệt và trích xuất header trước khi gửi về downstream.
