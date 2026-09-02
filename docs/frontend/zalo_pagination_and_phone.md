# Tài Liệu Cập Nhật: Thêm phân trang và sửa lỗi hiển thị SĐT Zalo

## Tóm tắt thay đổi
- Chỉnh sửa `frontend/src/pages/Zalo.tsx`:
  - Thêm state `page` và hằng số `pageSize = 100` để thực hiện phân trang trực tiếp ở frontend (cắt mảng `filteredMembers.slice(...)`).
  - Sửa lại trường dữ liệu số điện thoại từ `m.phone_number` thành `m.phone` để khớp với JSON object trả về từ Backend API (`ZaloMember` struct).
  - Thêm cụm nút chuyển trang (Trang trước, Trang sau, Số trang) bên cạnh ô Tìm kiếm thành viên.

## Mục đích & Ý nghĩa
- **Tránh giật lag:** Khi số lượng thành viên lên đến hàng chục nghìn, việc render toàn bộ ra bảng DOM sẽ gây đơ trình duyệt. Phân trang mỗi 100 dòng giúp UI mượt mà hơn.
- **Sửa lỗi hiển thị:** Việc gõ nhầm tên trường (`phone_number` thay vì `phone`) khiến cột số điện thoại trước đây trống trơn, nay đã được khắc phục.

## Mối liên hệ
- Lấy trực tiếp dữ liệu từ Context / API đã viết sẵn trong `useZalo`. Backend API không thay đổi.

## Rủi ro (Risks & Edge Cases)
- Logic phân trang hiện tại chạy trên **Client-side**, có nghĩa là toàn bộ thành viên vẫn được load về RAM trình duyệt. Nếu số lượng thành viên vượt quá 100.000, có thể cần chuyển phân trang sang Server-side. Tuy nhiên ở quy mô nhóm Zalo hiện tại (max 1000 người), việc này là an toàn và tối ưu nhất.
