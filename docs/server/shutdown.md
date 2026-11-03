# Tài Liệu Kỹ Thuật: Cơ Chế Graceful Process Shutdown

## 1. Tóm Tắt Thay Đổi

Trong `crates/proxify-server/src/main.rs`, hệ thống đã được triển khai đầy đủ cơ chế dừng tiến trình an toàn (Graceful Shutdown) và xử lý tín hiệu hệ điều hành:

1. **Lắng nghe tín hiệu dừng (`tokio::signal::ctrl_c`)**:
   - Sử dụng `tokio::select!` để giám sát đồng thời tín hiệu ngắt người dùng (`Ctrl+C` / `SIGINT`) và trạng thái sống của các background tasks (`proxy_handle`, `dash_handle`).
2. **Kênh thông báo dừng đồng bộ (`tokio::sync::watch`)**:
   - Khởi tạo watch channel `(shutdown_tx, shutdown_rx)` để phát tín hiệu dừng tới máy chủ Web Dashboard (Axum) thông qua `server.with_graceful_shutdown()`, cho phép các kết nối HTTP/WebSocket dashboard hiện hữu hoàn tất phiên làm việc trước khi đóng socket.
3. **Xả hàng đợi lưu trữ (`RequestStorage::shutdown`)**:
   - Gửi chỉ thị `StorageItem::Flush(ack_tx)` vào kênh tác vụ ngầm của `RequestStorage` và chờ xác nhận (`ack_rx.await`) từ worker lưu trữ PostgreSQL.
   - Toàn bộ các bản ghi request/response đang nằm trong RAM buffer được flush và commit vào cơ sở dữ liệu trước khi tiến trình thoát hoàn toàn.

---

## 2. Mục Đích & Ý Nghĩa

- **Chống mất mát dữ liệu (Zero Data Loss)**: Trước khi có graceful shutdown, khi người dùng bấm `Ctrl+C` hoặc container nhận `SIGTERM`, tiến trình bị kill đột ngột, toàn bộ các gói tin vừa bắt được nằm trong kênh `mpsc` (tối đa 2,000 bản ghi) và batch buffer chưa kịp commit vào PostgreSQL sẽ bị mất vĩnh viễn.
- **Bảo toàn tính toàn vẹn phiên kết nối (Connection Integrity)**: Đảm bảo máy chủ dashboard Axum và client không nhận lỗi `Connection reset by peer` (TCP RST) đột ngột, mà được đóng bằng chuỗi bắt tay FIN/ACK chuẩn TCP.

---

## 3. Mối Liên Hệ

- **`crates/proxify-server/src/main.rs`**: Điểm khởi động chính của binary server, quản lý vòng đời (lifecycle) của toàn bộ tiến trình.
- **`crates/proxify-core/src/storage.rs`**: Module quản lý hàng đợi ghi và kết nối `deadpool-postgres`, cung cấp hàm `flush()` và `shutdown()`.
- **`crates/proxify-server/src/dashboard.rs`**: Cung cấp giao diện Web và Telemetry WebSocket nhận tín hiệu dừng từ `shutdown_rx`.

---

## 4. Rủi Ro (Risks & Edge Cases)

1. **Database Treo hoặc Quá Tải Khi Shutdown**:
   - *Rủi ro*: Nếu cơ sở dữ liệu PostgreSQL đang bị khóa hoặc mất kết nối mạng, việc chờ `flush().await` có thể khiến tiến trình bị treo vô hạn lúc tắt máy.
   - *Biện pháp giảm thiểu*: Kênh `mpsc` và tác vụ kết nối `deadpool-postgres` sử dụng connection timeout. Trong các milestone tiếp theo, có thể bổ sung `tokio::time::timeout` (ví dụ: tối đa 5 giây) cho hàm `storage_for_shutdown.shutdown()` để ép buộc thoát nếu database không phản hồi kịp thời.
2. **Nhiều tín hiệu Ctrl+C dồn dập**:
   - *Rủi ro*: Người dùng nhấn Ctrl+C liên tục nhiều lần.
   - *Biện pháp xử lý*: `tokio::select!` bắt tín hiệu đầu tiên và chuyển ngay sang luồng shutdown; các tín hiệu tiếp theo của OS sẽ được xử lý tự nhiên bởi runtime.
