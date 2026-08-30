# Tài liệu: Sửa lỗi tham số sắp xếp (sorting) trên GraphQL Facebook

## Tóm tắt thay đổi
- Chỉnh sửa file `proxify/platforms/facebook/crawler.py`: Sửa lỗi đánh máy (typo) trong payload của biến GraphQL. Cụ thể, thay vì truyền tham số `variables["sorting_setting"]`, hệ thống hiện tại sẽ truyền đúng chuẩn camelCase mà Facebook yêu cầu là `variables["sortingSetting"] = "CHRONOLOGICAL"`.

## Mục đích & Ý nghĩa
- Mặc dù hệ thống đã có chủ đích ép Facebook trả về danh sách bài viết theo thứ tự "Bài mới nhất" (CHRONOLOGICAL), nhưng do sai tên biến (dùng snake_case thay vì camelCase), Facebook GraphQL đã bỏ qua cờ này và tiếp tục trả về dữ liệu theo mặc định là "Hoạt động mới nhất" (Top Posts).
- Sửa đúng tên biến `sortingSetting` giúp hệ thống hoàn toàn loại bỏ được tình trạng "bài viết cũ bị bump lên trang đầu". Dữ liệu sẽ được thu thập theo đúng thứ tự thời gian, giúp tăng tốc độ cào và khắc phục triệt để lỗi nhảy ngày của Crawler.

## Mối liên hệ
- Liên kết trực tiếp tới module RequestParser và API GraphQL của Facebook. Khắc phục tận gốc vấn đề mà tài liệu `crawler_progress_fix.md` đề cập.

## Rủi ro (Risks & Edge Cases)
- Một số Group đặc biệt (ví dụ Group nội bộ Workplace) có thể không hỗ trợ cờ `sortingSetting` trong câu truy vấn, nhưng đối với đa số Facebook Group thông thường, đây là tham số hợp lệ.
