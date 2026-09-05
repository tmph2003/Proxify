# Tài Liệu Kỹ Thuật: Khắc Phục Cập Nhật Lượt Tương Tác / Bình Luận & Gỡ Bỏ Nút Cập Nhật Riêng Lẻ

## 1. Tóm Tắt Thay Đổi
- **Loại bỏ nút làm mới tương tác riêng lẻ trên từng dòng (`Facebook.tsx`, `useFacebook.ts`)**:
  - Gỡ bỏ nút inline `🔄` nằm cạnh cột lượt tương tác (`post.reaction_count`) trên từng bài viết.
  - Bỏ function `refreshSinglePost` thừa trong hook `useFacebook`.
  - Toàn bộ thao tác cập nhật số tương tác, số bình luận và trạng thái bài viết được gom tập trung vào nút **"🔄 Làm mới"** (Bulk Refresh) ở thanh công cụ nổi (Floating Action Bar) khi chọn bài viết.
- **Sửa triệt để lỗi không cập nhật `reaction_count` và `comment_count` khi bấm "Làm mới" (`crawler.py`)**:
  - **Nguyên nhân gốc rễ**: 
    1. Query GraphQL `CommentsListComponentsPaginationQuery` vốn chỉ phục vụ phân trang bình luận (Comment pagination), trong payload trả về của Facebook **hoàn toàn không có trường `reaction_count` của bài viết**, dẫn đến parser trả về `reaction_count = None` và DB bỏ qua không cập nhật.
    2. Trong fallback HTML trước đây, điều kiện `if "login.php" in text:` bị false-positive (mọi trang Facebook public khi xem ẩn danh đều có link "Log In" trên header chứa `login.php`), khiến crawler tưởng nhầm là bị chặn đăng nhập và `pass` bỏ qua việc cập nhật số liệu.
  - **Giải pháp xử lý (Dual-Engine)**:
    1. **Primary Engine (Anonymous permalink check)**: Dùng `curl_cffi` (impersonate `chrome120`) với **ZERO COOKIE** gọi trực tiếp vào `permalink_url` của bài viết. Phân tích các thẻ `<script type="application/json">` chứa `Story` và `comet_ufi_summary_and_actions_renderer` để lấy chính xác tuyệt đối `reaction_count` và `comment_rendering_instance.comments.total_count`. An toàn 100% không checkpoint vì hoàn toàn vô danh.
    2. **Fallback Engine (Extension Bridge GraphQL)**: Khi gặp group kín hoặc bài ẩn danh không lấy được, fallback về GraphQL thông qua Extension Bridge với bộ parser `_parse_metrics_from_graphql` được nâng cấp toàn diện (hỗ trợ `node_v2`, `node`, `feedback`, bóc tách `comet_ufi_summary_and_actions_renderer` và `comment_rendering_instance`).
- **Bổ sung Unit Test (`test_crawler_refresh_and_guardrails.py`)**:
  - Test case `test_extract_metrics_from_html_success`: Xác thực trích xuất số like, comment và feedback_id từ cấu trúc HTML JSON nhúng.
  - Test case `test_extract_metrics_from_html_unavailable`: Xác thực nhận diện bài viết đã bị xóa hoặc ẩn.

---

## 2. Mục Đích & Ý Nghĩa
- **Trải nghiệm người dùng (UX)**: Người dùng chọn các bài viết và bấm "Làm mới", hệ thống tự động cập nhật chính xác số tương tác (like) và bình luận mới nhất, loại bỏ nút bấm vụn vặt thừa thãi trên từng hàng gây rối mắt giao diện.
- **Độ chính xác dữ liệu (Data Accuracy)**: Giải quyết dứt điểm vấn đề số liệu tương tác bị kẹt ở giá trị cũ hoặc `None`.
- **An toàn tài khoản (Zero-Checkpoint Compliance)**: Phương pháp lấy số liệu ẩn danh không mang cookie vừa cực nhanh (~1s/bài) vừa đảm bảo không có rủi ro bị Facebook phạt checkpoint tài khoản đang đăng nhập.

---

## 3. Mối Liên Hệ (Coupling & Impact)
- **`backend/proxify/platforms/facebook/crawler.py`**:
  - Hàm `refresh_single_post` là hạt nhân xử lý cập nhật số liệu cho 1 bài viết.
  - Được gọi bởi `_bg_refresh` trong `_handle_bulk_action` (`api.py`) và `_execute_crawl_specific_posts`.
- **`frontend/src/pages/Facebook.tsx` & `frontend/src/hooks/useFacebook.ts`**:
  - Bảng danh sách bài viết hiển thị sạch sẽ `👍 {post.reaction_count || 0}`.
  - Nút "🔄 Làm mới" ở FAB gửi bulk request, lắng nghe progress SSE/polling và tự động tải lại bảng (`loadData()`) khi hoàn tất.

---

## 4. Rủi Ro & Trường Hợp Ngoại Lệ (Risks & Edge Cases)
1. **Bài viết trong nhóm kín (Private Group)**:
   - Với nhóm kín, anonymous `curl_cffi` sẽ không thấy nội dung bài viết.
   - Khi đó hệ thống tự động fallback sang Extension Bridge thông qua tab Facebook đã đăng nhập của người dùng để thực thi GraphQL.
2. **Bài viết bị tác giả xóa hoặc Group bị khóa**:
   - Hàm `extract_metrics_from_html` và `_parse_metrics_from_graphql` tự động bắt các chuỗi đặc trưng ("Bạn hiện không xem được nội dung này", "This content isn't available right now") và cập nhật `is_active = FALSE` vào cơ sở dữ liệu.
3. **Bài viết có 0 lượt like hoặc 0 bình luận**:
   - Logic cập nhật kiểm tra chặt chẽ `if rc is not None` (thay vì `if rc`), đảm bảo số `0` vẫn được ghi đè hợp lệ vào Postgres thay vì giữ nguyên giá trị cũ.
