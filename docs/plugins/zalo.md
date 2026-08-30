# Tài liệu: `proxify/plugins/zalo.py`

## 1. Tóm tắt tổng quan
File `zalo.py` chịu trách nhiệm cài đặt plugin trích xuất dữ liệu từ Zalo Web. Plugin can thiệp vào request để đón lõng dữ liệu được giải mã và can thiệp response để gắn (inject) mã độc/tác vụ thu thập dữ liệu (JS hook) vào web client.

## 2. Mục đích & Ý nghĩa
- Tự động hóa việc lấy dữ liệu Zalo (như danh sách thành viên nhóm, nội dung tin nhắn, nhóm chat).
- Tích hợp giao diện quản trị riêng (Tab Zalo Extractor) vào Dashboard của Proxify để người dùng kiểm soát và xem dữ liệu.
- Quản lý các lệnh thao tác quét nhóm, quản lý tiến trình làm việc dưới dạng job.

## 3. Mối liên hệ
- Kế thừa `BasePlugin` và đăng ký với định danh `zalo`.
- Phụ thuộc mạnh vào các hàm nghiệp vụ `handle_capture_dump` và `modify_zalo_response` từ `proxify.platforms.zalo.extractor`.
- Giao tiếp mật thiết với Zalo DB (`proxify.platforms.zalo.zalo_db`) để lưu và truy vấn thành viên, trạng thái công việc.

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro bảo mật:** Cần thận trọng vì có thao tác inject script (hook) vào môi trường trình duyệt Zalo của người dùng.
- **Database khoá (Locking):** Nếu có nhiều request đồng thời gửi dữ liệu dump lớn, SQLite Zalo DB có thể bị nghẽn khóa (locking).
- **Zalo cập nhật mã nguồn:** Việc phân tích request JSON và mã HTML trả về cực kỳ nhạy cảm với sự thay đổi của kiến trúc Zalo. Nếu họ đổi định dạng/API, toàn bộ tính năng này sụp đổ.

## 5. Chi tiết các Class và Hàm
### Class `ZaloPlugin(BasePlugin)`
- **Hàm `on_request(self, flow: Any) -> None`**:
  - Bắt các POST request từ các script được tiêm vào Zalo trả về proxy.
  - Sử dụng hàm `handle_capture_dump(flow)` để xử lý và lưu dữ liệu.
- **Hàm `on_response(self, flow: Any) -> None`**:
  - Bắt các response html/js của hệ thống Zalo.
  - Gọi `modify_zalo_response(flow)` để tiêm các đoạn hook (như đè hàm giải mã nội dung) vào ứng dụng web của họ.
- **Hàm `get_ui_tabs(self) -> List[Dict[str, str]]`**:
  - Trả về cấu hình UI cho menu dashboard (Tab: Zalo Extractor).
- **Hàm `get_api_routes(self) -> List[web.RouteDef]`**:
  - Trả về một loạt endpoint để quản trị trên web UI, trỏ đến các hàm xử lý bên dưới.
- **Hàm `_handle_zalo_page`**: Đọc và trả về file `zalo.html` cho UI Dashboard.
- **Hàm `_handle_zalo_stats`**: Truy xuất và trả về thống kê số liệu của Zalo DB.
- **Hàm `_handle_zalo_groups`**: Lấy danh sách nhóm chat Zalo.
- **Hàm `_handle_zalo_group_members`**: Lấy danh sách thành viên của một nhóm.
- **Hàm `_handle_zalo_export`**: Trả về file xuất định dạng CSV hoặc JSON danh sách thành viên một nhóm (trả về dưới dạng attachment).
- **Hàm `_handle_zalo_users`**: Lấy danh sách toàn bộ user (tất cả các nhóm).
- **Hàm `_handle_zalo_scan`**: Nhận request tạo job mới (nhập link hoặc ID nhóm cần quét), khởi tạo job trong DB.
- **Hàm `_handle_zalo_jobs`**: Lấy danh sách lịch sử scan.
- **Hàm `_handle_zalo_cancel_job`**: Cập nhật trạng thái một job thành `cancelled` theo ý người dùng.
