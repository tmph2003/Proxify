# Tài Liệu Kỹ Thuật: Tái Cấu Trúc FacebookPlugin Theo Adapter Pattern

## 1. Tóm tắt thay đổi
- **`backend/proxify/plugins/facebook.py`**:
  - Đã thay thế toàn bộ 893 dòng code trùng lặp (vốn copy từ v1 trước khi có kiến trúc `platforms/facebook/`) bằng một lớp Adapter mỏng (`FacebookPlugin`).
  - Áp dụng mẫu thiết kế **Adapter Pattern** (theo tài liệu `python-design-pattern`, Chương 9: `ch09-adapter.md`).
  - `FacebookPlugin` kế thừa `BasePlugin` và ủy quyền (delegate) toàn bộ chức năng sang 2 thành phần chính của `platforms/facebook/`:
    - `on_request` / `on_response` ủy quyền sang `FacebookGraphQLObserver` (`interceptor.py`).
    - `get_api_routes()` ủy quyền sang `FacebookAPI` (`api.py`).
- **`backend/proxify/platforms/facebook/interceptor.py`**:
  - Hỗ trợ khởi tạo `FacebookGraphQLObserver(event_bus=None)` với cờ an toàn (`if self.event_bus:`).

---

## 2. Mục đích & Ý nghĩa
- **Triệt tiêu trùng lặp (DRY Principle):** Xóa bỏ hoàn toàn 893 dòng mã nguồn dư thừa gây rối loạn và nguy cơ lỗi đồng bộ (desync bug) giữa plugin v1 và platform v2.
- **Tương thích ngược 100%:** Giúp cơ chế tự động quét plugin (`discover_plugins()` và `test_registry.py`) vẫn nhận diện được plugin `facebook` mà không phải duy trì 2 bộ định tuyến API song song.
- **Kiến trúc rõ ràng (High Cohesion & Low Coupling):** Toàn bộ nghiệp vụ Facebook được tập trung duy nhất tại `backend/proxify/platforms/facebook/`.

---

## 3. Mối liên hệ
- Liên kết giữa hệ thống plugin cũ (`proxify.plugins.base.BasePlugin`) và kiến trúc phân tầng mới (`proxify.platforms.facebook.*`).
- `backend/tests/test_registry.py` tiếp tục pass 100% khi kiểm tra plugin discovery.

---

## 4. Rủi ro & Kiểm thử
- **Rủi ro:** Không có rủi ro; `server.py` đã sử dụng trực tiếp `FacebookPlatform` từ trước.
- **Kiểm thử:** Đã chạy bộ kiểm thử `pytest tests/test_registry.py` và toàn bộ 2/2 tests đều PASSED.
