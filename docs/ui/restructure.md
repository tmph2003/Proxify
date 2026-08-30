# Cấu trúc lại thư mục Giao diện (UI)

## Tóm tắt thay đổi
- Chuyển thư mục `proxify/static` và `proxify/templates` vào chung một thư mục mẹ mới là `proxify/ui/`.
- Cấu trúc thư mục mới:
  ```
  proxify/
  ??? ui/
      ??? static/
      ??? templates/
  ```
- Cập nhật lại toàn bộ đường dẫn tham chiếu (import path) trong mã nguồn Python (`proxify/dashboard.py`, `proxify/plugins/zalo.py`, `proxify/plugins/facebook.py`) để trỏ chính xác về thư mục mới.

## Mục đích & Ý nghĩa
- **Tổ chức thư mục khoa học hơn:** Giúp quy tụ toàn bộ các tài nguyên liên quan đến giao diện người dùng (gồm cả HTML tĩnh, CSS, JS) vào một điểm duy nhất (thư mục `ui`). 
- **Chuẩn bị cho tương lai:** Tạo tiền đề gọn gàng nếu sau này dự án muốn tích hợp một hệ thống template engine phức tạp hơn hoặc xây dựng thành một Frontend hoàn chỉnh (như Vue/React).

## Mối liên hệ
- **dashboard.py**: Sửa đường dẫn phục vụ thư mục tĩnh từ `parent / "static"` thành `parent / "ui" / "static"`. Sửa đường dẫn file `index.html`, `style.css`.
- **plugins/zalo.py & plugins/facebook.py**: Sửa đường dẫn tham chiếu đến các file template `zalo.html` và `facebook.html`.

## Rủi ro (Risks & Edge Cases)
- Các file hoặc plugin cũ nếu vẫn hardcode tham chiếu đến folder `templates` cũ sẽ bị lỗi Not Found (404). Hiện tại đã scan và thay thế toàn bộ path trong phạm vi toàn dự án.
