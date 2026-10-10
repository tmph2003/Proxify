# Tài liệu Cập nhật: Loại bỏ nút "Tải lại bảng" trên Facebook Dashboard

## 1. Tóm tắt thay đổi
- Loại bỏ nút thủ công `🔄 Tải lại bảng` trên thanh tiêu đề của bảng dữ liệu bài viết Facebook (`frontend/src/pages/Facebook.tsx`).

## 2. Mục đích & Ý nghĩa
- **Tối ưu hóa UI/UX:** Nút "Tải lại bảng" chiếm diện tích và tạo cảm giác thừa thãi khi hệ thống đã hỗ trợ cơ chế tự động cập nhật dữ liệu (auto-fetch khi mount, khi chuyển trang, đổi bộ lọc nhóm/tác giả, đổi tiêu chí sắp xếp và sau khi tiến trình crawl hoàn tất).
- **Trực quan hơn:** Giúp thanh công cụ khu vực hiển thị bảng dữ liệu trở nên thoáng đãng, tập trung vào ô tìm kiếm / lọc nhóm.

## 3. Mối liên hệ
- File chỉnh sửa: `frontend/src/pages/Facebook.tsx`.
- Các cơ chế tải dữ liệu `loadData()` và `fetchGroups()` vẫn hoạt động tự động trong vòng đời React (`useEffect`) và các event handler liên quan, không làm ảnh hưởng tới luồng dữ liệu của component.

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro:** Người dùng muốn ép tải lại bảng ngay lập tức khi nghi ngờ có dữ liệu ngầm mà không đổi filter hay reload trang web.
- **Biện pháp xử lý:** Người dùng có thể F5 trang hoặc chuyển đổi filter/trang để kích hoạt lại API `loadData()`. Khi có tác vụ crawl mới, hệ thống tự động refetch sau khi crawl xong.
