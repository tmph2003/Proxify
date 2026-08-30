# Tài liệu Refactor Giao diện Zalo Extractor (Tách Vanilla CSS/JS)

## Tóm tắt thay đổi
- Chuyển logic CSS và JS từ trong file HTML trực tiếp ra các file tĩnh riêng biệt:
  - Tách block `<style>` ra file `proxify/static/css/zalo.css`.
  - Tách block `<script>` ra file `proxify/static/js/zalo.js`.
- Cấu hình lại `aiohttp` trong `proxify/dashboard.py` để thêm endpoint phục vụ thư mục tĩnh (static assets):
  - `self.app.router.add_static("/static", Path(__file__).parent / "static")`
- Nhúng 2 đường dẫn `zalo.css` và `zalo.js` ngược lại vào file `proxify/templates/zalo.html`.

## Mục đích & Ý nghĩa
- **Giảm tải file HTML:** Giải quyết triệt để tình trạng "khủng" của file `zalo.html` (trước đây chứa > 900 dòng, nay còn dưới 100 dòng).
- **Tách biệt quan tâm (Separation of Concerns):** Giữ UI layout (HTML), Styling (CSS), và Logic (JS) nằm ở các file riêng biệt.
- **Tái cấu trúc (Refactoring):** Tạo đà để dễ dàng quản lý, mở rộng và bảo trì code frontend sau này mà không bị rối mắt.

## Mối liên hệ
- Tác động trực tiếp lên `proxify/templates/zalo.html` và backend web server `proxify/dashboard.py`.
- Tạo thư mục cấu trúc mới: `proxify/static/css/` và `proxify/static/js/`.

## Rủi ro (Risks & Edge Cases)
- **Cache trình duyệt:** Có thể xảy ra hiện tượng trình duyệt cache file `.css` hoặc `.js` cũ khiến giao diện hoặc logic không cập nhật ngay (có thể khắc phục bằng cách clear cache trên trình duyệt với `Ctrl + F5` hoặc thêm query hash ở link).
- Không ảnh hưởng đến dữ liệu hay luồng nghiệp vụ backend.
