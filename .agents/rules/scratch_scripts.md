# Scratch Scripts Rule

BẤT CỨ KHI NÀO bạn (Agent) cần tạo các file script tạm thời để kiểm tra, debug, test (ví dụ như `check_cookies.py`, `patch_crawler.py`, script test database...), bạn **BẮT BUỘC** phải lưu chúng vào trong thư mục `scratchs/` ở gốc dự án.

**Tuyệt đối không được** lưu trực tiếp ở thư mục gốc của dự án hoặc để rải rác ở các thư mục code chính.

Điều này giúp giữ cho cấu trúc dự án luôn sạch sẽ và các file test không bị commit nhầm vào Git (do thư mục `scratchs/` đã được cấu hình trong `.gitignore`).
