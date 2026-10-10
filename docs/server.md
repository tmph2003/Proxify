# Tài liệu: `server.py`

## 1. Tóm tắt tổng quan
File `server.py` là điểm đầu vào (entry point) chính để khởi chạy hệ thống Proxify. Nó thiết lập giao diện dòng lệnh (CLI), cấu hình hệ thống logging, đồng thời khởi tạo và quản lý hai thành phần cốt lõi chạy song song: một máy chủ proxy (dựa trên `mitmproxy`) và một bảng điều khiển web (Dashboard) dựa trên `aiohttp`.

## 2. Mục đích & Ý nghĩa
- Đóng vai trò là file chạy chính (runner) của toàn bộ dự án. Khi người dùng chạy lệnh `python -m proxify`, file này sẽ phân tích các đối số truyền vào (như port, host, dsn cơ sở dữ liệu, bật chế độ ẩn danh...).
- Phối hợp khởi tạo kết nối cơ sở dữ liệu (`RequestStorage`), nạp các plugin, cấu hình event loop và khởi động luồng riêng biệt để chạy `mitmproxy`, giúp ứng dụng có thể vừa chặn/bắt request ở một cổng, vừa cung cấp giao diện hiển thị ở một cổng khác mà không chặn lẫn nhau.

## 3. Mối liên hệ
- Tương tác với `proxify.capture_addon.CaptureAddon` và `proxify.stealth_addon.StealthUpstreamAddon` để gắn vào `mitmproxy`.
- Khởi tạo và sử dụng `proxify.dashboard.Dashboard` cùng `proxify.storage.RequestStorage`.
- Sử dụng hệ thống sự kiện (`proxify.core.events.bus`) để giao tiếp đa luồng giữa proxy và UI/Database.
- Quản lý việc nạp plugin thông qua `proxify.plugins.registry`.

## 4. Rủi ro (Risks & Edge Cases)
- **Đa luồng & Bất đồng bộ (Concurrency):** `mitmproxy` chạy trong một thread riêng (proxy_thread) cần sử dụng asyncio loop của riêng nó, trong khi bảng điều khiển chạy ở luồng chính. Các tương tác chéo luồng (như hàm `broadcast_fn` gọi `asyncio.run_coroutine_threadsafe`) có khả năng gây lỗi race condition hoặc khó dừng ứng dụng dứt điểm khi người dùng nhấn `Ctrl+C`.
- **Mã hoá Console:** Can thiệp mã hóa luồng ra (stdout) trên Windows có thể gây xung đột với các shell đặc biệt hoặc khi pipe đầu ra.

## 5. Chi tiết các Class và Hàm
- **`setup_logging(verbose: bool = False)`**: Thiết lập định dạng và cấp độ log cho toàn hệ thống (sử dụng thư viện `logging`). Hàm được thiết kế idempotent (an toàn khi gọi nhiều lần). Nếu truyền `verbose=True`, sẽ bật chế độ DEBUG.
- **`_make_broadcast_fn(dashboard: Dashboard, dashboard_loop: asyncio.AbstractEventLoop)`**: Hàm factory tạo ra một hàm `broadcast` đồng bộ. Hàm này có nhiệm vụ gọi các coroutine bất đồng bộ của Dashboard (`dashboard.broadcast`) thông qua hàm `asyncio.run_coroutine_threadsafe`, giúp luồng proxy (thread khác) có thể gửi thông báo (real-time) sang luồng UI một cách an toàn.
- **`run_mitmproxy(...)`**: Chạy phiên bản tùy chỉnh của `mitmproxy` bên trong một luồng nền. Nó cấu hình các tuỳ chọn (Options) như port, host, ignore_hosts (bỏ qua TLS cho tốc độ cao), và nạp các Addon (`CaptureAddon`, `StealthUpstreamAddon`). Nó cũng đăng ký (subscribe) các observer lắng nghe sự kiện ghi log và ghi CSDL.
- **`run_dashboard(dashboard: Dashboard, proxy_port: int)`**: Một coroutine (`async`) có nhiệm vụ khởi động server web giao diện điều khiển `aiohttp` (AppRunner, TCPSite) và in thông tin chào mừng ra console. Chạy vòng lặp duy trì kết nối cho đến khi bị huỷ.
- **`main()`**: Entry-point của toàn bộ script. Xử lý các cờ từ dòng lệnh (`argparse`), gọi `setup_logging`, khởi tạo CSDL (`RequestStorage`), nạp danh sách plugins (`discover_plugins`), tạo `Dashboard`, khởi tạo Event Loop và khởi động `proxy_thread` trước khi cho ứng dụng Dashboard chặn luồng chính. Đảm bảo việc dọn dẹp các tài nguyên (`storage.close()`, `loop.close()`) khi tắt.
