# Chuẩn hóa Thống kê Topbar & Hiệu ứng `LIVE` trên Giao diện Dashboard SPA

## Tóm tắt thay đổi
- **Cập nhật `frontend/src/hooks/useRequests.ts`:**
  - Bổ sung hàm `normalizeStats(data)` chuyển đổi thống nhất tên trường trả về từ API `/api/stats` (`total_requests` → `requests`, `unique_domains` → `domains`, `graphql_requests` → `graphql`, ép kiểu số với giá trị mặc định `0`).
  - Bổ sung biến tính toán `effectiveStats` tự động suy ra tổng số request, số domain duy nhất và số request GraphQL trực tiếp từ danh sách `requests` đang hiển thị trong bộ nhớ khi chế độ ghi cơ sở dữ liệu (`DB_INTEGRATION_ENABLED`) đang tắt (`stats.requests === 0 && requests.length > 0`).
- **Cập nhật `frontend/src/index.css`:** Bổ sung quy tắc `@keyframes pulse` (`opacity: 1` ↔ `0.4`) cho chấm trạng thái `LIVE` trên giao diện Dashboard.

## Mục đích & Ý nghĩa
- **Khắc phục lỗi hiển thị trống số liệu thống kê:** Trước đây backend trả về khóa `total_requests`, `unique_domains`, `graphql_requests` (có thể là `null` khi chưa có bản ghi), trong khi hook React đọc `requests`, `domains`, `graphql` nên thanh Topbar bị hiển thị trống hoặc mất số liệu khi chưa bật lưu SQLite.
- **Hoạt động mượt mà ngay cả khi tắt lưu DB:** Giúp người dùng theo dõi trực tiếp lưu lượng thời gian thực qua WebSocket trên bộ nhớ RAM mà không bắt buộc ghi xuống ổ đĩa.
- **Hoàn thiện hiệu ứng thị giác:** Khôi phục animation nhấp nháy của chỉ báo kết nối WebSocket `LIVE`.

## Mối liên hệ
- **`frontend/src/hooks/useRequests.ts` ↔ `backend/proxify/dashboard.py`:** Đồng bộ hợp đồng dữ liệu JSON giữa endpoint `GET /api/stats` (và `RequestRepository.get_stats()`) với trạng thái giao diện `DashboardPage` / `MainLayout`.
- **`frontend/src/index.css` ↔ `frontend/src/pages/Dashboard.tsx`:** Cung cấp keyframe `pulse` cho phần tử chỉ báo trực tuyến.

## Rủi ro (Risks & Edge Cases)
- Khi chế độ ghi DB đang tắt, `effectiveStats` phản ánh tối đa 500 request gần nhất được giữ trong state React (`slice(0, 500)`) thay vì toàn bộ lịch sử từ khi khởi động server; khi bật lưu DB (`stats.requests > 0`), số liệu được lấy chính xác toàn cục từ SQLite.
