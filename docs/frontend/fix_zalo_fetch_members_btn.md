# Cập nhật: Sửa lỗi tính năng Lấy Toàn Bộ Thành Viên & Quét Nhóm Zalo

## Tóm tắt thay đổi
- Chỉnh sửa file `frontend/src/hooks/useZalo.ts`: 
  - Thay thế hàm API endpoint trong `fetchZaloUrl` từ `/zalo/jobs` thành `/zalo/scan` để map đúng với backend Zalo plugin.
  - Thêm một hàm mới `fetchMembers` gọi đến API `/zalo/commands/fetch_members`.
- Chỉnh sửa file `frontend/src/pages/Zalo.tsx`:
  - Liên kết nút "Lấy toàn bộ thành viên" với hàm `fetchMembers` mới.

## Mục đích & Ý nghĩa
- **Vấn đề:** Nút "Lấy toàn bộ thành viên" trước đó không hoạt động (bị dead-click). Nút "Quét" cũng có thể gọi sai API.
- **Nguyên nhân:** Cả hai nút này đang sử dụng chung hàm `fetchZaloUrl` trỏ đến API `POST /api/zalo/jobs`. Tuy nhiên ở Backend `zalo.py`, các routes khai báo lại là `POST /api/zalo/scan` (để tạo job scan mới) và `POST /api/zalo/commands/fetch_members` (để gửi command queue cho JS hook lấy member list).
- **Cách khắc phục:** Tách bạch 2 hành động: "Quét" gọi `/zalo/scan`, và "Lấy toàn bộ thành viên" gọi `/zalo/commands/fetch_members` để đẩy lệnh xuống trình duyệt. Đồng thời thông báo Toast/Alert cho người dùng biết thao tác đã thành công.

## Mối liên hệ
- Khắc phục sự bất đồng bộ giữa React Frontend (`Zalo.tsx`) và API Route của Zalo Backend Plugin (`zalo.py`).

## Rủi ro (Risks & Edge Cases)
- Hàm `fetchMembers` sau khi gửi API sẽ không tự động cập nhật được danh sách thành viên trên Frontend ngay lập tức mà phụ thuộc vào việc trình duyệt gửi ngược dữ liệu qua MITM Proxy và hệ thống cập nhật vào DB. Người dùng có thể cần nhấn nút làm mới (hoặc Zalo page tự fetch interval 3s) để xem sự thay đổi.
