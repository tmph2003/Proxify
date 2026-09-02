# Tài Liệu Cập Nhật: Tích Hợp Hoàn Chỉnh Các Tính Năng Filter & Export Trong Dashboard

## Tóm tắt thay đổi
- Chỉnh sửa `frontend/src/pages/Dashboard.tsx` để "nối dây" các Filter và nút Export vào đúng logic.
- Khôi phục bộ lọc theo phương thức (`methodFilter`), mã lỗi (`statusFilter`), tên miền (`domainFilter`), và loại request (`gqlFilter`). Cập nhật hàm `requests.filter` để lọc đa điều kiện.
- Bổ sung gọi API `getDomains()` khi khởi tạo trang để render danh sách tên miền vào thẻ Select (của tính năng Lọc hiển thị) và thẻ Dropdown Checkbox (của tính năng cấu hình Ghi DB).
- Viết lại hàm `handleExport` để khi bấm các nút (JSON, HAR, Python, cURL), trang sẽ gọi API backend qua `window.open` với tham số `ids` là request đang được chọn. Các nút bấm sẽ bị làm mờ (opacity) nếu người dùng chưa chọn request nào hợp lệ.
- Bổ sung logic `autoScroll` bằng `useRef`, khi có request mới (và cờ autoScroll đang bật) thì khung danh sách request sẽ tự động nhảy lên đỉnh (scrollTop = 0).

## Mục đích & Ý nghĩa
- **Làm cho UI "Sống"**: Ở các lần commit trước, UI chỉ có giao diện HTML mà chưa gắn các logic tương tác phức tạp. Việc này đưa chức năng Filter và Export vào hoạt động thực tế, giúp UI hoàn thiện 100% chức năng so với bản gốc.

## Mối liên hệ
- Sử dụng các API: `getDomains`, `exportRequests`, `toggleDb`.
- Liên quan mật thiết tới mảng dữ liệu `requests` từ Context `useAppContext`.

## Rủi ro (Risks & Edge Cases)
- Hàm `exportRequests` của backend (`/api/export/<format>`) hiện chỉ hỗ trợ truyền mảng `ids` (export 1 dòng đang chọn) chứ chưa hỗ trợ export nguyên mảng dữ liệu đang lọc trên Frontend (do giới hạn độ dài Query string của URL). Điều này tuân thủ nguyên mẫu của Dashboard HTML trước đây.
