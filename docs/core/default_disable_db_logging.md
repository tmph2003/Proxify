# Tài Liệu Cập Nhật: Mặc Định Tắt Ghi DB (Default Disable DB Logging)

## Tóm tắt thay đổi
- **`backend/proxify/core/traffic_storage/__init__.py`**: Đổi giá trị mặc định của biến môi trường `DB_INTEGRATION_ENABLED` trong `RequestStorage.__init__` từ `"true"` sang `"false"`.
- **`docker-compose.yml`, `.env`, `.env.example`**: Đổi cấu hình `DB_INTEGRATION_ENABLED=true` sang `false` (và `${DB_INTEGRATION_ENABLED:-false}` trong `docker-compose.yml`) để container `proxify` tôn trọng trạng thái tắt mặc định khi khởi chạy, không bị ghi đè bởi biến môi trường trong `.env`.
- **`backend/proxify/capture_addon.py`**: Đồng bộ logic xác định cờ `db_save` trong `CaptureAddon.response` để lấy từ `getattr(self.storage, "db_integration_enabled", False)` thay vì gán cứng `db_save = True` khi không truyền callback `_is_db_enabled_fn`.
- **`frontend/src/pages/Dashboard.tsx`**:
  - Đổi giá trị khởi tạo `dbIntegrationEnabled` từ `sessionStorage.getItem('dbIntegrationEnabled') !== 'false'` sang `sessionStorage.getItem('dbIntegrationEnabled') === 'true'`.
  - Cập nhật thông báo ở khung chi tiết (`Detail Panel`) khi chọn một request `LIVE` (`selectedId === 0`) để phản ánh chính xác trạng thái khi tính năng Ghi DB đang tắt.

## Mục đích & Ý nghĩa
- **Giảm tải I/O và dung lượng lưu trữ PostgreSQL**: Trong chế độ Universal Capture (bắt toàn bộ lưu lượng mạng qua proxy), việc bật ghi DB mặc định ngay từ khi khởi động sẽ đẩy một lượng lớn HTTP/HTTPS request/response (bao gồm cả header và body) vào hàng đợi `AsyncWriterWorker` và ghi xuống đĩa. Tắt mặc định giúp hệ thống khởi động nhẹ nhàng, zero-disk-write cho lưu lượng thông thường, chỉ ghi vào DB khi người dùng chủ động bật ("Opt-in Persistence") trên Dashboard.
- **Đồng nhất Single Source of Truth (SSoT)**: Trước đây, `docker-compose.yml` ép cứng `DB_INTEGRATION_ENABLED=true` và Frontend `sessionStorage` dùng phép phủ định `!== 'false'` khiến trạng thái mặc định luôn bị bật lại ở cả 3 tầng (Infrastructure, Application, Presentation). Việc đồng bộ cả 3 tầng về `false` loại bỏ hiện tượng lệch pha trạng thái (state flicker) khi mở Dashboard lần đầu.

## Mối liên hệ
- **`V1GlobalObserver` (`backend/proxify/server.py`)**: Đọc trực tiếp `getattr(self.db_writer.storage, 'db_integration_enabled', False)`. Khi cờ này là `False`, `DashboardBroadcaster` vẫn phát sự kiện `new_request` qua WebSocket (với `id = 0` / trạng thái `LIVE`) lên giao diện thời gian thực, nhưng `DatabaseWriter` sẽ bỏ qua bước ghi vào PostgreSQL.
- **`Dashboard` API (`backend/proxify/dashboard.py`)**: Các endpoint `/api/config`, `/api/health` và `/api/toggle_db` đọc/ghi thuộc tính `self.storage.db_integration_enabled` và đồng bộ trạng thái với React SPA (`frontend/src/pages/Dashboard.tsx`).
- **Các Extension chuyên biệt (Zalo, Facebook, YouTube)**: Các extension sử dụng CQRS `AsyncEventBus` hoặc pool riêng không bị ảnh hưởng bởi cờ `db_integration_enabled` của `RequestStorage` (vốn chỉ kiểm soát bảng `requests` chung của Traffic Dashboard).

## Rủi ro (Risks & Edge Cases)
- **Không xem được chi tiết Request (Headers/Body) và không Export được khi tắt Ghi DB**: Do thiết kế hiện tại của Dashboard lấy chi tiết request (`GET /api/requests/{id}`) và xuất dữ liệu (`/api/export/{format}`) trực tiếp từ PostgreSQL dựa trên `id > 0`, các request bắt được khi đang tắt Ghi DB sẽ giữ `id = 0` (`LIVE`) và không thể xem chi tiết body/headers hay export cho đến khi người dùng bật nút **Ghi DB**. Giao diện đã được bổ sung thông báo rõ ràng ở `Detail Panel` để người dùng nắm được hành vi này.
- **Session Storage trên trình duyệt đang mở**: Nếu tab trình duyệt cũ của người dùng đã lưu `sessionStorage.setItem('dbIntegrationEnabled', 'true')` từ phiên trước, khi tải lại trang thì hook `useEffect` gọi `getConfig()` sẽ ngay lập tức đồng bộ lại giá trị `false` từ Backend (Source of Truth) về UI.
