# Khắc Phục Lỗi Không Thể Mở Lại Modal Bình Luận Khi Đang Cào (Reopen Comment Modal Fix)

## 1. Tóm tắt thay đổi
* **File sửa đổi**: [`frontend/src/pages/Facebook.tsx`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/frontend/src/pages/Facebook.tsx)
* **Thay đổi chi tiết**:
  1. **Nút tiến trình cào tại bảng bài viết (`btn-comment crawling`)**:
     * Trước đây: Bị gán thuộc tính `disabled` và hoàn toàn không có hàm `onClick`. Khi người dùng đóng modal bình luận trong lúc đang cào, nút này bị khóa cứng, người dùng không thể nhấn vào để mở lại modal.
     * Khắc phục: Gắn `onClick={() => openComments(post)}` và thiết lập `cursor: pointer`. Người dùng có thể nhấn vào biểu tượng đang cào (`⭕ Đã lấy x comments...`) bất kỳ lúc nào để mở lại modal.
  2. **Nút xem bình luận đã lưu (`btn-comment has-data`)**:
     * Trước đây: Bị khóa (`pointer-events: none`, `disabled`) nếu có tiến trình cào feed (`crawling`) hoặc bulk action (`feedCrawling`).
     * Khắc phục: Thao tác mở modal để xem bình luận đã lưu thuần túy là đọc dữ liệu cục bộ từ PostgreSQL, không gửi request lên Facebook nên không xung đột với cào feed. Nút xem bình luận giờ đây luôn luôn mở được.
  3. **Cơ chế cập nhật bình luận thời gian thực (Live Comment Polling)**:
     * Trong modal xem bình luận, nếu tiến trình cào của bài viết đó đang chạy (`running`), React Hook tự động thăm dò và nạp thêm bình luận mới từ DB mỗi 2 giây, giúp danh sách bình luận nhảy số trực tiếp trước mắt người dùng.

---

## 2. Mục đích & Ý nghĩa
* **Giải quyết dứt điểm phản hồi người dùng:** "đóng xong không ấn vào lại được".
* Cho phép người dùng linh hoạt: mở modal xem cào trực tiếp $\rightarrow$ đóng modal để xem các bài viết khác $\rightarrow$ bấm mở lại modal bất kỳ lúc nào mà không bị gián đoạn hay bị khóa nút.

---

## 3. Mối liên hệ
* `frontend/src/pages/Facebook.tsx`: Giao diện bảng danh sách bài viết và Modal hiển thị bình luận.
* `frontend/src/hooks/useFacebook.ts`: Cung cấp hàm `openComments` và đối tượng theo dõi tiến độ `commentCrawlProgress`.

---

## 4. Rủi ro (Risks & Edge Cases)
* **Xung đột click**: Khi người dùng nhấn vào nút đang cào, nó chỉ kích hoạt `openComments` (mở modal hiển thị), không kích hoạt lại lệnh cào mới nên tuyệt đối an toàn và không gây trùng lặp request.
