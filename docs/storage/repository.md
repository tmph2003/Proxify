# Tài liệu: `proxify/storage/repository.py`

## 1. Tóm tắt tổng quan
File `repository.py` chịu trách nhiệm khai báo và xử lý toàn bộ các câu lệnh tương tác SQL trực tiếp với PostgreSQL đối với bảng dữ liệu `requests`. File này độc lập với logic nghiệp vụ, hoàn toàn tập trung vào Database Access Layer.

## 2. Mục đích & Ý nghĩa
Việc cô lập tất cả câu lệnh SQL vào file `repository.py` áp dụng mẫu thiết kế Repository Pattern. Nó đảm bảo các class quản lý phía trên (`RequestStorage`) không cần biết về SQL hay cách hoạt động nội bộ của cơ sở dữ liệu. Đồng thời, nó cài đặt các trigger, index và Full-text Search (FTS) của PostgreSQL để tối ưu khả năng truy xuất dữ liệu cực nhanh cho số lượng lớn logs.

## 3. Mối liên hệ
- Hoạt động phụ thuộc chặt chẽ cùng thư viện `psycopg2`.
- Được gọi trực tiếp từ `RequestStorage`, `TTLWorker`, `AsyncWriterWorker` trong phân hệ lưu trữ.

## 4. Rủi ro (Risks & Edge Cases)
- **SQL Injection:** Việc tìm kiếm và truy vấn động tiềm ẩn SQL injection. May mắn thay, mọi query trong này đều sử dụng parameterized variables (`%s`), khiến nó hoàn toàn an toàn.
- **Full Text Search Performance Hit:** Có hàm và trigger postgres `update_search_vector()` chạy ở mỗi lần Insert/Update, điều này làm giảm một chút hiệu năng ghi. Tuy nhiên, việc ghi đa số là được batching qua AsyncWorker để triệt tiêu khuyết điểm tốc độ đó.
- **Parsing Lỗi JSON:** Data đôi khi bị hỏng, vì thế hàm parse kết quả lấy từ database bắt exception `json.JSONDecodeError` để bỏ qua nếu string không hợp lệ.

## 5. Chi tiết các Class và Hàm

### `RequestRepository` (Class)
Class chứa toàn bộ logic truy vấn Database tĩnh cho phần quản lý log request, hoàn toàn phi trạng thái (stateless), nhận biến kết nối (`conn` hoặc `pool`) mỗi khi gọi method.
- `init_db(self, conn)`: Dùng để thiết lập cấu trúc database. Chạy lệnh CREATE TABLE `requests`, tạo chỉ mục btree cơ bản, GIN index. Đặc biệt hàm sẽ định nghĩa PostgreSQL Function và Trigger `tsvectorupdate` tự động index từ khóa để phục vụ tìm kiếm.
- `delete_old_requests(self, conn, interval: str = '3 days') -> int`: Hàm xóa bỏ tự động dữ liệu cũ (mặc định quá 3 ngày) bằng SQL, phục vụ cho TTL Worker. Trả về số dòng đã bị xóa.
- `save_requests_batch(self, conn, batch: list, callbacks: list) -> None`: Hàm tối ưu tốc độ ghi bằng cách sử dụng `psycopg2.extras.execute_values` ghi một danh sách request lớn trong 1 câu SQL Insert. Duyệt mảng `callbacks` sau khi hoàn tất.
- `save_request(self, conn, params: tuple) -> int`: Thực thi insert 1 bản ghi (tuple params) trực tiếp xuống DB, trả về khóa chính (ID).
- `get_request(self, pool, request_id: int) -> Optional[dict]`: Lấy ra record khớp với ID cung cấp, format trả lại thành dictionary.
- `query_requests(self, pool, domain, method, status_code, search, graphql_only, limit, offset, since) -> list[dict]`: Hàm sinh câu SQL động (dynamic query builder) dựa vào các bộ lọc. Nó truy xuất plainto_tsquery nếu người dùng sử dụng full text search `search`. Trả về list các bản ghi vắn tắt.
- `get_domains(self, pool, since) -> list[dict]`: Dùng SQL `GROUP BY` để đếm số lượng bản ghi của mỗi tên miền.
- `get_stats(self, pool, since) -> dict`: Lấy thông số thống kê vĩ mô (SUM, COUNT) ví dụ tổng số log, số unique domain, tổng lượng băng thông tiêu thụ.
- `get_requests_for_export(self, pool, ids, **filters) -> list[dict]`: Select tất cả các cột cho một tập bản ghi, dùng để xuất báo cáo nguyên bản (export file).
- `delete_requests(self, pool, ids)`: Xóa các rows bằng mệnh đề `IN (id1, id2)` hoặc xóa sạch table nếu không cung cấp danh sách.
- `_row_to_dict(self, row: dict) -> dict`: Tiện ích nội bộ để ánh xạ `psycopg2` dictionary row về dictionary chuẩn của Python. Nó loại bỏ vector thô `search_vector` không cần thiết, tự động `json.loads()` đối với các cột header, tags, để output dùng được ngay.
