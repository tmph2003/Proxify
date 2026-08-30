# Tài liệu: Tách biệt trạng thái lọc và trạng thái thu thập dữ liệu trong Facebook Extractor

## Tóm tắt thay đổi
Trong file `proxify/ui/templates/facebook.html`, logic lưu trữ trạng thái của bộ lọc nhóm (Group Filter) ở bảng dữ liệu (bên phải) đã được thay đổi. Thay vì chia sẻ chung giá trị `localStorage.getItem('fb_groupId')` với ô nhập liệu "Group ID" dùng để thu thập dữ liệu (bên trái), bộ lọc hiện tại sử dụng `sessionStorage` (`fb_filterGroupId` và `fb_filterGroupName`). Khối code đồng bộ tự động từ bộ lọc sang ô input "Group ID" cũng được loại bỏ để tránh việc người dùng chỉ muốn xem dữ liệu cũ lại vô tình đổi luôn cấu hình nhóm chuẩn bị thu thập.

## Mục đích & Ý nghĩa
Thay đổi này giải quyết vấn đề "mặc định là Tất cả các nhóm" mỗi khi người dùng mở phiên làm việc mới (session mới). `sessionStorage` chỉ tồn tại trong suốt một phiên của tab trình duyệt. 
Nhờ vậy:
1. Khi người dùng mới mở trình duyệt hoặc tab mới lên, bộ lọc nhóm luôn mặc định hiển thị "Tất cả các nhóm" (chưa lọc).
2. Khi người dùng chọn một nhóm để lọc (ví dụ: "group data"), rồi chuyển qua lại giữa các trang/tab khác của ứng dụng (Zalo Extractor, Requests) **trong cùng một session trình duyệt đó**, giá trị đang lọc ("group data") vẫn được giữ nguyên nhờ lưu tại `sessionStorage`.
3. Phân tách rõ ràng giữa "nhóm đang muốn xem" (bên phải) và "nhóm đang chuẩn bị cào dữ liệu" (bên trái).

## Mối liên hệ
- **`proxify/ui/templates/facebook.html`**: Script quản lý state được update để xử lý `currentGroupId` dựa trên `sessionStorage`.
- Không ảnh hưởng tới backend API (`proxify/platforms/facebook/api.py`), chỉ thuần túy là update logic frontend để cải thiện trải nghiệm người dùng.

## Rủi ro (Risks & Edge Cases)
- **Hành vi người dùng đã quen với bản cũ**: Một số người dùng có thể đã quen với việc click vào tên nhóm bên bảng dữ liệu (bên phải) thì ô nhập Group ID bên trái sẽ tự động đổi theo để cào tiếp. 
*Cập nhật:* Tính năng đồng bộ ngược này đã được bổ sung lại theo yêu cầu. Khi chọn một nhóm bất kỳ ở bộ lọc, `Group ID` bên trái sẽ tự động đổi theo. Nếu chọn "Tất cả các nhóm", ô `Group ID` bên trái sẽ tự động được xóa rỗng để tránh nhầm lẫn. Việc đồng bộ này cũng đồng thời cập nhật `localStorage` để lưu trữ cho lần truy cập sau.
- Dữ liệu ở `sessionStorage` sẽ bị xóa hoàn toàn khi đóng tab. Điều này được coi là tính năng theo đúng request (mặc định mở lại là Tất cả), nhưng cần đảm bảo người dùng hiểu rõ sự khác biệt so với `localStorage`.
