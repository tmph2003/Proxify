# Tài liệu Benchmark: Bổ sung Criterion Microbenchmarks cho Data Plane Components

## Tóm tắt thay đổi
Bổ sung các hàm benchmark vi mô chuyên sâu trong `benches/proxy_micro_benches.rs`:
1. `router_match_lookup`: Đo lường chi phí tra cứu Radix-Trie domain router cho các domain thực tế.
2. `header_map_transformation`: Đo lường chi phí zero-copy `HeaderMap::clone` và xử lý header của Hyper so với việc tuần tự chuyển đổi sang `HashMap<String, String>`.
3. `bench_flow_buffer_zero_copy`: So sánh trực tiếp giữa `bytes::Bytes::clone` (zero-copy buffer với refcount bump) và `Vec<u8>::clone` (deep memory allocation copy) trên buffer kích thước 64 KiB, thiết lập throughput bytes để đo lường băng thông xử lý (MB/s và ns).
4. `bench_ca_signing`: So sánh thời gian ký chứng chỉ lá TLS động giữa phương thức đồng bộ `server_config_for_host` và bất đồng bộ `server_config_for_host_async` (được offload qua `tokio::task::spawn_blocking` kết hợp single-flight broadcast deduplication).

## Mục đích & Ý nghĩa
- Cung cấp số liệu định lượng chuẩn xác từ công cụ đo lường Criterion cho toàn bộ các cải tiến hiệu năng của Milestone 2 và 3.
- Chứng minh tính ưu việt của zero-copy buffer (`bytes::Bytes`), giảm thiểu cấp phát bộ nhớ (allocation overhead), và đảm bảo reactor thread không bị nghẽn (no reactor starvation) khi sinh chứng chỉ TLS động.
- Đáp ứng đầy đủ các tiêu chuẩn nghiệm thu và yêu cầu đo kiểm của Milestone 4.

## Mối liên hệ
- Liên kết trực tiếp với `crates/proxify-core/src/ca.rs` (CA leaf caching, async signing, single-flight deduplication).
- Liên kết với `crates/proxify-core/src/router.rs` (Radix-Trie domain matcher).
- Liên kết với `crates/proxify-sdk` (`FlowRequest`, `FlowResponse` sử dụng `bytes::Bytes`).
- Cung cấp số liệu gốc cho báo cáo hiệu năng toàn diện tại `docs/performance/final_benchmark_report.md`.

## Rủi ro (Risks & Edge Cases)
- **CPU Throttling / Nhiệt độ phần cứng**: Kết quả benchmark có thể dao động nhẹ tùy thuộc vào tải nền của hệ thống máy chủ hoặc container runtime. Đã cấu hình warmup hợp lý và số mẫu phù hợp (`sample_size(20)` cho cryptographic signing) để hạn chế sai số.
- **Cache Eviction**: Trong các test đo uncached signing, host được sinh với chuỗi đếm tăng dần (`sync-N.bench.test`, `async-N.bench.test`) để tránh va chạm với cache LRU, đảm bảo luôn đo đạc chính xác chi phí cryptographic generation thực tế.
