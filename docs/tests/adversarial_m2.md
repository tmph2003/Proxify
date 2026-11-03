# Tài liệu Kiểm thử Đối kháng Hiệu năng & Reactor CA — Milestone 2

## 1. Tóm tắt thay đổi
Tạo bộ kiểm thử đối kháng `tests/adversarial_m2_tests.rs` và đăng ký test target `adversarial_m2_tests` trong `Cargo.toml`.
Bộ test bao gồm 6 kịch bản kiểm thử độc lập:
1. `test_adv_ca_leaf_signing_no_reactor_freezing`: Đo lường độ trễ của async heartbeat ticker (5ms) khi có 20 tác vụ ký leaf certificate uncached đồng thời trên runtime giới hạn 2 worker threads.
2. `test_adv_ca_single_flight_broadcast_dedup`: Bắn 50 request đồng thời cho cùng 1 uncached host, chứng minh toàn bộ 50 tác vụ nhận cùng con trỏ `Arc<ServerConfig>` duy nhất qua broadcast channel.
3. `test_adv_ca_single_flight_leader_cancellation_resilience`: Hủy bỏ (abort) tác vụ leader khi đang ký cert, kiểm tra các follower có fallback an toàn mà không bị deadlock hay treo vĩnh viễn.
4. `test_adv_ca_lru_cache_4500_hosts_eviction`: Sinh 4500 host duy nhất, xác thực cơ chế LRU loại bỏ các entry cũ nhất (host 0) nhưng vẫn giữ lại các entry mới (host 3000, host 4400) với ngưỡng 4096.
5. `test_adv_ca_concurrent_lru_stampede`: 16 worker đồng thời thực hiện 50 request host duy nhất xen kẽ với 5 host hotspot dùng chung (tổng cộng 1500+ host) nhằm kiểm tra an toàn đa luồng trên DashMap và atomic counter.
6. `test_adv_zero_copy_bytes_slicing_and_mutation`: Kiểm tra tính năng zero-copy slicing và tính tương thích ngược của buffer `bytes::Bytes` trong `FlowRequest`.

## 2. Mục đích & Ý nghĩa
- Kiểm chứng thực nghiệm (empirical verification) các tuyên bố tối ưu hóa hiệu năng trong Milestone 2 của worker.
- Đảm bảo việc ký chứng chỉ động không làm nghẽn Tokio worker threads (nhờ `spawn_blocking`), cơ chế single-flight hoạt động đúng theo thiết kế broadcast channel, và bộ nhớ cache LRU được giới hạn chặt chẽ ở ngưỡng 4096 mà không gây rò rỉ bộ nhớ hoặc panic.

## 3. Mối liên hệ
- Liên kết trực tiếp với module `crates/proxify-core/src/ca.rs` (struct `CertificateAuthority`, `CaSigner`).
- Liên kết với `crates/proxify-sdk/src/lib.rs` (`FlowRequest` payload `bytes::Bytes`).
- Được tích hợp vào bộ kiểm thử chung qua `Cargo.toml`.

## 4. Rủi ro (Risks & Edge Cases)
- **Cạnh tranh tài nguyên khi nhiều tiến trình cargo chạy song song**: Việc chạy nhiều container Docker cùng mount chung volume build directory có thể gây `Blocking waiting for file lock`. Cần tuần tự hóa việc chạy test.
- **Tiêu thụ tài nguyên sinh cert**: Ký 4500 chứng chỉ trong test LRU tiêu tốn một lượng CPU nhất định. Tuy nhiên, việc sử dụng chung root key và shared leaf key giúp giảm thiểu thời gian chạy xuống mức tối ưu.
