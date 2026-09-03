# Nâng Giới Hạn Phân Trang Cào Bình Luận Từ 25 Trang (250 Comments) Lên 500 Trang (5.000 Comments)

## 1. Tóm tắt thay đổi
* **File sửa đổi**: [`backend/proxify/platforms/facebook/crawler.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/platforms/facebook/crawler.py)
* **Thay đổi chi tiết**:
  * Tại phương thức `_execute_crawl_comments()`, nâng biến giới hạn số trang `max_pages` từ **25** (tối đa ~250 comments) lên **500** (tối đa ~5.000 comments).
  * Vòng lặp dừng lại tự nhiên khi Facebook trả về `has_more = False` (đã cào hết toàn bộ bình luận của bài viết), hoặc khi chạm mốc trần bảo vệ 500 trang.

---

## 2. Mục đích & Ý nghĩa
* **Nguyên nhân gốc rễ (Root Cause)**:
  * Người dùng chụp ảnh bài viết có 1.042 bình luận nhưng hệ thống chỉ lấy được đúng **`250 / 1042 đã lấy`**.
  * Trong mã nguồn `crawler.py`, tác giả trước đó đã hardcode cứng:
    ```python
    page_idx = 0
    max_pages = 25  # Up to ~250 comments
    while has_more and page_idx < max_pages:
        page_idx += 1
    ```
  * Vì mỗi trang GraphQL trả về khoảng 10 bình luận, nên khi `page_idx == 25`, vòng lặp bị cưỡng chế dừng lại ở đúng 250 bình luận.
* **Ý nghĩa**:
  * Cho phép cào trọn vẹn toàn bộ bình luận của các bài viết có tương tác khủng (1.000, 2.000, 5.000 comments) mà không bị chặt cụt giữa chừng.

---

## 3. Mối liên hệ
* `backend/proxify/platforms/facebook/crawler.py`: Module điều phối vòng lặp cào bình luận qua GraphQL.
* `frontend/src/pages/Facebook.tsx`: Badge hiển thị số lượng bình luận `💬 {saved} / {total} đã lấy`.

---

## 4. Rủi ro (Risks & Edge Cases)
* **Thời gian cào lâu hơn đối với bài viết >1.000 comments**: Với độ trễ mô phỏng hành vi người thật (~0.7s/trang), bài viết 1.000 comments (~100 trang) sẽ mất khoảng 70 giây để hoàn tất. Hệ thống đã có cơ chế cập nhật tiến độ liên tục lên UI theo từng trang nên người dùng luôn nắm bắt được trạng thái.
