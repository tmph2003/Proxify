# Tài liệu Đại phẫu Kiến trúc Lưu trữ Group ID (Refactor Database)

## Tóm tắt thay đổi
- Thực thi đại phẫu (refactor) toàn diện cách xử lý `group_id` cho Facebook Crawler theo 4 giai đoạn.
- **Sửa Database Schema**: Thêm bảng `facebook.groups` để cache map giữa Slug và Numeric ID. Thêm cột `group_numeric_id` vào bảng `facebook.posts`. 
- **Trám dữ liệu (Data Backfill)**: Quét và cập nhật `group_numeric_id` cho tất cả các post cũ. Đổi lại `group_id` về giá trị slug gốc cho các post đã bị lưu nhầm thành số trong bản hotfix trước đó.
- **Sửa Backend API (`proxify/plugins/facebook.py`)**: Loại bỏ logic ép (override) Slug thành Numeric ID. Hiện tại API truyền nguyên bản Slug xuống Crawler để đảm bảo tính toàn vẹn (từ khi user yêu cầu đến khi lưu DB đều dùng một định danh duy nhất).
- **Cải tiến SQL Query**: API query kết quả `/api/facebook/results` hiện hỗ trợ tìm kiếm trên cả 2 cột `group_id` (Slug) VÀ `group_numeric_id` (Numeric ID).
- **Cải tiến Crawler (`crawler.py` & `extractor.py`)**: Crawler tự động lưu trữ cả 2 định danh (Slug + Numeric ID) vào DB nhờ vào nâng cấp hàm `extract_from_responses`. Thêm cơ chế đọc Cache từ Database trước khi call API Facebook để tiết kiệm Rate Limit.

## Mục đích & Ý nghĩa
- **Giải quyết Mismatched ID**: Khắc phục dứt điểm lỗi Dashboard không thấy bài viết do lệch pha định danh (DB lưu số nhưng Frontend tìm bằng chữ).
- **Tránh bùng nổ Tech Debt**: Thay vì nhắm mắt dùng tạm một giải pháp chắp vá, hệ thống giờ đây lưu trữ vững chãi 2 lớp định danh (Slug cho UI, Numeric ID cho GraphQL).
- **Tiết kiệm Rate Limit & Antibot**: Trình độ ngụy trang của Crawler được tăng lên mức tối đa do giữ nguyên Slug làm `referer` (giống người thật). Bỏ qua hoàn toàn request HTTP phụ thừa thãi nhờ cơ chế check DB Cache.

## Mối liên hệ
- Các file bị ảnh hưởng:
  - `proxify/platforms/facebook/database.py` (Cấu trúc bảng)
  - `proxify/platforms/facebook/repository.py` (Thêm cột khi Upsert)
  - `proxify/platforms/facebook/extractor.py` (Bơm Numeric ID vào Record)
  - `proxify/platforms/facebook/crawler.py` (Logic Cache & Pass Numeric ID xuống extractor)
  - `proxify/plugins/facebook.py` (Xóa bỏ logic Override Slug, cập nhật SQL Query Dashboard)

## Rủi ro (Risks & Edge Cases)
- Do cột `group_numeric_id` chỉ mới được chèn vào `posts` mà chưa rải xuống `comments` (vì comment đã link theo `post_id`), nên các luồng query độc lập trên comment (nếu có sau này) không thể query trực tiếp bằng Numeric ID của Group. Tuy nhiên rủi ro cực thấp do hệ thống thiết kế query theo cascade (tìm post trước, lấy comment sau).
- Cache Database có thể out-of-date nếu Group ID đột nhiên thay đổi (hiếm nhưng có thể xảy ra do lỗi của Facebook). Khi đó cần có nút "Clear Cache" trên Dashboard (sẽ làm trong tương lai).
