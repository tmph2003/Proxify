# Tài liệu: Sửa lỗi injection sai biến GraphQL khi cào Facebook Feed

## Tóm tắt thay đổi
- Chỉnh sửa hàm `_set_variables` trong `proxify/platforms/facebook/crawler.py`.
- Xoá hai dòng ép cứng gán biến không hợp lệ: `variables["UFI2CommentsProvider_commentsKey"] = "GroupFeedRecommededEntitiesQuery"` và `variables["groupID"] = group_id`.
- Cập nhật thêm tính năng Lọc (Filter) theo ngày tháng trên UI: Sửa đổi `facebook.html` và `api.py` để bảng hiển thị tự động lấy đúng các bài viết nằm trong dải `start_date` và `end_date` mà người dùng đã thiết lập, thay vì nạp tất cả như trước.

## Mục đích & Ý nghĩa
- **Về GraphQL Variables:** Việc cố tình nhồi nhét key `UFI2CommentsProvider_commentsKey` vào payload của `GroupsCometFeedRegularStoriesPaginationQuery` là hoàn toàn vô lý vì đây là biến dùng cho thao tác cào Comment chứ không phải Feed. Việc này dẫn đến rủi ro Facebook GraphQL trả về lỗi hoặc lờ đi cấu hình `sortingSetting` do payload không hợp lệ. Việc xoá 2 key thừa này giúp request sạch và bám sát template chuẩn mà trình duyệt đã ghi nhận.
- **Về UI Filter:** Giải quyết triệt để hiểu lầm của người dùng. Khi họ set quét ngày 26-27, bảng UI vẫn tải tất cả bài ngày 29-30 (do các lần cào trước để lại), khiến người dùng tưởng Crawler bị lỗi (fetch sai ngày). Giờ đây UI sẽ filter song hành cùng cấu hình cào.

## Mối liên hệ
- Liên quan mật thiết tới core fetching của Crawler và Router API lấy danh sách bài viết.

## Rủi ro (Risks & Edge Cases)
- Code đã sạch sẽ và không gây bất kỳ tác dụng phụ nào so với logic cũ. Thậm chí giúp tăng tính an toàn và minh bạch cho luồng hiển thị dữ liệu (UI syncs with User intent).
