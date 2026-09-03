# Tài Liệu Kỹ Thuật: Cơ Chế Phân Trang Bình Luận Relay Cursor & Báo Cáo Tiến Độ Chuẩn Xác

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `backend/proxify/platforms/facebook/crawler.py`
  - `backend/proxify/platforms/facebook/extractor.py`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`

---

## 1. Tóm tắt thay đổi

1. **Khóa chiều phân trang (`direction lock`) chống lỗi Ping-Pong Loop**:
   - Khi Facebook Comet trả về một trang bình luận (chẳng hạn Trang 2 sau Trang 1), metadata `page_info` sẽ có `has_previous_page = True` (trỏ ngược về Trang 1 vừa duyệt).
   - Nếu kiểm tra đồng thời cả 2 cờ mà không cố định chiều duyệt (`direction`), crawler sẽ quay đầu đi ngược lại Trang 1, tạo vòng lặp **Ping-Pong qua lại giữa Trang 1 và Trang 2**.
   - **Giải pháp:** Bổ sung tham số `current_direction` vào `_extract_comment_page_info`. Một khi đã bắt đầu duyệt theo chiều `after` (hoặc `before`), hệ thống **chỉ đi tiếp theo chiều đó** cho đến khi cờ `has_next_page` (hoặc `has_previous_page`) trả về `False`. Kết hợp tập `seen_cursors` để ngăn lặp lại cursor.

2. **Khắc phục Bug False Fallback Strategy 2 làm mất tiến độ bình luận**:
   - Trong `_execute_crawl_comments`, biến `progress["total"]` trước đây cộng dồn `c_count` từ `extract_from_responses()`.
   - Tuy nhiên, `c_count` chỉ đại diện cho số lượng bình luận **mới toanh chưa có trong DB** (`new_comments`).
   - Khi người dùng bấm "Cập nhật / Cào tiếp" một bài viết đã cào trước đó, tất cả bình luận ở Trang 1 đã tồn tại trong DB -> `c_count = 0` -> `progress["total"] = 0`.
   - Khối `if progress["total"] == 0:` hiểu nhầm là GraphQL bị lỗi và lập tức kích hoạt Strategy 2 (HTML page scraping), rồi ghi đè thông báo `"Hoàn tất! Tổng: 0 bình luận"`, khiến người dùng thấy số lượng không tăng và tưởng rằng hệ thống không cào được trang 2.
   - **Giải pháp:** 
     - Dùng `len(all_comment_ids)` (tổng comment IDs thực sự lấy được từ GraphQL) để đánh giá GraphQL có thành công hay không.
     - Sau khi cào xong, truy vấn trực tiếp `SELECT COUNT(*) FROM facebook.comments WHERE post_id = %s` từ PostgreSQL để phản ánh chính xác 100% số bình luận đã lưu trong cơ sở dữ liệu.

3. **Bóc tách Chỉ số Phản hồi & Trả lời (`reaction_count`, `reply_count`) trong `CommentExtractor`**:
   - Trước đây `CommentExtractor` gán cứng `"reply_count": 0` và `"reaction_count": 0`.
   - Nay đã bóc tách trực tiếp từ node `feedback.comments.total_count` và `feedback.reactors.count`.

---

## 2. Mục đích & Ý nghĩa

- **Giải quyết triệt để phản ánh của người dùng:**
  1. *"sao chỉ crawl được 1 trang comments vậy nhỉ"*
  2. *"tự check lại đi vẫn chưa được"*
- **Ý nghĩa kỹ thuật:**
  - Chuẩn hóa Relay Cursor Connection theo đúng RFC spec của Meta Relay.
  - Loại bỏ hoàn toàn xung đột logic giữa "Số bình luận mới thêm vào DB" và "Số bình luận crawler vừa thu thập được từ Facebook".
  - Phản ánh trung thực con số bình luận thực tế hiển thị trên Facebook (ví dụ bài có 32 bình luận tổng thể, sau khi lọc spam/xóa thì Facebook trả về đủ 16 bình luận qua 2 trang GraphQL).

---

## 3. Mối liên hệ kiến trúc

- **`FacebookCrawler._extract_comment_page_info`**: Khóa hướng duyệt Relay cursor.
- **`FacebookCrawler._fetch_comments`**: Đóng gói payload GraphQL gửi qua Extension Bridge / Stealth Session.
- **`FacebookCrawler._execute_crawl_comments`**: Điều phối luồng cào, phân trang đa tầng và đồng bộ trạng thái DB.
- **`CommentExtractor.extract`**: Chuẩn hóa cấu trúc bản ghi comment trước khi DocumentLinker lưu xuống PostgreSQL.

---

## 4. Rủi ro (Risks & Edge Cases) và Giải pháp Kiểm soát

1. **Số lượng "Tổng FB" lớn hơn "Đã lưu":**
   - Facebook thường tính tổng cả bình luận vi phạm đã bị xóa, tài khoản spam bị shadowban, hoặc bình luận trả lời cấp 2 trở đi.
   - *Kiểm soát:* Giao diện hiển thị rõ ràng: `Tổng FB: X • Đã lưu: Y` để người dùng hiểu rõ bản chất Y là số bình luận thực tế còn tồn tại được cào về.
2. **Facebook đổi vị trí start_cursor/end_cursor:**
   - *Kiểm soát:* Đã xử lý an toàn bằng `seen_cursors` và `max_pages = 25` để đảm bảo crawler luôn kết thúc an toàn, không bao giờ bị nghẽn worker.

