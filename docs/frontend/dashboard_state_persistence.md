# Tài Liệu Cập Nhật: Sửa Lỗi Mất Trạng Thái State Của Filter Bar

## Tóm tắt thay đổi
- Sửa lại `frontend/src/pages/Dashboard.tsx`
- Bổ sung logic load config khi khởi tạo component (gọi API `getConfig` để khôi phục trạng thái `dbIntegrationEnabled`).
- Bổ sung hàm `handleToggleDb` để thay vì chỉ đổi state ở client, nay sẽ gọi API `/api/toggle_db` (qua hàm `toggleDb` trong `client.ts`) để báo cho server lưu lại trạng thái mới.
- Xóa biến `dbAllowedDomains` do chưa sử dụng đến để tránh lỗi Typescript (TS6133).

## Mục đích & Ý nghĩa
- **Mục đích**: Giải quyết dứt điểm vấn đề "bật ghi DB nhưng thoát ra vào lại thì lại bị mất state session".
- **Ý nghĩa**: Bất cứ tùy chọn nào người dùng tương tác trên Frontend (như bật/tắt DB) phải được đồng bộ và lưu trữ ở Backend. Khi refresh trang, React sẽ tự động gọi API fetch lại config cũ, giúp trải nghiệm liền mạch như app Desktop (trạng thái persist).

## Mối liên hệ
- Sử dụng các API khai báo trong `frontend/src/api/client.ts`.
- Giao tiếp trực tiếp với Backend qua `/api/toggle_db` và `/api/config`.

## Rủi ro (Risks & Edge Cases)
- Do hàm `handleToggleDb` cập nhật state local trước để tạo cảm giác "nhanh" (Optimistic UI), nếu server mất kết nối, state sẽ bị roll back lại, có thể gây nháy nút bấm, tuy nhiên điều này rất hiếm khi xảy ra vì server chạy ở localhost.
