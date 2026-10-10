# Tài Liệu Cập Nhật: Session State & Hiển Thị LIVE

## Tóm tắt thay đổi
- Sửa file `frontend/src/pages/Dashboard.tsx`.
- Thêm cơ chế lưu trữ Session State bằng `sessionStorage` cho toàn bộ các filter trong UI (search, method, status, autoScroll, gqlFilter, dbIntegrationEnabled).
- Sửa lại giao diện render cho các request chưa có ID (ID = 0) thành chữ `LIVE` với hiệu ứng chớp tắt (pulse) như giao diện gốc.
- Sửa lại bảng Detail Panel bên phải để hiển thị thông báo "⚡ Request LIVE" khi người dùng click vào một request chưa kịp ghi vào DB.

## Mục đích & Ý nghĩa
- **Session State**: Giúp mỗi tab trình duyệt (mỗi client) giữ lại thiết lập tìm kiếm và lọc riêng biệt của mình, không bị mất khi vô tình tải lại trang. Các state này được gắn kết (sync) liên tục vào bộ nhớ phiên của trình duyệt (`sessionStorage`).
- **Giao diện LIVE**: Khôi phục lại đúng trải nghiệm của bản gốc, giúp người dùng dễ dàng phân biệt được request nào là cũ (đã có ID) và request nào vừa bắt được, đang trên đường truyền qua Proxy.

## Mối liên hệ
- Sử dụng trực tiếp hook `useEffect` và API `sessionStorage` của HTML5.
- Cần có class `.pulse` trong CSS (đã có trong `index.css`) để tạo hiệu ứng nhấp nháy cho chữ LIVE.

## Rủi ro (Risks & Edge Cases)
- `sessionStorage` chỉ lưu trữ trong thời gian sống của tab trình duyệt. Nếu người dùng mở tab mới, các bộ lọc sẽ bị reset (vì không dùng `localStorage`). Đây là hành vi tiêu chuẩn của session.
- Đối với `dbIntegrationEnabled`, nó vừa được lưu vào `sessionStorage`, vừa gọi API Backend. Việc này giúp UI không bị giật khi tải lại trang, nhưng nếu Backend có giá trị khác, nó sẽ đè lại giá trị local (trong `useEffect` fetch `getConfig`), đảm bảo Backend luôn là "nguồn chân lý" (Source of Truth) cho cờ ghi DB.
