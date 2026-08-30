# Tài liệu: `proxify/platforms/facebook/session_state.py`

## 1. Tóm tắt tổng quan
File `session_state.py` đóng vai trò tạo và quản lý các tham số phiên làm việc ẩn (dynamic form parameters) như `__req`, `__s`, và `__spin_t` cần thiết cho các biểu mẫu (form) GraphQL của Facebook. Đây là lớp mô phỏng lại bộ sinh tham số nội bộ của trình duyệt Facebook Web.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Thay đổi liên tục các giá trị định danh phiên cho mỗi yêu cầu được gửi đi. 
- **Ý nghĩa**: Facebook theo dõi rất khắt khe các biến này. Gửi một chuỗi template cứng nhắc liên tục nhiều lần mà không thay đổi biến đếm (counter) hay thời gian sẽ ngay lập tức kích hoạt cờ đỏ (bot detection). Việc này đảm bảo các yêu cầu từ Crawler trông y hệt như một người dùng đang lướt trình duyệt thật sự.

## 3. Mối liên hệ
- Nó được khởi tạo (instance) bên trong hàm `_execute_crawl_group_feed` của `FacebookCrawler` (trong file `crawler.py`).
- Trong vòng lặp qua từng trang bài viết (pagination loop), hàm `update_params()` của class này được gọi để đột biến (mutate) cấu trúc biến (variables) trước khi gửi Request.

## 4. Rủi ro (Risks & Edge Cases)
- **Logic Facebook thay đổi**: Thuật toán băm và định dạng chuỗi `__s` hoặc cách tính `__req` base-36 có thể bị Facebook đổi thuật toán ở phía client trong tương lai. Cần phải phân tích ngược (Reverse Engineer) lại nếu có sự thay đổi từ Facebook.
- **Tràn biến đếm (Counter Overflow)**: Mặc dù trong Python int là vô hạn, nếu biến đếm quá lớn, Base-36 sinh ra chuỗi quá dài khác biệt so với hành vi chuẩn của trình duyệt. Dù vậy, ứng dụng giới hạn crawl dưới 100 pages mỗi lượt nên khó xảy ra.

## 5. Chi tiết các Class và Hàm

### 1. `SessionStateManager` (Class)
- **Mô tả**: Quản lý việc tính toán, tăng dần các biến theo dõi phiên `__req`, sinh token ngẫu nhiên `__s` và tạo `__spin_t` thời gian thực.
- **Thuộc tính**:
  - `_ALPHABET`: Bảng chữ cái và số để mã hóa cơ số 36.
  - `_counter_offset`: Điểm khởi đầu của biến đếm (bắt đầu từ một số ngẫu nhiên 5-15).
  - `_request_count`: Đếm số request thực tế đã tạo trong suốt phiên.

- **Các hàm**:
  - `__init__(self, counter_offset: Optional[int] = None)`: Hàm khởi tạo. Nếu không chỉ định bù trừ (offset), nó tự random một số từ 5 đến 15 để đóng giả một người dùng đang ở giữa chừng lúc bắt đầu thu thập.
  - `update_params(self, data: dict) -> None`: Phương thức chính. Thay đổi giá trị của `__req`, `__s`, `__spin_t` trực tiếp (in-place) bên trong dictionary `data` truyền vào.
  - `@property def request_count(self) -> int`: Trả về số lượng request đã chạy.
  - `reset(self) -> None`: Reset bộ đếm và random lại offset mới (dùng khi bắt đầu luồng cào mới).
  - `@classmethod _encode_base36(cls, n: int) -> str`: Hàm nội bộ để chuyển một số thập phân (n) sang chuỗi Base-36 (dùng các ký tự 0-9a-z) theo định dạng mã của FB.
  - `@staticmethod _gen_session_token() -> str`: Hàm nội bộ sinh chuỗi ID phiên ngẫu nhiên `__s` bao gồm 3 đoạn ký tự chữ/số dài 6 ký tự phân tách bằng dấu hai chấm (vd: `abc123:def456:ghi789`).
