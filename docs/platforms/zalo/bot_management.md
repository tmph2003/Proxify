# Cập nhật Zalo Plugin — Thêm Bot Management và Scan UI

## Tóm tắt thay đổi
- Thêm 3 API endpoints quản lý Bot trình duyệt: `POST /api/zalo/bot/start`, `POST /api/zalo/bot/stop`, `GET /api/zalo/bot/status`.
- Khôi phục ô nhập link quét nhóm (scan input) và thêm nút bật/tắt Bot trực tiếp trên giao diện web.
- Thêm JS functions: `submitScan()`, `toggleBot()`, `checkBotStatus()` và CSS cho nút Bot toggle.

## Mục đích & Ý nghĩa
Trước đây, người dùng phải chạy lệnh `python -m proxify.platforms.zalo.bot` thủ công từ terminal mỗi khi muốn quét nhóm Zalo. Thay đổi này cho phép khởi động/dừng Bot trình duyệt (Playwright Chromium) trực tiếp từ giao diện web dashboard, giúp trải nghiệm người dùng mượt mà hơn.

## Mối liên hệ
- **`proxify/plugins/zalo.py`**: Plugin chính, quản lý subprocess của Bot thông qua `subprocess.Popen`. Bot được khởi chạy như một tiến trình con của container/server.
- **`proxify/ui/templates/zalo.html`**: Giao diện HTML, thêm scan-area chứa ô nhập link + nút Bot toggle.
- **`proxify/ui/static/css/zalo.css`**: CSS cho nút Bot toggle (hiệu ứng nhấp nháy xanh khi đang chạy).
- **`proxify/ui/static/js/zalo.js`**: Logic client-side cho submitScan, toggleBot, checkBotStatus. Tích hợp vào vòng polling 5s.
- **`proxify/platforms/zalo/bot.py`**: Module Bot thực tế được khởi chạy bởi subprocess.

## Rủi ro (Risks & Edge Cases)
- **Subprocess trên Docker Container**: Bot sử dụng Playwright + Chromium headless=False (hiển thị cửa sổ). Khi chạy trong Docker container KHÔNG có display (headless server), Bot sẽ không thể mở cửa sổ trình duyệt → cần chạy trên máy host trực tiếp hoặc cấu hình X11 forwarding.
- **Zombie Process**: Nếu server crash mà không gọi `shutdown()`, subprocess Bot có thể trở thành orphan process. Đã xử lý bằng `shutdown()` hook nhưng không đảm bảo 100% trong mọi trường hợp crash.
- **Concurrent Access**: Nếu nhiều người cùng bấm Start Bot, chỉ 1 instance chạy do có check `_is_bot_alive()`. Tuy nhiên nếu có nhiều instance plugin, mỗi instance sẽ quản lý subprocess riêng.
- **DB_DSN**: Subprocess cần biến `DB_DSN` để kết nối database. Code đã set fallback mặc định nhưng nếu DSN khác, cần đảm bảo biến môi trường được truyền đúng.
