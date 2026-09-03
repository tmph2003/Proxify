# Tài Liệu Kỹ Thuật: Ép Buộc Sắp Xếp Bài Viết Theo Thời Gian Đăng (CHRONOLOGICAL)

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `backend/proxify/platforms/facebook/crawler.py`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`, `docs/platforms/facebook/crawler_sorting_fix.md`

---

## 1. Tóm tắt thay đổi

- Trong `backend/proxify/platforms/facebook/crawler.py` (`_set_variables()`):
  - Xóa bỏ điều kiện kiểm tra tồn tại `if "sortingSetting" not in variables:`.
  - **Ép buộc tuyệt đối:** `variables["sortingSetting"] = "CHRONOLOGICAL"` cho toàn bộ request GraphQL phân trang feed nhóm.
  - Ghi đè triệt để giá trị `TOP_POSTS` (Phù hợp nhất) hoặc `RECENT_ACTIVITY` (Hoạt động gần đây) mà trình duyệt vô tình chụp được từ template gốc.

---

## 2. Mục đích & Ý nghĩa

- **Khắc phục hiện tượng quét bài viết bị nhảy ngày lung tung ("lung tung lắm")**:
  - Trước đây, do giữ nguyên `sortingSetting = "TOP_POSTS"` từ template trình duyệt, thuật toán của Facebook trả về bài viết dựa trên điểm tương tác (bài viết từ 2-3 tuần trước có bình luận mới hoặc nhiều like vẫn nhảy lên đầu trang).
  - Kết quả là crawler khi cuộn trang gặp các bài viết ngày tháng lộn xộn: trang 1 thấy bài ngày 01/09, trang 2 thấy bài 15/08 (bị tương tác bump lên), trang 3 lại thấy bài 02/09.
  - Việc ép cứng `CHRONOLOGICAL` buộc Facebook phải trả về bài viết **đúng theo thứ tự thời gian tạo (`creation_time`) giảm dần đơn điệu**:
    $$\text{Hôm nay (03/09)} \longrightarrow \text{Hôm qua (02/09)} \longrightarrow \text{01/09} \longrightarrow \text{31/08} \longrightarrow \text{30/08}$$
  - Giúp crawler tiếp cận đúng khoảng ngày chỉ định nhanh hơn gấp nhiều lần và kích hoạt điều kiện dừng (`_check_old_posts`) chuẩn xác, không bị dừng non hoặc quét lãng phí.

---

## 3. Mối liên hệ kiến trúc

- **`FacebookCrawler._set_variables()`**: Điểm chuẩn hóa tham số payload trước khi gửi qua Bridge / Network.
- **`FacebookCrawler._check_old_posts()`**: Tận dụng tính giảm dần đơn điệu của ngày đăng để dừng crawler chính xác khi chạm mốc `start_timestamp`.
- **`FacebookPlatform.extractor`**: Nhận danh sách bài viết sạch, có tính tuần tự thời gian cao.

---

## 4. Rủi ro (Risks & Edge Cases) và Giải pháp Kiểm soát

1. **Bài viết ghim (Pinned Posts):**
   - *Rủi ro:* Kể cả khi chọn CHRONOLOGICAL, Facebook vẫn luôn đặt các bài viết ghim (Pinned Stories) ở đầu feed (có thể là bài từ vài tháng trước).
   - *Giải pháp:* Hàm `_check_old_posts` đã có cơ chế `consecutive >= 3` (yêu cầu 3 trang liên tiếp toàn bài cũ mới dừng), ngăn chặn việc dừng nhầm khi gặp bài ghim.
