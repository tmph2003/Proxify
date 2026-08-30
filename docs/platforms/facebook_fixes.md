# Tài liệu cập nhật module Facebook Crawler

## 1. Tóm tắt thay đổi
- Cập nhật luồng phân giải (resolve) Facebook Group ID dạng chữ (Slug) sang dạng số (Numeric ID).
- Sửa lỗi văng tiến trình cào dữ liệu (tuple index out of range) trong `repository.py` bằng cách truyền đúng trường `group_numeric_id` bị thiếu.
- Thêm thông báo tiến trình chi tiết (trang số mấy) vào `crawler.py` để giao diện người dùng hiển thị trực quan hơn.

## 2. Mục đích & Ý nghĩa
- **Phân giải Slug:** Nhiều người dùng copy link nhóm có chứa Slug (VD: `apikhongngonxoagroup`) thay vì Numeric ID, khiến Graph API của Facebook trả về rỗng. Cập nhật này tự động dò tìm ID số đằng sau trang nhóm đó để API chạy trơn tru.
- **Sửa lỗi lưu bài viết (`repository.py`):** Fix lỗi số lượng tham số trong câu lệnh SQL `INSERT` không khớp với giá trị truyền vào, giúp bài viết được lưu trữ thành công mà không bị sập hàm xử lý.
- **Tiến trình trực quan (`crawler.py`):** Giúp người dùng biết bot đang thực hiện tới bước nào, không có cảm giác bị "treo" (báo lỗi lúc xanh lúc đỏ do trạng thái bất định).

## 3. Mối liên hệ
- Các sửa đổi này tác động trực tiếp đến plugin Facebook (`proxify/plugins/facebook.py`), module Crawler (`proxify/platforms/facebook/crawler.py`) và module Database (`proxify/platforms/facebook/repository.py`).
- Kết nối chặt chẽ với API polling trạng thái của frontend, giúp giao diện tại `facebook.html` luôn hiển thị đúng thông điệp (trang đang cào).

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro phân giải ID:** Nếu Facebook thay đổi cấu trúc HTML, biểu thức chính quy (Regex) tìm `groupID` có thể không hoạt động. Tuy nhiên, nếu thất bại, hệ thống vẫn báo lỗi rõ ràng yêu cầu người dùng nhập ID số.
- **Rủi ro Database:** Đảm bảo rằng lược đồ cơ sở dữ liệu (`schema.sql`) phải có sẵn cột `group_numeric_id`, nếu không sẽ ném ra `UndefinedColumn`. (Đã được kiểm chứng trong lược đồ hệ thống).
