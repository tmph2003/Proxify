# Tài liệu Kiểm thử Đối kháng Milestone 3 (Adversarial M3 Tests)

## Tóm tắt thay đổi
Tạo bộ kiểm thử đối kháng `tests/adversarial_m3_tests.rs` và đăng ký target kiểm thử vào `Cargo.toml`. Bộ kiểm thử này được thiết kế chuyên biệt để stress-test các cơ chế mới của Milestone 3 bao gồm:
1. Dynamic Stream Path Rules & Stream Exclusion (`ProxyRouter`).
2. Tương tác giữa Stream Exclusion và pipeline mutator đối với Zalo `trusted-device-bridge.js`.
3. Kiểm thử ma trận độ bao phủ toàn diện 18 YouTube path rules trên các domain chính và subdomain wildcard.
4. Stress-test khả năng phân giải alias GraphQL đa luồng (concurrent queries) và đăng ký alias động đồng thời.
5. Ma trận kiểm thử phân biệt hoa thường và host kèm port trong stream exclusion.

## Mục đích & Ý nghĩa
- Đảm bảo việc tách biệt vendor logic khỏi core không gây ra bất kỳ lỗ hổng bảo mật, lỗi bỏ sót (bypass), hay tranh chấp dữ liệu (race conditions).
- Kiểm chứng thực nghiệm (empirical verification) giả định của Worker: liệu Zalo `trusted-device-bridge.js` sau khi được loại trừ khỏi stream có thực sự được chuyển giao nguyên vẹn cho Response Mutator xử lý hay bị cơ chế downstream `forward_upstream` stream trực tiếp bỏ qua mutator.
- Kiểm tra tính đúng đắn của 18 YouTube path rules và bảo đảm không có đường dẫn thông thường nào bị chặn hoặc stream nhầm.

## Mối liên hệ
- Liên kết trực tiếp với:
  - `crates/proxify-core/src/proxy.rs`: Luồng xử lý `handle_http_request`, `forward_upstream`, và `should_stream_response_headers`.
  - `crates/proxify-core/src/router.rs`: `ProxyRouter` (`is_stream_excluded`, `should_stream_path`, `should_stream_request`).
  - `crates/proxify-core/src/graphql.rs`: `GraphQLParser` (`register_operation_alias`, `register_query_alias`, `parse`).
  - `crates/ext-zalo/src/lib.rs`: `ZaloHookMutator` và `ZaloExtension`.
  - `crates/ext-youtube/src/lib.rs`: `YouTubePlugin` và `YouTubeExtension`.

## Rủi ro (Risks & Edge Cases)
- **Rủi ro bỏ qua Mutator (Critical Defect)**: Nếu upstream trả về `Content-Type: application/javascript`, hàm `forward_upstream` trong `proxy.rs` kiểm tra `should_stream_response_headers(ct, cl)` độc lập và trả về lỗi dạng stream, dẫn đến `handle_http_request` trả thẳng luồng stream về client mà không gọi `mutate_response`. Điều này khiến script độc hại hoặc script hook của Zalo không bao giờ được inject.
- **Rủi ro tranh chấp đa luồng (Concurrency)**: Kiểm tra xem các khóa `RwLock` trong `GraphQLParser` có gặp tình trạng writer starvation hoặc deadlock khi alias được đăng ký đồng thời với hàng loạt query đọc.
