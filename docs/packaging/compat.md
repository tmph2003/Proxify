# Tài Liệu Kỹ Thuật: Module Tương Thích Runtime Windows & Packaging (`proxify.utils.compat`)

## 1. Tóm tắt thay đổi
- Khởi tạo module mới `backend/proxify/utils/compat.py`.
- Triển khai hàm `get_application_base_dir()` giải quyết đường dẫn thư mục gốc ứng dụng một cách nhất quán trên mọi môi trường runtime (Dev Python, PyInstaller frozen binary, Nuitka standalone/onefile executable, biến môi trường `PROXIFY_DB_PATH`).
- Triển khai hàm `get_default_db_path()` trả về đường dẫn SQLite database mặc định (`proxify.db`) dựa trên thư mục gốc hoặc biến môi trường `PROXIFY_DB_PATH`.
- Đóng gói và tái cấu trúc hàm monkey-patch `_patch_nuitka_pyo3_builtins()`: tiêm `'__builtins__'` vào toàn bộ dictionary của sys.modules và bọc `builtins.__import__` để loại bỏ triệt để lỗi crash `KeyError: '__builtins__'` của PyO3 Rust extension (đặc biệt là thư viện `cryptography` khi Nuitka biên dịch C-code).
- Triển khai hàm `install_windows_ca_certificate(cer_path: Path) -> bool` gọi tiện ích hệ thống `certutil.exe -user -addstore Root <path>` để tự động tin cậy Root CA Certificate của Mitmproxy vào Windows CurrentUser Certificate Store mà không đòi hỏi quyền Administrator.
- Triển khai hàm `get_default_ca_cert_path() -> Path` tự động dò tìm vị trí lưu certificate mặc định của Mitmproxy.

## 2. Mục đích & Ý nghĩa
- **Giải quyết vấn đề phân tán và sao chép mã nguồn (DRY & SRP)**: Trước đây, logic xác định đường dẫn cơ sở dữ liệu bị trùng lặp ở cả `backend/proxify/core/database.py` và `backend/proxify/database/connection.py`. Cả hai file đều chỉ kiểm tra `__compiled__` (Nuitka) và fallback về `Path.cwd()`. Khi chạy ứng dụng qua Windows Shortcut (.lnk) hoặc Windows Service, thư mục làm việc thường bị đặt thành `C:\Windows\System32`, dẫn đến lỗi phân quyền ghi file SQLite (`sqlite3.OperationalError: unable to open database file`).
- **Ngăn ngừa crash PyO3/Rust Extensions**: Trong Nuitka 4.x, các module biên dịch C không tự động chèn `__builtins__` vào module `__dict__`. Khi extension Rust (PyO3) như `cryptography` truy cập `f_globals['__builtins__']` trong quá trình thực hiện TLS Handshake, Python sẽ ném ngoại lệ `KeyError: '__builtins__'`. Việc gom và gọi sớm `_patch_nuitka_pyo3_builtins()` giải quyết triệt để vấn đề này.
- **Tự động hóa tin cậy chứng chỉ trên Windows**: Người dùng chạy standalone executable không cần phải mở `certmgr.msc` thủ công để import file `.cer`. Bằng cách sử dụng `certutil.exe` với cờ `-user`, chứng chỉ được thêm thẳng vào chứng chỉ gốc người dùng hiện tại mà không kích hoạt UAC Prompt đòi quyền admin.

## 3. Mối liên hệ
- **Module liên kết**:
  - `backend/proxify/core/database.py`: Sử dụng `get_default_db_path()` và `get_application_base_dir()`.
  - `backend/proxify/database/connection.py`: Sử dụng `get_default_db_path()` và `get_application_base_dir()`.
  - `backend/proxify/__main__.py`: Gọi `_patch_nuitka_pyo3_builtins()` ngay khi khởi động và tích hợp cờ `--install-ca`.
  - `backend/proxify/server.py`: Gọi `_patch_nuitka_pyo3_builtins()` ở đầu file trước khi import các thư viện bên thứ 3.
  - `backend/tests/test_compat.py`: Chứa bộ unit test kiểm thử toàn diện các nhánh logic trong `compat.py`.

## 4. Rủi ro (Risks & Edge Cases)
- **Hệ điều hành phi Windows**: `certutil.exe` chỉ tồn tại trên Windows. Trên Linux/macOS, hàm `install_windows_ca_certificate` sẽ ghi log warning và trả về `False` thay vì gây crash ứng dụng.
- **Chứng chỉ không tồn tại**: Nếu file chứng chỉ chưa được tạo (lần đầu chạy chưa kích hoạt Mitmproxy), `compat.py` kiểm tra `is_file()` và ghi log rõ ràng thay vì gọi subprocess vô ích.
- **Nhiều luồng / đa tiến trình gọi lặp lại**: `_patch_nuitka_pyo3_builtins` đã được thiết kế mang tính bình đẳng trạng thái (idempotent) thông qua cờ `_proxify_builtins_patched` và `_proxify_patched`, ngăn chặn lồng bọc lặp vô hạn.
