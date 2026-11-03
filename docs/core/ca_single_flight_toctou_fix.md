# Khắc phục Lỗ hổng Đua Tranh TOCTOU trong Single-Flight Ký Chứng chỉ TLS (`CertificateAuthority`)

## Tóm tắt thay đổi

Sửa đổi hàm `CertificateAuthority::server_config_for_host_async` trong `crates/proxify-core/src/ca.rs`:
1. **Đảo thứ tự cập nhật cache và thu hồi khóa `in_flight`**: Ghi cấu hình `Arc<ServerConfig>` vào `self.leaf_cache` (`insert_to_cache`) **trước** khi xóa mục đang xử lý khỏi `self.in_flight` và phát tín hiệu `broadcast`.
2. **Double-Checked Locking trong nhánh `Entry::Vacant`**: Khi chiếm được shard lock của `self.in_flight` ở trạng thái `Vacant`, kiểm tra lại `self.leaf_cache.get(&clean_host)` một lần nữa trước khi khởi tạo leader mới.

## Mục đích & Ý nghĩa

- Loại bỏ hoàn toàn cửa sổ đua tranh (TOCTOU race window) khi hàng trăm kết nối TLS đồng thời (thundering herd, như khi mở YouTube nạp hàng chục request song song tới cùng domain) cùng yêu cầu chứng chỉ lá cho một hostname chưa có trong cache:
  - Trước đây, leader xóa `in_flight` trước khi chèn vào `leaf_cache`, khiến một task đến trễ đúng vào khoảng giữa hai thao tác này thấy cả `leaf_cache` và `in_flight` đều trống và tự kích hoạt tác vụ ký mật mã RSA/ECDSA trùng lặp.
  - Đảm bảo 100% các luồng đồng thời nhận về chính xác cùng một con trỏ `Arc<ServerConfig>` và loại bỏ lãng phí CPU trên threadpool `spawn_blocking`.

## Mối liên hệ

- **`crates/proxify-core/src/ca.rs`**: Thực thi cơ chế cấp phát chứng chỉ MITM động cho toàn bộ luồng HTTPS đi qua `MitmProxyServer` (`crates/proxify-core/src/proxy.rs`).
- **`tests/adversarial_tier5_hardening_tests.rs`**: Đảm bảo bài kiểm thử áp lực cao `test_tier5_adv_cert_gen_100_concurrent_thundering_herd` đạt tính tất định tuyệt đối 100%.

## Rủi ro (Risks & Edge Cases)

- **Nguy cơ Deadlock giữa hai `DashMap` (`in_flight` và `leaf_cache`)**: Đã được kiểm chứng an toàn vì thứ tự khóa luôn đơn chiều hoặc độc lập — nhánh `Entry::Vacant` chỉ đọc ngắn hạn `leaf_cache.get()` trong khi giữ shard lock `in_flight`, còn leader gọi `insert_to_cache` (chỉ khóa `leaf_cache`) khi **không** giữ bất kỳ tham chiếu shard lock nào của `in_flight`, do đó không bao giờ xảy ra chu trình khóa ngược (AB-BA deadlock).
