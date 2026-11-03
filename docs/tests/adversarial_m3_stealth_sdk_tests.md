# Tài liệu Bộ Kiểm thử Đối kháng: Stealth Soft-Block & SDK Tương thích ngược (Milestone 3)

## 1. Tóm tắt thay đổi
Tạo bộ kiểm thử đối kháng `tests/adversarial_m3_stealth_sdk_tests.rs` nhằm kiểm chứng độc lập và stress-test các tính năng của Milestone 3:
- Kiểm thử phát hiện soft-block cốt lõi (`CORE_SOFT_BLOCK_SIGNATURES`) và các mã trạng thái HTTP (429, 403, 401).
- Kiểm thử đăng ký động các signature của `ext-facebook` (`"error":1357001`, `"is_checkpoint":true`, `/checkpoint/block`, v.v.).
- Kiểm thử khả năng miễn nhiễm với dương tính giả (false-positive immunity): mã lỗi 0, 100, 1357000, 1357002, `is_checkpoint: false`, HTTP 200, 404, 500, 502.
- Kiểm thử tương tranh tải cao: 50 luồng đồng thời đăng ký signature và quét phát hiện gói tin.
- Kiểm thử an toàn bộ đệm UTF-8 multi-byte tại biên cắt lát 2000 ký tự.
- Kiểm thử tương thích ngược SDK: thực thi trait method `on_Init` (deprecated) và kiểm chứng cơ chế bao đóng `ExtensionContext` (sử dụng pool khởi tạo từ `deadpool_postgres::tokio_postgres`).

## 2. Mục đích & Ý nghĩa
- Đảm bảo việc tách rời logic khỏi `proxify-core` sang `ext-facebook` và các extension không làm suy giảm tính chính xác hoặc gây tranh chấp tài nguyên (race conditions/deadlocks) trong môi trường proxy chịu tải cao.
- Bảo đảm tính toàn vẹn của SDK khi các plugin cũ gọi phương thức `on_Init` thì mã khởi tạo vẫn vận hành trơn tru mà không xảy ra hoảng loạn (panic) hoặc lỗi biên dịch.

## 3. Mối liên hệ
- Liên kết trực tiếp với module `crates/proxify-core/src/stealth.rs` (`StealthSessionManager`, `register_soft_block_signature`, `is_soft_blocked`).
- Liên kết với `crates/proxify-sdk/src/lib.rs` (`BaseExtension`, `ExtensionContext`, `EventPublisher`).
- Liên kết với các signature đặc thù của `crates/ext-facebook/src/lib.rs`.

## 4. Rủi ro & Phát hiện Thực nghiệm (Empirical Findings & Risks)
- **Lỗ hổng Cắt lát chuỗi UTF-8 (Char Boundary Panic)** (Xác nhận Thực nghiệm):
  - Tại `crates/proxify-core/src/stealth.rs:228-232`:
    ```rust
    let check_chunk = if body.len() > 2000 {
        &body[..2000]
    } else {
        body
    };
    ```
  - Nếu phản hồi từ upstream có độ dài > 2000 bytes và byte thứ 2000 rơi vào giữa ký tự UTF-8 (ví dụ tiếng Việt có dấu, emoji 4-bytes, dấu nháy kép typographic `\u{2019}`), Rust lập tức panic: `end byte index 2000 is not a char boundary; it is inside ... of string`. Điều này gây crash luồng worker của stealth crawler.
  - Khuyến nghị khắc phục cho worker: Dùng `body.char_indices().nth(...)` hoặc `floor_char_boundary(2000)` thay vì trực tiếp `&body[..2000]`.
- **Hiện tượng Shadowing Signature trong Core**:
  - Trong `CORE_SOFT_BLOCK_SIGNATURES`: `"Temporarily Blocked"` được đặt trước `"You\u{2019}re Temporarily Blocked"`. Vì `"Temporarily Blocked"` là chuỗi con của `"You’re Temporarily Blocked"`, nên mọi chuỗi chứa `"You’re Temporarily Blocked"` đều sẽ khớp với phần tử thứ nhất trước, khiến phần tử thứ hai bị che khuất (dead branch).
- **Hạn chế Ủy quyền Lifecycle Tương thích ngược (Legacy Extension)**:
  - Nếu một plugin kế thừa cũ chỉ cài đè `on_Init(&self, ctx)` mà không cài đè `on_init(&self, ctx)`, khi host hiện đại (`main.rs`) gọi `ext.on_init()`, hàm mặc định của trait sẽ trả về `Ok(())` mà không gọi `on_Init()`, dẫn tới plugin cũ không được cấu hình tài nguyên. Tuy nhiên, nếu caller gọi trực tiếp `ext.on_Init()`, việc ủy quyền hoạt động bình thường.
