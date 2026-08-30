# Tài liệu: `proxify/platforms/facebook/network.py`

## 1. Tóm tắt tổng quan
File `network.py` triển khai mẫu thiết kế Borg (hay Singleton có chung trạng thái) tạo ra một Client Mạng Toàn Cục (`GlobalNetworkClient`). Thành phần này đảm nhận trách nhiệm quản lý, điều phối và gửi các HTTP Request tới Facebook, sử dụng `StealthSessionManager`.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Đảm bảo trên toàn bộ ứng dụng, tại bất kỳ thời điểm nào cũng chỉ có duy nhất MỘT request mạng gửi đến hệ thống Facebook, và phải đảm bảo một khoảng thời gian chờ cố định (rate limit) giữa các requests liên tiếp.
- **Ý nghĩa**: Tính năng này ngăn chặn triệt để tình trạng ứng dụng "bắn phá" (spam) server Facebook bằng các luồng (coroutines) bất đồng bộ. Đây là cơ chế bảo vệ tối thượng giúp tránh bị khóa IP/Cookie do vi phạm rate-limit của Facebook, tạo nền tảng cho sự ổn định lâu dài.

## 3. Mối liên hệ
- Mọi thao tác gửi request GraphQL hoặc lấy trang HTML trong `FacebookCrawler` (ở `crawler.py`) đều không dùng thẳng thư viện HTTP mà bọc qua `GlobalNetworkClient.safe_request()`.
- Client này bọc bên trong một `StealthSessionManager` (từ `proxify.utils.stealth`) để kết hợp cả Rate Limiting toàn cục lẫn giả mạo TLS/Trình duyệt xịn (TLS impersonation).

## 4. Rủi ro (Risks & Edge Cases)
- **Tắc nghẽn hệ thống (Global Lock Bottleneck)**: Vì sử dụng khóa `asyncio.Lock` và ép buộc thời gian rảnh 2.5s, nếu có quá nhiều tác vụ (ví dụ: crawl cả group và comment cùng lúc từ nhiều nguồn), hàng đợi request sẽ dài vô tận. Ứng dụng sẽ bị chậm đi đáng kể, dù không bị block.
- **Xung đột State của Borg Pattern**: Nếu các instance khác nhau vô tình ghi đè `manager` bằng các cài đặt không tương thích, có thể xảy ra lỗi.
- **Timeout**: Trong lúc chờ khóa (Lock), nếu thời gian chờ quá lâu, request có thể bị timeout ở phía Client gọi hàm.

## 5. Chi tiết các Class và Hàm

### 1. `GlobalNetworkClient` (Class)
- **Mô tả**: Class đại diện cho Client mạng toàn cục, sử dụng mẫu Borg (`_shared_state`). Mọi instance được tạo ra từ class này đều trỏ chung về một từ điển thuộc tính, đảm bảo chúng cùng chia sẻ chung một Lock và Manager.
- **Thuộc tính nội bộ**:
  - `_shared_state`: Từ điển chứa toàn bộ state chia sẻ (thuộc về class).
  - `manager`: Đối tượng `StealthSessionManager` dùng để tạo HTTP request thực sự.
  - `_rate_limit_lock`: Đối tượng `asyncio.Lock` đảm bảo tính loại trừ lẫn nhau (Mutex).
  - `_last_request_time`: Thời điểm gửi request gần nhất (kiểu float).

- **Các hàm**:
  - `__init__(self, manager: Optional[StealthSessionManager] = None)`: Hàm khởi tạo. Nếu chưa khởi tạo lần nào (`initialized` chưa có), nó sẽ tạo mới Manager mặc định, Lock và thời gian. Nếu đã khởi tạo rồi và có truyền manager mới, nó sẽ thay thế bằng manager mới.
  - `async def safe_request(self, *args, **kwargs)`: Hàm bao bọc (wrapper) để gửi request. 
    - Đầu tiên nó sẽ yêu cầu cấp khóa (Lock) của Mutex.
    - Tiếp theo, tính toán thời gian từ lúc gửi request cuối. Nếu nhỏ hơn 2.5 giây, nó sẽ tự động `asyncio.sleep` cho đủ thời gian đó.
    - Gửi request thật qua `self.manager.request(*args, **kwargs)`.
    - Sau khi gửi xong, cập nhật lại `_last_request_time = time.time()` tại khối `finally` trước khi giải phóng khóa.
