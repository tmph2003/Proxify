# Tài liệu Kỹ thuật Milestone 2: Performance Engine & Zero-Copy Pipeline

## 1. Tóm tắt thay đổi (Summary of Changes)
Milestone 2 tập trung nâng cấp toàn diện hiệu năng của Proxify từ tầng kiến trúc mạng, xử lý bộ nhớ, mật mã học TLS đến tầng lưu trữ cơ sở dữ liệu:
- **Asynchronous TLS Leaf Signing**:
  - Chuyển tác vụ sinh chứng chỉ lá (`rcgen`) tiêu tốn nhiều chu kỳ CPU sang worker pool blocking của Tokio (`tokio::task::spawn_blocking`) thông qua `CaSigner`.
  - Triển khai cơ chế **Single-Flight Deduplication** (`InFlightGuard` + `tokio::sync::broadcast`) giúp gom các kết nối đồng thời vào cùng một domain chỉ thực hiện 1 lần tính toán mã hóa RSA/ECDSA.
  - Xây dựng thuật toán **True LRU Eviction** với bộ đếm truy cập nguyên tử (`AtomicU64`) khi bộ nhớ cache vượt ngưỡng $4096$ chứng chỉ.
- **Zero-Copy Flow Buffers**:
  - Chuyển đổi toàn bộ `FlowRequest.content` và `FlowResponse.content` trong `proxify-sdk` từ `Vec<u8>` sang `bytes::Bytes` (Zero-copy slice ref-counted buffer).
  - Cập nhật luồng xử lý proxy trong `proxify-core/src/proxy.rs`, `storage.rs`, và các extension (`ext-youtube`, `ext-zalo`) sang `Bytes`, loại bỏ các thao tác sao chép bộ nhớ `.clone()` hoặc `to_vec()`.
- **HeaderMap Pipeline & Multi-Value Preservation**:
  - Thay thế toàn bộ các lệnh ghi đè `insert` header trong WebSocket Upgrade và HTTP Response Builder bằng phương thức `append`, bảo toàn nguyên vẹn các header lặp lại nhiều lần (ví dụ: `Set-Cookie`, `Sec-WebSocket-Protocol`).
  - Hạn chế cấp phát chuỗi trung gian bằng cách duyệt trực tiếp `HeaderMap` và tái sử dụng `HeaderName` / `HeaderValue`.
- **Pre-normalized Allocation-Free Domain Routing**:
  - Tiền chuẩn hóa các quy tắc stream domain (`StreamDomainRule`) với cấu trúc lưu sẵn `exact` và `dot_suffix`.
  - Loại bỏ hoàn toàn việc cấp phát chuỗi động `format!(".{}", d)` trên mỗi request.
  - Phân giải chuỗi domain bằng cách cắt lát tham chiếu `&str` trực tiếp thay vì cấp phát `Vec<String>`.
  - Tối ưu đường đi nhanh (fast path) không cấp phát `HashSet` khi chỉ có $\le 1$ plugin đăng ký.
- **Vectorized Database Batch Flush**:
  - Tái cấu trúc hoàn toàn hàm `flush_batch` trong `proxify-core/src/storage.rs` từ việc thực thi tuần tự từng câu lệnh `INSERT` đơn lẻ thành **Multi-row `INSERT` statement** với 1 transaction và 1 round-trip mạng duy nhất.
- **Production Release Profile & Mimalloc Allocator**:
  - Cấu hình cấu hình biên dịch tối ưu trong root `Cargo.toml`: `lto = "fat"`, `codegen-units = 1`, `panic = "abort"`, `strip = true`.
  - Tích hợp bộ cấp phát bộ nhớ hiệu năng cao `mimalloc` làm `#[global_allocator]` cho `proxify-server`.
- **DNS Single-Flight RAII Drop Guard**:
  - Bổ sung `DnsInFlightGuard` bảo vệ bảng tra cứu DNS đơn luồng (`in_flight`), đảm bảo kênh broadcast luôn được giải phóng an toàn khi task bị hủy hoặc timeout.

---

## 2. Mục đích & Ý nghĩa (Purpose & Significance)

### 2.1 Giải quyết điểm nghẽn CPU trong TLS Interception
- **Vấn đề trước đây**: Khi client mở đồng thời hàng chục kết nối HTTPS (HTTP/2 multiplexing, nhiều tab hoặc resource loading), hàm `server_config_for_host` thực hiện ký chứng chỉ lá đồng bộ ngay trên async runtime của Tokio. Điều này làm "bắt cóc" (starve) các luồng worker của Tokio, khiến độ trễ của các request khác tăng vọt. Ngoài ra, cache ban đầu sử dụng chiến lược xóa ngẫu nhiên (arbitrary key removal) không tối ưu và khi nhiều request cùng vào một host chưa có cache, mỗi request đều thực hiện ký lại một chứng chỉ giống hệt nhau.
- **Giải pháp**: Tách biệt `CaSigner` chạy trên `spawn_blocking`, đồng thời gom luồng bằng `broadcast` channel (Single-flight) và cơ chế xóa LRU thực thụ giúp tiết kiệm đáng kể CPU và giảm P99 latency khi bắt đầu phiên TLS.

### 2.2 Loại bỏ gánh nặng phân mảnh bộ nhớ và Garbage Collection qua Zero-Copy
- **Vấn đề trước đây**: Mỗi request và response có payload lớn (ảnh, video, file binary) khi đi qua proxy, extension pipeline, storage recorder và WebSocket handler đều bị `to_vec()` hoặc `.clone()` nhiều lần. Điều này gây tốn RAM gấp 3-5 lần dung lượng thực tế và gây áp lực phân mảnh bộ nhớ trầm trọng.
- **Giải pháp**: `bytes::Bytes` sử dụng con trỏ chia sẻ bộ đếm tham chiếu (atomic reference counting) và cho phép slice lát cắt dữ liệu mà không cần cấp phát lại buffer. Kết hợp với `mimalloc`, proxy đạt thông lượng cực cao với chi phí cấp phát bộ nhớ gần như bằng không trong đường dẫn dữ liệu nóng.

### 2.3 Bảo toàn tính toàn vẹn giao thức HTTP/WebSocket
- **Vấn đề trước đây**: Thao tác `headers_mut().insert(...)` sẽ ghi đè và làm mất các header trùng tên xuất hiện hợp lệ trong HTTP (đặc biệt là nhiều dòng `Set-Cookie` hoặc giao thức đàm phán WebSocket).
- **Giải pháp**: Chuyển sang `headers_mut().append(...)` tuân thủ tiêu chuẩn RFC, bảo vệ phiên đăng nhập và khả năng tương thích của client.

### 2.4 Giảm tải I/O cơ sở dữ liệu từ $O(N)$ xuống $O(1)$ round-trips
- **Vấn đề trước đây**: Khi proxy nhận tải cao, hàng nghìn request log cần ghi xuống PostgreSQL. Cơ chế cũ gọi tuần tự từng câu lệnh `INSERT` lặp lại theo batch size, tiêu tốn $N$ round-trips mạng và khóa bảng liên tục.
- **Giải pháp**: Xây dựng câu lệnh `INSERT INTO public.requests (...) VALUES ($1, ...), ($18, ...) ...` theo lô vectorized, đưa toàn bộ batch vào 1 truy vấn duy nhất.

---

## 3. Mối liên hệ (Inter-module Relationships & Impact)

- **`proxify-sdk` $\leftrightarrow$ `proxify-core` $\leftrightarrow$ Extension Ecosystem**:
  - `FlowRequest` và `FlowResponse` trong `proxify-sdk` là struct dữ liệu trung tâm dùng chung giữa proxy core và các extension (như `ext-youtube`, `ext-zalo`, `ext-facebook`).
  - Việc chuyển `content` sang `bytes::Bytes` duy trì tính tương thích ngược hoàn toàn nhờ cung cấp các phương thức truy cập tiện ích: `body()`, `body_mut()`, `content_slice()`, `content_vec()`, `set_content()`. Các extension cũ và mới đều có thể thao tác mà không bị breaking API.
- **`proxy.rs` $\leftrightarrow$ `ca.rs`**:
  - `handle_connect` trong `proxy.rs` gọi phương thức bất đồng bộ `server_config_for_host_async(&host).await`. Proxy task không còn bị chặn luồng async trong quá trình handshake TLS.
- **`proxy.rs` $\leftrightarrow$ `storage.rs`**:
  - Cấu trúc `RequestRecord` trong `storage.rs` nhận `Option<bytes::Bytes>` trực tiếp từ proxy pipeline. Thao tác giới hạn độ dài payload được thực hiện bằng `b.slice(0..max)` thay vì cắt lát vector tốn bộ nhớ.
- **`router.rs` $\leftrightarrow$ Plugins**:
  - Router xử lý tra cứu domain cho từng request/response. Các quy tắc streaming được lưu trong cấu trúc nén `StreamDomainRule` giúp bước kiểm tra không sinh ra bất kỳ bộ nhớ heap nào.
- **`proxify-server` $\leftrightarrow$ `mimalloc`**:
  - Binary `proxify-server` kích hoạt `mimalloc` trên phạm vi toàn cục, hưởng lợi từ cấu trúc phân bổ bộ nhớ thread-local cache tốc độ cao, hỗ trợ đa luồng không lock contention.

---

## 4. Rủi ro & Trường hợp Ngoại lệ (Risks & Edge Cases)

1. **Giới hạn số lượng tham số trong PostgreSQL Parameterized Queries**:
   - *Rủi ro*: Giao thức PostgreSQL giới hạn tối đa 65,535 parameters cho một prepared statement. Với mỗi record có 17 tham số, một batch vượt quá $\approx 3800$ bản ghi có thể chạm trần giới hạn protocol.
   - *Đánh giá & Xử lý*: `BATCH_SIZE` hiện tại được cấu hình là 100 bản ghi ($100 \times 17 = 1,700$ parameters), thấp hơn rất nhiều so với ngưỡng an toàn 65,535.
2. **Hủy tác vụ đột ngột khi đang đợi DNS hoặc TLS Single-Flight**:
   - *Rủi ro*: Khi một request client ngắt kết nối (drop connection) trong khi đang là "leader" thực hiện DNS lookup hoặc ký TLS cert, nếu không xử lý giải phóng entry trong bảng `in_flight`, các "follower" request tiếp theo có thể bị kẹt hoặc bảng tra cứu bị rò rỉ bộ nhớ.
   - *Xử lý*: Đã cài đặt `DnsInFlightGuard` và `InFlightGuard` với cơ chế RAII (`Drop` trait). Ngay cả khi task bị panic hoặc bị Tokio hủy bỏ (`tokio::select!`), guard sẽ tự động dọn dẹp entry khỏi bảng `in_flight`.
3. **Cơ chế Fallback khi Broadcast Channel bị Lagged hoặc Closed**:
   - *Rủi ro*: Nếu leader task hoàn thành hoặc bị lỗi khiến kênh broadcast bị đóng trước khi follower kịp nhận kết quả.
   - *Xử lý*: Khối `Err(RecvError::Closed)` hoặc `Err(RecvError::Lagged)` được thiết kế để tự động kiểm tra lại cache lần thứ hai (`self.leaf_cache.get(&clean_host)`) hoặc rơi vào đường dẫn sinh trực tiếp độc lập, không làm sập request của client.
4. **Chia sẻ Buffer qua `Bytes` và Vòng đời Bộ nhớ**:
   - *Rủi ro*: Nếu giữ một lát cắt nhỏ `b.slice(0..10)` của một buffer lớn 100MB trong thời gian dài, toàn bộ buffer 100MB đó sẽ không được thu hồi cho đến khi tất cả các slice được drop.
   - *Xử lý*: Đối với việc lưu trữ bản ghi vào database, các byte slice được chuyển đổi sang kiểu dữ liệu lưu trữ tương ứng hoặc chỉ tồn tại trong thời gian ngắn của vòng đời batch flush, do đó không gây hiện tượng neo giữ bộ nhớ dài hạn.
