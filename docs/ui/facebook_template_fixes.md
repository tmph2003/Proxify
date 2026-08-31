# Lỗi chọn Group trong Search Box (Facebook UI)

## 1. Tóm tắt thay đổi
Đã sửa lỗi trong `proxify/ui/templates/facebook.html` khiến cho khi người dùng chọn một group không có `group_id` (trị số `null` trong JSON) từ ô tìm kiếm (Dropdown), ô Group ID ở Sidebar bên trái không được xóa hoặc cập nhật đúng.

## 2. Mục đích & Ý nghĩa
- **Vấn đề trước đây:** Hàm `renderGroupDropdown` gán chuỗi nội suy template là `'null'` khi biến `g.group_id` là null. Hàm `selectGroupFilter` có một câu lệnh điều kiện `if (sidebarInput && groupId !== 'null')` để chặn cập nhật vào ô Sidebar khi Group không có ID. Hệ quả là khi click chọn một group không có ID, ô nhập bên trái không được xóa trống mà vẫn giữ nguyên ID cũ, gây nhầm lẫn hoặc làm gửi sai ID trong các request cào dữ liệu tiếp theo.
- **Giải pháp:** Cập nhật lại logic truyền dữ liệu `selectGroupFilter('${g.group_id || ''}', ...)` để trả về chuỗi rỗng thay vì chuỗi `'null'`. Thay thế điều kiện ở hàm `selectGroupFilter` để cho phép cập nhật ô `sidebarInput.value` thành chuỗi rỗng nếu click vào nhóm không có ID. Việc này giúp UI đồng nhất, xóa sạch ID cũ bị sót lại.

## 3. Mối liên hệ
- File chỉnh sửa: `proxify/ui/templates/facebook.html` (chủ yếu là `renderGroupDropdown` và `selectGroupFilter`).
- Ảnh hưởng trực tiếp đến người dùng thao tác ở trang **Dashboard -> Auto Crawl Facebook**, cụ thể là khi tìm group ở mục "Dữ liệu thu thập được".

## 4. Rủi ro (Risks & Edge Cases)
- Các nhóm được crawler tự động bắt (từ luồng GraphQL) nhưng thiếu `group_id` sẽ hiển thị trong danh sách Group Filter và có giá trị ID là rỗng (empty string). Người dùng sẽ không thể chủ động bắt đầu crawl lại nhóm này thông qua Group ID, vì nó yêu cầu một ID hợp lệ (hệ thống sẽ báo lỗi Missing group_id nếu ID là trống). Tuy nhiên, đây là logic an toàn và chính xác cho hệ thống vì crawler không thể chạy nếu không có ID xác định.
