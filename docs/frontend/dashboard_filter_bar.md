# Tài Liệu Cập Nhật: Khôi Phục Giao Diện Filter Bar (Dashboard.tsx)

## Tóm tắt thay đổi
- Cập nhật file `frontend/src/pages/Dashboard.tsx`.
- Thêm đầy đủ các cấu trúc DOM của khối `.filter-bar` từ HTML cũ sang JSX.
- Thêm các React state (`methodFilter`, `statusFilter`, `domainFilter`, `gqlFilter`, `autoScroll`, `dbIntegrationEnabled`) để quản lý các dropdown, toggle filter.

## Mục đích & Ý nghĩa
- **Mục đích**: Mang lại giao diện "y hệt bản cũ" đúng như yêu cầu của người dùng, bằng cách thêm lại toàn bộ các thẻ `<select>`, `<button>` cho Lọc Method, Status, Domain, Ghi DB, Export (JSON, HAR) đã bị thiếu trong quá trình migrate ban đầu.
- **Ý nghĩa**: Giúp duy trì tính nhất quán về UI/UX đối với những người dùng đã quen thuộc với giao diện cũ (HTML/CSS), đồng thời tận dụng được nền tảng React mới.

## Mối liên hệ
- Liên kết trực tiếp với file `frontend/src/index.css` (đã được bổ sung thêm đoạn CSS `.filter-bar` từ HTML cũ vào trước đó).
- Nằm trong kiến trúc UI chính, tác động đến trang chủ Dashboard của hệ thống Proxify.

## Rủi ro (Risks & Edge Cases)
- Các nút chức năng xuất dữ liệu (Export JSON/HAR/Python) và logic lọc (Lọc Ghi DB) hiện tại chỉ đang dựng UI và lưu trữ state cục bộ (dummy functions). Sẽ cần triển khai thêm phần tích hợp API tương ứng nếu muốn các nút này có tác dụng thực tế (giống như trong file `index.html` cũ).
- Có thể cần tuỳ biến lại hook `useRequests` để áp dụng filter `methodFilter` và `statusFilter` thay vì chỉ filter theo search box như hiện tại.
