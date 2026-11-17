# Cập nhật Bộ Kiểm thử Tương thích & Tách Tiến trình E2E cho Chế độ System Tray

## Tóm tắt thay đổi
- **`private/tests/e2e_root/fixtures/process_manager.py`:** Đặt mặc định `PROXIFY_FOREGROUND=1` và `PROXIFY_NO_TRAY=1` trong biến môi trường khi sinh tiến trình `proxify.exe` / `python -m proxify` trong bộ test E2E.
- **`backend/tests/test_compat.py`:** Bổ sung kiểm thử đơn vị mới (`TestBuiltinExtensionDiscovery`, `TestDashboardSpaRouting`, `TestHeadlessLoggingAndAutoDetach` và `TestWindowsSystemTray`) bao phủ nạp extension tích hợp không hardcode tên nền tảng (`_get_builtin_extension_packages`), định tuyến SPA tĩnh và ưu tiên API 404, nhận diện binary đã biên dịch (`is_compiled_executable`, `get_outer_executable_path`), ghi log không console (`setup_headless_logging` với `sys.stdout=None`), điều kiện tự động tách nền từ Git Bash (`_should_auto_detach`), kích thước cấu trúc Win64 (`NOTIFYICONDATAW` = 976 bytes, `WNDCLASSEXW` = 80 bytes) và chế độ bỏ qua an toàn trên non-Windows.

## Mục đích & Ý nghĩa
Đảm bảo các bài kiểm thử tự động chạy ổn định ngay cả khi kích hoạt từ Git Bash (`MSYSTEM=MINGW64`) bằng cách ép chạy ở chế độ foreground và tắt tạo icon khay hệ thống tạm thời, đồng thời kiểm soát độ tin cậy của toàn bộ lớp tương thích Win32 và ranh giới Open-Core.

## Mối liên hệ
Tác động trực tiếp đến hạ tầng chạy kiểm thử trong `private/tests/e2e_root/` và bộ unit test Open-Core `backend/tests/test_compat.py` (kiểm chứng `backend/proxify/__main__.py`, `backend/proxify/utils/compat.py`, `backend/proxify/utils/tray.py`, `backend/proxify/sdk/loader.py`, `backend/proxify/dashboard.py`).

## Rủi ro (Risks & Edge Cases)
- Trong `test_setup_headless_logging_handles_none_streams`, `pytest` mặc định thiết lập mức log gốc (`root_logger.level`) là `WARNING`; bài test phải lưu/phục hồi mức `NOTSET` tạm thời để kiểm chứng đúng hành vi tự nâng mức log lên `INFO` của `setup_headless_logging()`.
