# Tài liệu: `proxify/storage/__init__.py`

## 1. Tóm tắt tổng quan
Module này đóng vai trò là entry point chính của subsystem lưu trữ trong dự án Proxify. Nó cung cấp class `RequestStorage` quản lý việc lưu các HTTP request/response vào cơ sở dữ liệu PostgreSQL. Module chịu trách nhiệm quản lý kết nối, khởi tạo các luồng chạy nền (workers) và cung cấp các phương thức truy vấn API lưu trữ.

## 2. Mục đích & Ý nghĩa
Mục đích của file này là bao bọc lại các tác vụ phức tạp liên quan tới PostgreSQL thành một giao diện đơn giản dễ sử dụng. Với `RequestStorage`, hệ thống dễ dàng khởi động, tự động chạy luồng dọn dẹp dữ liệu cũ (TTL Worker) và tối ưu hóa tốc độ hệ thống nhờ cơ chế ghi bất đồng bộ theo mẻ (Async Batch Writing). Nhờ đó proxy không bị chậm hay giật cục khi có số lượng lớn request cần lưu vào database.

## 3. Mối liên hệ
- Phụ thuộc vào kết nối DB từ `proxify.database.pool`.
- Sử dụng trực tiếp class `RequestRepository` từ `proxify.storage.repository` để thao tác trực tiếp với SQL.
- Sử dụng `TTLWorker` và `AsyncWriterWorker` từ `proxify.storage.workers` để quản lý các tác vụ nền.
- Module tiện ích `proxify.utils.graphql.parse_graphql_request` được gọi để parse (phân tích) request nếu đó là GraphQL.

## 4. Rủi ro (Risks & Edge Cases)
- **DB không khả dụng (PostgreSQL bị tắt/lỗi):** Hệ thống có cơ chế "graceful degradation", nghĩa là nó sẽ log warning và tiếp tục chạy proxy bình thường, chỉ là các request sẽ không được lưu xuống database nữa (phòng tránh treo app).
- **Lỗi parse GraphQL:** Có thể làm hỏng logic lưu. Tuy nhiên đã có bọc exception bên trong hàm tiện ích `parse_graphql_request`.
- **Thất thoát dữ liệu khi tắt app:** Các method `flush()`, `close()`, và `__exit__()` giúp app đợi các queue worker chạy nốt tiến trình ghi để không mất mát dữ liệu đang tồn đọng trong RAM.

## 5. Chi tiết các Class và Hàm

### `RequestStorage` (Class)
Class đóng vai trò làm Controller an toàn luồng (thread-safe) cho mọi thao tác ghi/đọc request từ PostgreSQL.
- `__init__(self, db_dsn: str)`: Hàm khởi tạo. Nhận DSN của cơ sở dữ liệu, khởi tạo pool. Nếu kết nối DB có sẵn, nó tự động khởi tạo bảng (`init_db`) và bật hai worker chạy ngầm (`ttl_worker`, `async_writer`). Ngược lại, thông báo cảnh báo và thiết lập trạng thái vô hiệu DB.
- `__enter__(self)` / `__exit__(self, exc_type, exc_val, exc_tb)`: Context manager methods. `__exit__` tự động gọi hàm `close()` để dọn dẹp các resource.
- `_prepare_request_data(self, data: dict) -> tuple`: Hàm tiền xử lý request data chuẩn bị lưu xuống database. Nó thêm các timestamp (chuẩn và dạng epoch), parse JSON header, và gọi parser nếu phát hiện URL là GraphQL. Output là tuple tuân theo schema SQL insert của repository.
- `flush(self)`: Block thread hiện tại cho đến khi luồng ghi bất đồng bộ (`async_writer`) xử lý xong mọi request còn tồn đọng trong hàng đợi.
- `save_request(self, data: dict) -> int`: Hàm lưu đồng bộ (synchronous). Gọi thẳng database để ghi dữ liệu ngay lập tức và trả về ID.
- `save_request_async(self, data: dict, callback=None)`: Hàm lưu bất đồng bộ (asynchronous). Không chờ kết quả mà đẩy nhanh data vào hàng đợi của `async_writer` để worker này tự gom mẻ (batching) và insert.
- `get_request(self, request_id: int) -> Optional[dict]`: Lấy thông tin chi tiết một log request dựa theo `request_id`.
- `query_requests(self, ...)`: Truy vấn danh sách các request theo bộ lọc như domain, method, status code, hoặc chuỗi tìm kiếm text (search).
- `get_domains(self, since: Optional[float] = None) -> list[dict]`: Lấy danh sách tổng hợp số lượng request cho từng domain độc nhất.
- `get_stats(self, since: Optional[float] = None) -> dict`: Lấy thông số thống kê tổng thể bao gồm tổng dung lượng, số request và phân bố GraphQL.
- `get_requests_for_export(self, ids: Optional[list[int]] = None, **filters) -> list[dict]`: Lấy tất cả trường dữ liệu (full data) để phục vụ tính năng trích xuất / xuất file (export).
- `delete_requests(self, ids: Optional[list[int]] = None)`: Hàm dùng để xóa các bản ghi log dựa trên list IDs cung cấp. Xóa tất cả nếu không truyền ID.
- `close(self)`: Đóng và dọn dẹp module, ra lệnh ngưng workers và chạy hàm `join()` để chờ luồng tắt hẳn.
