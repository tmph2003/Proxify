# ⚡ Tối Ưu Hóa Độ Trễ Mạng, HTTP/2 Multiplexing & Loại Bỏ Jitter Trên Rust Core (`proxify-core`)

## 1. Tóm tắt thay đổi
Khắc phục triệt để 5 nguyên nhân gốc rễ gây ra hiện tượng mạng "thi thoảng bị khựng/chậm" (intermittent latency spikes / connection stalls) trên bản viết lại bằng Rust (`proxify-core`, `ext-youtube`, `proxify-server`):

1. **`crates/proxify-core/src/ca.rs` (CA Key Caching & HTTP/2 ALPN)**:
   - Lưu trữ sẵn `ca_key: KeyPair`, `ca_cert: rcgen::Certificate` và một `leaf_key: KeyPair` dùng chung ngay từ lúc khởi tạo `CertificateAuthority::load_or_generate` thay vì parse lại PEM, gọi lại `ca_params.self_signed(&ca_key)` và sinh cặp khóa bất đối xứng mới (`KeyPair::generate()`) trên mỗi domain TLS mới.
   - Bật quảng bá `ALPN = ["h2", "http/1.1"]` trên `rustls::ServerConfig` thay vì ép trình duyệt xuống `http/1.1` (vốn bị giới hạn cứng 6 kết nối/domain gây Head-of-Line blocking).
   - Thay thế cơ chế xóa trắng toàn bộ cache (`leaf_cache.clear()`) khi vượt ngưỡng 2000 bằng cơ chế cắt tỉa từng phần (evict 512 bản ghi khi vượt 4096).

2. **`Cargo.toml`, `crates/proxify-core/src/proxy.rs` & `crates/proxify-core/src/router.rs` (Enable Upstream HTTP/2 Feature, DNS TTL Cache, HTTP/2 Keep-Alive, Zero-Decompression Stream & Offload Blocking Tasks)**:
   - **Phát hiện nghiêm trọng trong `Cargo.toml`**: Do `reqwest` khai báo `default-features = false` nhưng thiếu feature `"http2"`, toàn bộ kết nối từ Proxy lên Upstream trước đó bị ép về **HTTP/1.1 thuần túy**, không có multiplexing và liên tục bị Google/Cloudflare đóng socket nhàn rỗi gây lỗi `error sending request for url`. Đã bổ sung `"http2"` vào `reqwest` features trong `Cargo.toml`.
   - Bổ sung bộ nhớ đệm `DNS_CACHE` (`DashMap` với TTL 60 giây) trong `Ipv4PreferredDnsResolver` và tái sử dụng trực tiếp trong `connect_ipv4_preferred` (giảm timeout mỗi IP từ 8s xuống 3s), triệt tiêu chi phí gọi syscall `getaddrinfo` lặp lại trên từng kết nối.
   - Bổ sung cấu hình HTTP/2 Keep-Alive (`http2_keep_alive_interval(15s)`, `http2_keep_alive_timeout(10s)`, `http2_keep_alive_while_idle(true)`, `http2_adaptive_window(true)`) và request timeout (`30s`) cho `reqwest::Client`, khắc phục lỗi `Upstream send retry (attempt 1): error sending request for url` khi kết nối HTTP/2 nhàn rỗi bị phía Google/Cloudflare đóng ngầm.
   - Tách riêng `stream_client` với `.no_gzip().no_brotli().no_deflate()` để truyền thẳng (zero-decompression passthrough) các luồng tĩnh (`.js`, `.css`, font, ảnh, video chunk, telemetry) giữ nguyên `Content-Encoding` và `Content-Length` gốc.
   - Hiện thực hóa `ProxyRouter::should_stream(&host)` và kết nối với `IGNORE_HOSTS` để các domain trong `stream_rules` thực sự đi qua đường truyền stream thay vì bị buffer toàn bộ vào RAM.
   - Loại bỏ toàn bộ các hop-by-hop headers cấm trong HTTP/2 (`keep-alive`, `proxy-connection`, `transfer-encoding`, `upgrade`, `http2-settings`, `te`, `connection`, `alt-svc`).
   - Đẩy tác vụ giải nén payload lớn (`> 32KB`) sang `tokio::task::spawn_blocking` và loại bỏ việc nhân bản (`clone()`) `FlowResponse.content` tới 3 lần khi không có Observer hoặc khi domain không nằm trong diện lưu DB.

3. **`crates/ext-youtube/src/lib.rs` & `crates/ext-youtube/Cargo.toml` (Non-Blocking Mutation & Telemetry Bypass)**:
   - Bổ sung dependency `tokio.workspace = true` cho `ext-youtube`.
   - Bỏ qua việc parse JSON vô ích trên các gói tin telemetry/nhịp tim (`/youtubei/v1/log_event`, `/feedback`, `/updated_metadata`, `/live_chat/`, `/notification/`).
   - Đẩy quá trình bóc tách quảng cáo JSON/HTML (`strip_youtube_ads`, `inject_youtube_anti_afk_with_nonce`) với payload lớn sang `tokio::task::spawn_blocking` để không bao giờ khóa luồng I/O của Tokio.

4. **`crates/proxify-core/src/storage.rs`, `eventbus.rs`, `dashboard.rs` & `backend/chrome_extension/popup.js` (Transactional Batching, Vacuum Bloat & Chrome Extension Sync)**:
   - Gom nhóm toàn bộ lệnh `INSERT` trong `flush_batch` của `RequestStorage` và `AsyncEventBus` vào một `Transaction` duy nhất (1 lần `fsync` WAL thay vì 50 lần autocommit rời rạc).
   - Chuyển `delete_requests(None)` từ `DELETE FROM public.requests` sang `TRUNCATE TABLE public.requests RESTART IDENTITY` và chạy `VACUUM FULL` giải phóng **6,023 MB (6 GB)** dung lượng bảng chết (giúp truy vấn `get_stats` giảm từ **989 ms** xuống **0.68 ms**).
   - Đồng bộ hóa trường `db_integration_enabled` và `db_allowed_domains` giữa `dashboard.rs` và `popup.js`.

## 2. Mục đích & Ý nghĩa
- **Loại bỏ hiện tượng nghẽn cổ chai 6 kết nối (HTTP/1.1 Downgrade) và chết kết nối ngầm HTTP/2**: Trình duyệt có thể ghép kênh (multiplex) hàng trăm request qua một kết nối TLS duy nhất tới Proxy, đồng thời kết nối từ Proxy lên Upstream luôn được giữ sống bằng H2 PING frame.
- **Bảo vệ tuyệt đối Tokio Async I/O Workers**: Không còn bất kỳ tác vụ CPU-bound nào (sinh khóa RSA/ECDSA, giải nén Brotli/Gzip hàng MB, chạy Regex trên HTML 3MB của YouTube) chạy trực tiếp trên luồng sự kiện mạng.
- **Ngăn chặn phình đại ổ cứng và nghẽn I/O PostgreSQL**: Khôi phục cơ chế lọc domain (`allowed_domains`) và trạng thái bật/tắt DB trên Chrome Extension.

## 3. Mối liên hệ
- Tác động trực tiếp tới tầng lõi `crates/proxify-core` (`ca.rs`, `proxy.rs`, `router.rs`, `storage.rs`, `eventbus.rs`, `dashboard.rs`), extension `crates/ext-youtube/src/lib.rs`, `crates/proxify-server/src/main.rs` và tiện ích `backend/chrome_extension/popup.js`.

## 4. Rủi ro (Risks & Edge Cases)
- **Tương thích HTTP/2 Header**: HTTP/2 yêu cầu nghiêm ngặt không có các connection-specific headers (`Keep-Alive`, `Transfer-Encoding`, `Connection`, `Upgrade`). Các bộ lọc header trong `handle_http_request` và `convert_reqwest_to_stream_response` đã được bổ sung đầy đủ để đảm bảo không phát sinh lỗi `ERR_HTTP2_PROTOCOL_ERROR`.
- **DNS Cache TTL (60s)**: Với các domain đổi IP động dưới 60 giây, cache sẽ giữ IP cũ tối đa 60 giây; tuy nhiên cơ chế retry kết nối sẽ tự động thử các IP tiếp theo trong danh sách đã phân giải.
