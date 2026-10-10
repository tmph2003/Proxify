# Tài liệu: interfaces.py

## 1. Tóm tắt tổng quan
Module `interfaces.py` chứa các định nghĩa giao diện (Interfaces / Protocols) cơ sở được sử dụng trong gói `core`.

## 2. Mục đích & Ý nghĩa
Định nghĩa sẵn cấu trúc chuẩn mà các lớp hay thành phần khác phải tuân thủ thông qua `typing.Protocol`. Việc này tăng cường khả năng Dependency Inversion, type-hinting cho IDE và công cụ kiểm tra (như mypy), giúp mã nguồn rõ ràng và dễ bảo trì hơn.

## 3. Mối liên hệ
- Protocol `EventListener` được kế thừa và triển khai bởi các lớp `DashboardBroadcaster` và `DatabaseWriter` trong file `listeners.py`.

## 4. Rủi ro (Risks & Edge Cases)
- **Kiểm tra Runtime lỏng lẻo:** `Protocol` trong Python chủ yếu dùng cho kiểm tra tĩnh (static type checking). Nếu không sử dụng các checker như `mypy`, sẽ không có cảnh báo nếu một class không hoàn toàn tuân thủ Protocol ở thời điểm chạy (runtime) trừ khi gọi hàm trực tiếp.

## 5. Chi tiết các Class và Hàm

- **`Class EventListener(Protocol)`**: Định nghĩa giao thức chuẩn dành cho mọi listener xử lý sự kiện proxy.
  - **`__call__(self, *args: Any, **kwargs: Any) -> None`**: Phương thức magic yêu cầu lớp triển khai phải có khả năng gọi được như một hàm. Phương thức này sẽ được kích hoạt khi sự kiện mà nó quan tâm xảy ra.
