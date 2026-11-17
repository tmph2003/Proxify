# Chế độ Chạy Ngầm trên System Tray & Khởi chạy Không Chặn Terminal

## Tóm tắt thay đổi
- **Tạo mới `backend/proxify/utils/tray.py`:** Hiện thực bộ điều khiển biểu tượng khay hệ thống Windows (`WindowsSystemTray`) thuần Win32 API qua `ctypes` (`shell32.Shell_NotifyIconW`, `user32`, `kernel32`) chạy trên luồng Win32 message-pump tách biệt, chuẩn kiểu con trỏ 64-bit (`LRESULT = ctypes.c_ssize_t`), hỗ trợ phục hồi biểu tượng tự động khi `explorer.exe` khởi động lại (`TaskbarCreated`), thông báo dạng bóng (balloon toast), sao chép địa chỉ proxy vào Windows Clipboard, mở Dashboard / file log, cài chứng chỉ HTTPS (Root CA) từ menu chuột phải và thoát ứng dụng an toàn (`CMD_QUIT`).
- **Cập nhật `backend/proxify/utils/compat.py`:** Bổ sung các hàm `is_compiled_executable()`, `get_outer_executable_path()`, lớp `_SafeLogStream` và `setup_headless_logging()` để tự động điều hướng toàn bộ log lẫn `sys.stdout`/`sys.stderr` (khi bị `None` ở chế độ GUI subsystem) sang tệp xoay vòng `proxify.log` (tối đa 5 MB × 2 file sao lưu, mã hóa UTF-8) cạnh `proxify.exe`.
- **Cập nhật `backend/proxify/__main__.py`:**
  - Bổ sung các cờ dòng lệnh `--console` (`--foreground`), `--no-tray`, `--stop` và cờ nội bộ `--tray-worker`.
  - Bổ sung cơ chế tự động tách nền (`_should_auto_detach()`, `_spawn_detached_tray_worker()`) khi mở `proxify.exe` từ Git Bash / `mintty` (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`), trả ngay dấu nhắc terminal về cho người dùng mà vẫn giữ tiến trình chạy ngầm ở System Tray.
  - Bổ sung cơ chế khóa đơn thể (Single-Instance Named Mutex `Local\ProxifyInstance_<proxy_port>_<dashboard_port>`) giúp khi bấm chạy lại `proxify.exe` lúc app đã chạy sẽ tự động mở Dashboard thay vì lỗi trùng cổng.
- **Cập nhật `backend/proxify/server.py`:** Bổ sung tham số `on_master_ready` và `enable_termlog` cho `run_server()`. Khi chạy ngầm không có console, tự động đặt `with_termlog=False` cho `mitmproxy.tools.dump.DumpMaster` để tránh `TermLogHandler` gọi `sys.exit(1)` do không có thiết bị xuất terminal.

## Mục đích & Ý nghĩa
- **Không chiếm dụng cửa sổ terminal / Không bật cửa sổ đen console:** Khi người dùng mở trực tiếp `proxify.exe` từ Windows Explorer, Shortcut, CMD, PowerShell hoặc Git Bash, Proxify chạy ẩn hoàn toàn dưới khay hệ thống (System Tray góc dưới bên phải màn hình bên cạnh đồng hồ) với đầy đủ logo riêng.
- **Thao tác nhanh một chạm:** Nhấp đúp (hoặc nhấp chuột trái) vào icon trên System Tray để mở nhanh Dashboard tại `http://localhost:8888`; nhấp chuột phải để sao chép `127.0.0.1:8080`, xem `proxify.log`, cài đặt chứng chỉ Root CA hoặc thoát Proxify sạch sẽ (xả SQLite WAL và thu hồi icon ngay lập tức, không để lại icon ma).
- **Tránh phình dung lượng file đóng gói:** Sử dụng thuần Win32 `ctypes` sẵn có trên Windows thay cho `pystray` + `Pillow`, giữ nguyên kích thước tối ưu của `proxify.exe`.

## Mối liên hệ
- **`backend/proxify/__main__.py` ↔ `backend/proxify/utils/tray.py`:** `main()` khởi tạo `WindowsSystemTray` và truyền callback `_on_tray_quit` (gọi `master.shutdown()` an toàn theo thread thông qua `on_master_ready`) cùng callback `_install_ca_with_autogen`.
- **`backend/proxify/__main__.py` ↔ `backend/proxify/server.py`:** `server.py` nhận `enable_termlog` từ `setup_headless_logging()` trong `__main__.py` và gọi lại `on_master_ready(master, loop)` ngay sau khi `Dashboard` sẵn sàng.
- **`backend/proxify/utils/tray.py` ↔ `assets/logo.ico` ↔ `backend/build.sh`:** Nạp icon đa phân giải `proxify/logo.ico` được nhúng trong gói dữ liệu Nuitka hoặc trích trực tiếp từ tài nguyên PE của `proxify.exe`.

## Rủi ro (Risks & Edge Cases)
- **Môi trường không có phiên desktop tương tác (Session 0 / headless container):** `Shell_NotifyIconW(NIM_ADD)` sẽ trả về lỗi `E_FAIL` (`0x80004005`) do không tồn tại cửa sổ khay `Shell_TrayWnd`; `WindowsSystemTray` bắt an toàn ngoại lệ này mà không làm sập máy chủ proxy và tự đăng ký lại icon nếu sự kiện `TaskbarCreated` xuất hiện.
- **Job Object trên một số terminal Windows:** Cờ tạo tiến trình `CREATE_BREAKAWAY_FROM_JOB` có thể bị từ chối (`OSError`) nếu terminal cha bị khóa trong Job Object; `_spawn_detached_tray_worker()` tự động bắt `OSError` và thử lại với bộ cờ `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`.
- **Chạy kiểm thử tự động trong Git Bash:** Các biến môi trường `PYTEST_CURRENT_TEST` và `PROXIFY_FOREGROUND=1` vô hiệu hóa auto-detach để công cụ test (như `pytest` và `tests/e2e/fixtures/process_manager.py`) thu nhận được stdout/stderr trực tiếp mà không làm rơi tiến trình con ra khay hệ thống.
