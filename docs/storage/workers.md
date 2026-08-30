# Tài liệu: `proxify/storage/workers.py`

## 1. Tóm tắt tổng quan
File `workers.py` chứa các class quản lý và thực thi luồng công việc chạy ngầm (background threading) của phần lưu trữ. Có hai worker chính là TTL Worker (tự động dọn rác dữ liệu cũ) và Async Writer (quản lý hàng đợi ghi để không làm chậm Proxy).

## 2. Mục đích & Ý nghĩa
Một proxy xử lý lượng lớn kết nối mạng không được phép dừng để chờ database thực hiện tác vụ nội bộ (như insert). `workers.py` cung cấp cơ chế batching (gom mẻ) ghi đồng loạt giúp làm tối đa hiệu suất cho Postgres. TTL worker tự động giữ cho server không bị phình to (Out-of-storage). Đây là cơ sở cốt lõi cho tính "Non-blocking" và bền bỉ của ứng dụng.

## 3. Mối liên hệ
- Thừa kế abstract class từ `abc` module, quản lý luồng bằng `threading`.
- Sử dụng cấu trúc `queue.Queue` làm hàng đợi dữ liệu.
- Được tạo và kiểm soát vòng đời bởi class `RequestStorage` trong `__init__.py`.

## 4. Rủi ro (Risks & Edge Cases)
- **Quá tải hàng đợi (Backpressure):** `AsyncWriterWorker` quy định size queue max = 5000 để chống phình to RAM (OOM). Khi hàng đợi nghẽn, nó bắt `queue.Full` và cố ý thả rơi (drop) log request thay vì làm hỏng app.
- **Sập worker do crash (Exception bất chợt):** Luồng gốc `_run_loop` luôn catch toàn bộ Exception để bỏ qua và tiếp tục `do_work`, hạn chế worker chết hẳn do 1 request lỗi ngớ ngẩn.
- **Race Condition & Shutdown:** Dùng `threading.Event()` thay vì boolean thường để ngắt luồng an toàn, bảo đảm luồng không bị treo vô tận.

## 5. Chi tiết các Class và Hàm

### `BackgroundWorker(ABC)` (Class)
Một Abstract Base Class quy chuẩn hóa vòng đời của 1 thread worker ngầm, xử lý exception bao bọc xung quanh.
- `__init__(self, pool, repository, name="Worker")`: Cấu hình thread `daemon=True`, sử dụng stop_event và lưu trữ instance pool, repo.
- `start(self)`: Bắt đầu run thread nền.
- `stop(self)`: Kích hoạt cờ (`_stop_event.set()`) đánh tín hiệu cho worker thoát vòng lặp vô hạn.
- `join(self, timeout=2.0)`: Đợi một khoảng thời gian trước khi kết thúc triệt để thread (sử dụng khi thoát app).
- `_run_loop(self)`: Chạy vòng lặp ngầm (While not stop), liên tục gọi `do_work()`, block chứa try/except giúp cách ly các exception nguy hiểm ra khỏi main app.
- `on_start(self)` / `on_stop(self)`: Abstract hook có thể override để thêm tác vụ lúc khởi động hoặc dừng.
- `do_work(self)`: Phương thức abstract bắt buộc phải implement tại class con.

### `TTLWorker(BackgroundWorker)` (Class)
Worker chịu trách nhiệm tự động loại bỏ các bản ghi lưu trữ đã hết đát (cũ hơn 3 ngày) khỏi Database.
- `__init__(self, pool, repository)`: Đặt tên worker là "TTL Worker", set state `_first_run = True`.
- `do_work(self)`: Trong chu kỳ đầu, đợi (wait timeout) 60 giây để tránh tranh chấp với khởi động ban đầu của proxy. Sau đó, nó tự động ngủ 1 tiếng (3600 giây). Hết thời gian chờ, gọi kết nối để chạy logic xóa và log ra số lượng bản ghi loại bỏ.

### `AsyncWriterWorker(BackgroundWorker)` (Class)
Worker nhận Request data vào hàng đợi trong RAM, gom lại và ghi đồng loạt vào cơ sở dữ liệu.
- `__init__(self, pool, repository, batch_size)`: Tạo 1 biến `write_queue` tối đa 5000 records. Định nghĩa kích thước lô (`batch_size`), mảng chứa dữ liệu `_batch` và callback.
- `enqueue(self, data, callback=None)`: Thêm nhanh chóng data từ ngoài vào hàng đợi ghi không chặn bằng `put_nowait()`. Nó kiểm soát độ lớn bộ nhớ, bỏ qua log mới có log ra cảnh báo nếu hàng đợi bị kẹt (`queue.Full`).
- `flush(self)`: Đợi cho đến khi toàn bộ yêu cầu xếp hàng trong Queue bị đẩy (hoặc hủy bỏ).
- `do_work(self)`: Chạy rút tuần tự các bản ghi từ queue (timeout ngắn 0.1s cho mỗi bản ghi nếu queue trống). Nếu `_batch` đầy hoặc timeout, nó sẽ gom mẻ vào PostgreSQL thông qua `save_requests_batch()`. Hậu xử lý gọi `task_done` lên tất cả record vừa lấy.
- `on_stop(self)`: Phương thức hook khi dừng, để sẵn cho các logic cleanup mẻ (hiện tại rỗng).
