# Tài Liệu Kỹ Thuật: Tự Động Thu Thập "Tất Cả Bình Luận" (Unfiltered Comments) Không Cần Chuyển Bộ Lọc Thủ Công

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `backend/proxify/platforms/facebook/crawler.py`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`

---

## 1. Tóm tắt thay đổi

1. **Phân tích gói tin GraphQL khi người dùng chọn "Tất cả bình luận":**
   - Khi người dùng bấm chuyển bộ lọc sang "Tất cả bình luận" trên bài viết Facebook, Meta gửi đi query:
     - `CommentListComponentsRootQuery` (doc_id: `27046361795040764`) hoặc `CommentsListComponentsPaginationQuery` (doc_id: `27973447728944010`).
     - Biến phân loại quyết định: `"commentsIntentToken": "CHRONOLOGICAL_UNFILTERED_INTENT_V1"`.
   - Ngược lại, khi mở bài viết mặc định hoặc khi crawler gửi `commentsIntentToken = None`: Meta tự động áp dụng `RANKED_FILTERED_INTENT_V1` ("Phù hợp nhất"), dẫn đến việc Facebook tự ý ẩn/lọc bỏ các bình luận bị coi là spam, quảng cáo, chèn link hoặc câu từ ngắn.

2. **Cưỡng chế token không lọc trong Crawler:**
   - Trong `_fetch_comments`: Cưỡng chế `variables["commentsIntentToken"] = "CHRONOLOGICAL_UNFILTERED_INTENT_V1"` trong mọi request cào bình luận.
   - Trong `crawl_comments_for_post`: Cập nhật template sinh mã GraphQL mặc định với `"commentsIntentToken": "CHRONOLOGICAL_UNFILTERED_INTENT_V1"`.
   - Kết quả: Crawler tự động lấy sạch 100% tất cả các bình luận (kể cả bình luận chứa link, bình luận bị Facebook xếp vào mục spam/ẩn) mà **người dùng không cần phải vào Facebook bấm "Hiển thị tất cả bình luận" bằng tay**.

---

## 2. Mục đích & Ý nghĩa

- **Mục đích:** Giải quyết triệt để vấn đề người dùng phản ánh: *"lúc mà redirect đến post ấy, tôi phải ấn hiển thị tất cả bình luận rồi mới crawl full được, bạn hãy check request tôi chuẩn bị ấn rồi phân tích và cải thiện code nhé"*.
- **Ý nghĩa kiến trúc:**
  - Tự động hóa hoàn toàn ở tầng giao thức GraphQL: Không phụ thuộc vào thao tác UI thủ công của người dùng trên trình duyệt.
  - Đảm bảo tính toàn vẹn dữ liệu (Data Completeness): Thu thập đầy đủ số lượng bình luận thực tế theo đúng dòng thời gian (Chronological), không bị thuật toán xếp hạng của Facebook che giấu.

---

## 3. Mối liên hệ kiến trúc

- **`FacebookCrawler._fetch_comments`**: Nơi gán tham số biến GraphQL `commentsIntentToken`.
- **`FacebookCrawler._execute_crawl_comments`**: Vòng lặp phân trang và xử lý template cào bình luận.
- **`CommentExtractor` (`extractor.py`)**: Tầng bóc tách node Comment từ cây JSON trả về của GraphQL.

---

## 4. Rủi ro (Risks & Edge Cases) và Giải pháp Kiểm soát

1. **Bài viết có bình luận đã bị xóa hoàn toàn khỏi cơ sở dữ liệu Facebook:**
   - *Thực tế:* Với các bình luận bị xóa vĩnh viễn (hard deleted), Meta không trả về node. Biến đếm tổng `total_comment_count` của Facebook có thể cao hơn số node thực tế trả về.
   - *Kiểm soát:* Hệ thống đã ghi nhận đúng số lượng comment node thực tế được lưu vào PostgreSQL và hiển thị tỷ lệ minh bạch `Đã lưu / Tổng FB`.
