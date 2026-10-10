# Tài liệu: events.py

## 1. Tóm tắt tổng quan
Module `events.py` định nghĩa cơ chế Event Bus (Observer Pattern) dạng đồng bộ. Cơ chế này dùng để đăng ký và phát (publish) các sự kiện cho toàn bộ hệ thống.

## 2. Mục đích & Ý nghĩa
Cung cấp khả năng giao tiếp lỏng lẻo (loosely coupled) giữa các thành phần trong hệ thống. Một module chỉ việc gửi sự kiện lên EventBus, và mọi module khác đã đăng ký lắng nghe (subscribe) sẽ tự động tiếp nhận và xử lý mà không cần phải gọi trực tiếp lẫn nhau.

## 3. Mối liên hệ
- Sử dụng trong `DatabaseWriter` (thuộc file `listeners.py`) để phát sự kiện `db_row_created` khi một request được lưu thành công vào cơ sở dữ liệu.
- Singleton `bus` có thể được import và lắng nghe bởi các thành phần giao diện, websocket, v.v., để cập nhật UI theo thời gian thực.

## 4. Rủi ro (Risks & Edge Cases)
- **Chặn luồng đồng bộ:** Các listener được gọi theo cách đồng bộ. Nếu một listener thực thi các tác vụ mất nhiều thời gian (như I/O hoặc tính toán nặng), nó sẽ chặn tiến trình gọi `publish` và gây chậm chương trình.
- **Xử lý Exception:** Các lỗi từ listener được bắt (catch) và ghi log để tránh làm sập luồng phát sự kiện. Tuy nhiên, nếu object chia sẻ bị thay đổi nửa vời trước khi lỗi xảy ra, có thể dẫn đến trạng thái không đồng nhất.

## 5. Chi tiết các Class và Hàm

- **`Class EventBus`**: Đối tượng quản lý danh sách các listener và điều phối sự kiện.
  - **`__init__(self)`**: Khởi tạo thuộc tính `_listeners` dạng dictionary để lưu trữ danh sách các hàm xử lý ứng với từng loại sự kiện.
  - **`subscribe(self, event_type: str, listener: Callable)`**: Cho phép đăng ký một hàm (`listener`) để lắng nghe một loại sự kiện cụ thể (`event_type`). Nếu chưa có key này, nó sẽ tạo một list mới.
  - **`publish(self, event_type: str, **kwargs: Any)`**: Phát sự kiện `event_type` tới tất cả các listener đã đăng ký. Hàm duyệt qua danh sách các listener và gọi chúng với tham số `kwargs`. Có sử dụng `try-except` để bắt và ghi log nếu có lỗi xảy ra ở bất kỳ listener nào.

- **`bus = EventBus()`**: Một instance singleton của `EventBus` được định nghĩa ở cuối file, dùng để chia sẻ một kênh giao tiếp chung trên toàn ứng dụng proxy.
