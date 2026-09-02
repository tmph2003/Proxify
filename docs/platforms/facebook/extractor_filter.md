# Tối ưu hóa Bộ lọc Bài viết trong Facebook Extractor

## Tóm tắt thay đổi
- Chỉnh sửa file `backend/proxify/platforms/facebook/extractor.py`.
- **PostExtractor**: Thêm logic phát hiện các bài viết là quảng cáo (Ads/Sponsored) dựa trên key `category == "SPONSORED"` và `sponsored_data`. Đồng thời, trích xuất ID và loại hình (`__typename`) của thực thể đích (`to` hoặc `owning_profile`) lưu vào `_target_id` và `_target_type`.
- **extract_from_responses**: Thêm bộ lọc kiểm tra chéo. Nếu đang tiến hành thu thập một Facebook Group cụ thể, hệ thống sẽ tự động bỏ qua các bài viết có `target_type` không phải là `Group` (ví dụ: Page, User) hoặc các bài có `target_id` khác với `group_numeric_id` đang thu thập.

## Mục đích & Ý nghĩa
- **Giải quyết vấn đề**: Trước đây crawler thu thập dữ liệu bằng cách quét đệ quy tìm tất cả các node `Story` trên JSON trả về từ Facebook GraphQL. Do Facebook thường xuyên chèn các bài viết quảng cáo (Sponsored) hoặc Gợi ý (Suggested for you, Suggested Groups) vào News Feed của Group, crawler đã vô tình thu thập và lưu trữ luôn các bài viết "rác" này.
- **Ý nghĩa**: Giúp làm sạch dữ liệu ngay từ bước parser. Cơ sở dữ liệu sẽ chỉ lưu trữ chính xác những bài viết được đăng tải *thực sự* trong Group đích mà người dùng muốn quét.

## Mối liên hệ
- **Tập tin liên quan**: `backend/proxify/platforms/facebook/extractor.py`
- **Ảnh hưởng đến crawler**: Luồng quét (`backend/proxify/platforms/facebook/crawler.py`) sẽ nhận được danh sách bài viết sạch hơn. Hàm `extract_from_responses` tiếp tục đảm nhiệm phân phối đầu ra cho `DocumentLinker` để UPSERT vào Database. Log cũng sẽ hiển thị lý do bỏ qua từng bài viết nếu bị lọc.

## Rủi ro (Risks & Edge Cases)
- **Edge Case 1 (Slug không phân giải được ID)**: Nếu người dùng nhập `group_id` là một dạng chữ (slug) và hàm API chưa phân giải thành công ra dãy số Numeric ID, biến `group_numeric_id` sẽ mang dạng chữ. Bộ lọc đã được thiết kế an toàn (`if str(group_numeric_id).isdigit()`) để không bỏ sót nhầm bài viết của Group trong trường hợp này.
- **Edge Case 2 (Facebook thay đổi kiến trúc)**: Nếu Facebook đổi cách gắn nhãn `sponsored_data` hoặc dấu ẩn `category`, một vài bài quảng cáo dạng mới có thể lọt vào. Tuy nhiên, rào cản thứ hai (xác thực `target_id` của Group) sẽ bắt được hầu hết những bài chèn từ trang (Page/User) bên ngoài.
- **Rủi ro nhỏ về Performance**: Việc tìm kiếm key `sponsored_data` đệ quy ở mức độ sâu (`DataHelper.find_key`) đối với mọi post có thể tiêu tốn một lượng mili-giây rất nhỏ, nhưng hoàn toàn khả thi và không gây tắc nghẽn với cấu trúc cây JSON của Story.
