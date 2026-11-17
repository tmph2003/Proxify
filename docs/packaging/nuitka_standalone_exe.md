# Đóng gói Proxify thành Standalone Native Binary (`proxify.exe`)

## Tóm tắt thay đổi
- Cập nhật `backend/proxify/dashboard.py` bổ sung phương thức `mount_spa_static()` để phục vụ trực tiếp React SPA (`frontend_dist` được nhúng trong binary hoặc `frontend/dist` khi chạy local) kèm chống tấn công leo thang thư mục (Path Traversal) và CORS hỗ trợ `PATCH`, `X-Client-ID`.
- Cập nhật `backend/proxify/sdk/loader.py` bổ sung hàm `_get_builtin_extension_packages()` nạp danh sách extension đã biên dịch sẵn từ tệp manifest tạm `proxify._compiled_extensions` (hoặc biến môi trường `PROXIFY_BUILTIN_EXTENSIONS`, mặc định rỗng trên Open-Core) để nạp các extension bên trong binary Nuitka, đồng thời vẫn hỗ trợ thư mục mở rộng `extensions/` nằm cạnh file `.exe`.
- Cập nhật `backend/proxify/server.py` gọi `dashboard_instance.mount_spa_static()` sau khi toàn bộ API route của core và extensions đã đăng ký xong, và định tuyến file SQLite `proxify.db` nằm ngay cạnh `proxify.exe`.
- Hoàn thiện kịch bản đóng gói tự động `backend/build.sh` (tự động stage đầy đủ `pages/*.tsx`, `hooks/*.ts`, `styles/*.css` từ `private/frontend/` và quét động các gói trong `private/extensions/<ext_id>/` + `private/shared/*.py` để tạo tạm `proxify/_compiled_extensions.py`, dùng `trap` đảm bảo dọn sạch toàn bộ file tạm sau khi build để giữ nguyên ranh giới Open-Core, chuẩn hóa `PYTHONPATH` bằng `cygpath -w` trên Git Bash, tự động giải phóng khóa file `proxify.exe` đang chạy trước khi biên dịch Nuitka `--standalone --onefile` cho Core + Extensions tùy chọn + `curl_cffi` + `frontend/dist`).

## Mục đích & Ý nghĩa
- **Chống dịch ngược mã nguồn (Anti-Decompilation):** Khác với PyInstaller chỉ đóng gói bytecode `.pyc` vào archive (dễ dàng bị giải nén bằng `pyinstxtractor` + `uncompyle6` trong vài phút), Nuitka biên dịch toàn bộ mã nguồn Python (cả `proxify` core lẫn các extension tùy chọn trong `private/extensions/<ext_id>`) sang mã C và biên dịch bằng `gcc` ra mã máy native `x86_64` (`.exe`), loại bỏ hoàn toàn `.pyc` của mã nguồn nghiệp vụ.
- **Độc lập hoàn toàn (Zero-Dependency Standalone):** Gỡ bỏ sự phụ thuộc vào Docker, Nginx (phục vụ giao diện React) và PostgreSQL Server. Người dùng chỉ cần chạy duy nhất 1 file `proxify.exe` trên bất kỳ máy Windows 64-bit nào.

## Mối liên hệ
- **`backend/proxify/server.py` ↔ `backend/proxify/dashboard.py`:** `mount_spa_static()` phải chạy sau `extension_loader.discover_and_load()` để route catch-all `/{tail:.*}` của React Router không chặn các endpoint `/api/<ext_id>/*`, `/api/extensions` và `/ws`.
- **`backend/proxify/sdk/loader.py` ↔ `private/extensions/<ext_id>`:** Khi chạy ở chế độ `.exe` nén `--onefile`, `ExtensionLoader` đọc `COMPILED_EXTENSION_PACKAGES` từ `proxify._compiled_extensions` (được `build.sh` sinh tạm lúc đóng gói) hoặc `PROXIFY_BUILTIN_EXTENSIONS` để nạp các extension đã biên dịch sẵn bên trong binary mà không cần hardcode tên extension riêng tư vào mã Open-Core.
- **`frontend/dist` ↔ `proxify/frontend_dist`:** Được nhúng vào gói dữ liệu nội bộ của Nuitka thông qua cờ `--include-data-dir`.

## Rủi ro (Risks & Edge Cases)
- **Thời gian khởi động lần đầu (Cold Start):** Chế độ `--onefile` của Nuitka giải nén runtime và `frontend_dist` vào thư mục `%TEMP%` khi khởi chạy, mất khoảng 2–5 giây trước khi cổng `8080` và `8888` sẵn sàng.
- **Cảnh báo nhầm từ Windows Defender / Antivirus (False Positive):** Các file `.exe` đóng gói `--onefile` kèm trình giải nén tự động và driver bắt gói tin (`mitmproxy_windows` / `WinDivert64.sys`) đôi khi bị phần mềm diệt virus quét heuristic cảnh báo; khi phân phối thương mại nên ký số (Code Signing Certificate).
- **Tính năng phụ thuộc trình duyệt ngoài (Playwright):** Cờ `--nofollow-import-to=playwright` giữ dung lượng `.exe` gọn nhẹ thay vì đóng gói cả trình duyệt Chromium; các tác vụ tự động hóa trình duyệt cần môi trường trình duyệt ngoài nếu kích hoạt.


---

## Bổ sung xử lý đặc thù Nuitka `--onefile` (`original_argv0` & `MetaPathFinder`)

### Tóm tắt thay đổi
- **`backend/proxify/core/database.py` & `backend/proxify/database/connection.py`:** Chuyển cơ chế xác định thư mục lưu `proxify.db` từ `sys.executable` sang `__compiled__.original_argv0` (kết hợp `_INITIAL_CWD`).
- **`backend/proxify/sdk/loader.py`:** Bổ sung `_LegacyNamespaceAliasFinder` vào `sys.meta_path` để ánh xạ tương thích ngược các lệnh import không gian tên cũ `proxify.platforms.<ext_id>.*` về `<ext_id>.*` khi đóng gói.

### Mục đích & Ý nghĩa
1. **Bảo toàn dữ liệu SQLite bền vững:** Trong Nuitka `--onefile`, `sys.executable` của tiến trình con trỏ tới thư mục giải nén tạm `%TEMP%\onefile_...` (tự động xóa khi đóng app). Dùng `__compiled__.original_argv0` đảm bảo file `proxify.db` luôn được khởi tạo và lưu trữ bền vững ngay bên cạnh file `proxify.exe` gốc của người dùng.
2. **Tương thích Namespace ảo trên Binary đã biên dịch:** CPython truyền thống tìm submodule qua đường dẫn vật lý `__path__`, nhưng bên trong binary Nuitka không tồn tại file `.py` vật lý nên các plugin dùng không gian tên cũ `proxify.platforms.<ext_id>.*` sẽ thất bại nếu chỉ gán trên `sys.modules`. Bộ `MetaPathFinder` chuyển hướng trực tiếp về trình nạp C nội bộ của Nuitka.

### Mối liên hệ
Liên kết trực tiếp giữa tầng nạp SDK (`proxify/sdk/loader.py`), tầng kết nối cơ sở dữ liệu (`proxify/core/database.py`, `proxify/database/connection.py`) và các extension tùy biến trong `private/extensions/<ext_id>`.

### Rủi ro (Risks & Edge Cases)
- Nếu người dùng đổi tên hoặc di chuyển `proxify.exe` sang thư mục chỉ đọc (Read-only như `C:\Program Files\`), SQLite sẽ không tạo được file `-wal` / `-shm` cạnh `.exe`; khi đó cần chạy quyền Admin hoặc đặt biến môi trường `PROXIFY_DB_PATH` trỏ sang `%APPDATA%\Proxify\proxify.db`.


---

## Bổ sung vá lỗi tương thích Nuitka ↔ Rust PyO3 (`KeyError: '__builtins__'` khi bắt tay TLS)

### Tóm tắt thay đổi
- **`backend/proxify/__main__.py` & `backend/proxify/server.py`:** Bổ sung hàm `_patch_nuitka_pyo3_builtins()` tự động gắn khóa `'__builtins__': builtins.__dict__` vào từ điển toàn cục (`__dict__`) của mọi module đang nạp trong `sys.modules` — bao gồm cả các module bị bọc bên trong lớp vỏ `cryptography.utils._ModuleWithDeprecations` (như `OpenSSL.crypto` qua thuộc tính `_module`) và hook vào `builtins.__import__`.
- Tự động nạp file cấu hình `.env` nằm cùng thư mục với `proxify.exe` gốc.

### Mục đích & Ý nghĩa
Khi `mitmproxy` thực hiện bắt tay TLS (`mitmproxy/addons/tlsconfig.py` → `OpenSSL/crypto.py:326` → `crypto_key.private_bytes(...)`), thư viện Rust `cryptography` (sử dụng binding PyO3) truy xuất trực tiếp `f_globals['__builtins__']` của frame gọi thông qua `PyObject_GetItem`. Trong Nuitka 4.x, các module biên dịch sang C không tự điền `'__builtins__'` vào `moduledict` trừ khi được tham chiếu tường minh trong mã Python, và `OpenSSL.crypto` còn bị bọc bởi `_ModuleWithDeprecations`, dẫn đến ngoại lệ `KeyError: '__builtins__'` làm đứt mọi kết nối HTTPS qua cổng proxy `8080`. Bản vá này khôi phục bất biến `f_globals['__builtins__']` cho toàn bộ hệ sinh thái module C của Nuitka.

### Mối liên hệ
Tác động trực tiếp đến luồng giải mã/ký chứng chỉ động TLS MITM giữa `mitmproxy.addons.tlsconfig`, `pyOpenSSL` (`OpenSSL.crypto`) và `cryptography` (Rust PyO3).

### Rủi ro (Risks & Edge Cases)
- Độ trễ khi quét `sys.modules` tại thời điểm khởi động nhỏ hơn 1ms và không ảnh hưởng tới hiệu năng xử lý gói tin sau khi bắt tay TLS.


---

## Chuyển sang GUI Subsystem (`--windows-console-mode=disable`) & Nhúng Icon `logo.ico`

### Tóm tắt thay đổi
- **`assets/logo.ico`:** Tạo file biểu tượng Windows đa kích thước (`16×16` đến `256×256` RGBA) từ `assets/logo.png`.
- **`backend/build.sh`:**
  - Tự động sinh `assets/logo.ico` nếu chưa tồn tại.
  - Bổ sung `--windows-icon-from-ico` (gắn icon cho file `proxify.exe` trên Windows Explorer / Taskbar) và `--include-data-files=...=proxify/logo.ico` (phục vụ hiển thị High-DPI trên System Tray).
  - Đổi `--windows-console-mode=force` sang `--windows-console-mode=disable` (chế độ GUI Subsystem không bật cửa sổ đen console).
  - Tự động giải phóng khóa file nếu `proxify.exe` đang chạy trước khi biên dịch đè.

### Mục đích & Ý nghĩa
Cho phép chạy `proxify.exe` như một ứng dụng nền Windows chuẩn mực không hiện cửa sổ CMD/Terminal, đồng thời hỗ trợ đầy đủ cờ dòng lệnh `--console` (mở console xem log trực tiếp khi gỡ lỗi), `--no-tray` (chạy nền không tạo icon khay) và `--stop` (dừng êm tiến trình đang chạy ngầm).

### Mối liên hệ
Liên kết chặt chẽ với mô-đun khay hệ thống `backend/proxify/utils/tray.py`, hàm `setup_headless_logging()` trong `backend/proxify/utils/compat.py` và điểm vào `backend/proxify/__main__.py`.

### Rủi ro (Risks & Edge Cases)
- Ở chế độ GUI Subsystem (`--windows-console-mode=disable`), `sys.stdout` và `sys.stderr` mặc định là `None` khi mở từ Explorer; mọi thao tác ghi trực tiếp ra stdout/stderr phải đi qua `setup_headless_logging()` và `with_termlog=False` trên `DumpMaster` để không phát sinh lỗi `AttributeError` hoặc thoát tiến trình.
