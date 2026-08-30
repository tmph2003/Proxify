# Tài liệu: Tính năng lọc bài viết theo Group (Facebook Extractor)

## 1. Tóm tắt thay đổi
- **Backend (`proxify/plugins/facebook.py`):**
  - Bổ sung thêm API `GET /api/facebook/groups` để truy vấn danh sách các Group đã được crawl.
  - Xử lý mượt mà (Edge Case): Những bài viết cào được `group_name` nhưng bị khuyết `group_id` (NULL) giờ đây sẽ được gộp chung bằng hàm `COALESCE(group_id, group_name)`. Tránh tình trạng bài viết bị bỏ sót khỏi danh sách bộ lọc.
  - Tích hợp cơ chế in-memory caching (5 phút) cho API này để tránh việc Full Table Scan lặp đi lặp lại trên bảng `posts` lớn.
- **Frontend (`proxify/ui/templates/facebook.html`):**
  - Thêm UI Searchable Dropdown (Bộ lọc tìm kiếm nhóm giống Google Autocomplete) vào thanh Header của bảng danh sách bài viết.
  - Viết logic JavaScript (`fetchGroups`, `renderGroupDropdown`, `selectGroupFilter`, `handleGroupInputKey`) để gọi API lấy danh sách nhóm, render giao diện.
  - Hỗ trợ bôi đậm (highlight) từ khóa trùng khớp khi gõ tìm kiếm.
  - Hỗ trợ điều hướng bằng bàn phím (Arrow Up, Arrow Down, Enter) mang lại trải nghiệm tiện lợi như công cụ tìm kiếm, sau đó truyền `group_id` xuống API `/api/facebook/results`.

## 2. Mục đích & Ý nghĩa
- **Mục đích:** Người dùng yêu cầu hiển thị và lọc lại bài viết của những Group đã crawl trước đó, với trải nghiệm thông minh "như Google".
- **Ý nghĩa:** Tránh việc phải xem lẫn lộn hàng nghìn bài viết của nhiều Group khác nhau. Bộ lọc Searchable Dropdown với tính năng bôi đậm từ khóa và phím tắt giúp thao tác tìm kiếm mượt mà ngay cả khi số lượng nhóm được crawl lên tới hàng trăm.

## 3. Mối liên hệ
- **Module:** Tính năng này can thiệp vào `FacebookPlugin` (phần Backend API) và `facebook.html` (phần UI).
- Nó tận dụng logic filter `group_id` đã được thiết kế sẵn trong API `/api/facebook/results` của file `facebook.py`.

## 4. Rủi ro (Risks & Edge Cases)
- **Hiệu năng Database:** Khi bảng `facebook.posts` có hàng chục triệu bản ghi, lệnh `SELECT DISTINCT ON` dù đã có cache vẫn có thể mất 1-2 giây cho lần gọi đầu tiên sau khi cache hết hạn. Có thể cần chuyển sang bảng riêng `facebook.groups` nếu user gặp vấn đề timeout sau này.
- **Lỗi giao diện:** Tên nhóm quá dài hoặc chứa ký tự đặc biệt như `'` đã được escape, tuy nhiên các ký tự unicode phức tạp có thể gây sai lệch hiển thị nhỏ, cần quan sát thêm thực tế.
