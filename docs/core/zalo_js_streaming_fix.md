# Fix JS Streaming — Cho phép Zalo Plugin inject hooks

## Tóm tắt thay đổi
Sửa file `proxify/capture_addon.py` để không stream các file `.js` của domain Zalo, cho phép Zalo plugin đọc và sửa đổi nội dung JS trước khi trả về trình duyệt.

## Mục đích & Ý nghĩa
- Trước đây, tất cả file `.js` (bao gồm cả JS của Zalo) đều bị đánh dấu stream (`flow.response.stream = True`) trong `responseheaders()` hook.
- Khi stream được bật, `flow.response.content` trống tại thời điểm `response()` hook chạy → Plugin Zalo không thể đọc hoặc sửa nội dung JS → JS Hooks không được inject → dữ liệu Zalo không bao giờ được capture.
- Fix: Kiểm tra nếu file `.js` thuộc domain Zalo → **không stream** → Zalo plugin có thể đọc body, inject hooks, và ghi lại body đã sửa.

## Mối liên hệ
- **`proxify/capture_addon.py`** (dòng 133-140): Hàm `responseheaders()` — điều khiển file nào bị stream.
- **`proxify/platforms/zalo/extractor.py`** (hàm `modify_zalo_response` và `inject_hooks`): Được gọi bởi ZaloPlugin.on_response() — cần đọc `flow.response.content` để inject JS hooks.
- **`proxify/plugins/zalo.py`** (hàm `on_response`): Gọi `modify_zalo_response(flow)` — yêu cầu body không bị stream.

## Rủi ro (Risks & Edge Cases)
- **RAM Usage:** Không stream file JS của Zalo nghĩa là toàn bộ file JS sẽ được buffer trong RAM. File JS của Zalo có thể lớn (vài MB), nhưng vẫn nằm trong phạm vi chấp nhận được.
- **Performance:** Không ảnh hưởng đáng kể vì chỉ có vài file JS chính của Zalo, không phải tất cả JS trên internet.
- **Tương thích:** Chỉ ảnh hưởng đến domain chứa "zalo" trong tên, không ảnh hưởng đến các site khác.
