# Đồng Bộ Hóa Tài Liệu README Và Cấu Trúc Kiến Trúc Dự Án

## 1. Tóm tắt thay đổi
- Cập nhật toàn bộ tài liệu hướng dẫn và tổng quan trong `README.md` (tiếng Anh) và `README_vi.md` (tiếng Việt).
- Điều chỉnh lại cây thư mục (`Directory Structure`) để phản ánh chính xác cấu trúc module hiện tại: tách biệt giữa các extension nghiệp vụ độc lập (`backend/extensions/` gồm `facebook`, `youtube`, `zalo`) và lõi điều phối (`backend/proxify/`).
- Bổ sung chi tiết các tính năng mới của **YouTube Platform & Enhancer**:
  - Cơ chế lọc quảng cáo an toàn cấp JSON và HTML (`clean_youtube_json_data`, `strip_youtube_ads`).
  - Bộ giám sát chống dừng hình tự động (Inline Anti-AFK Watchdog & `lactThresholdMs` override).
  - Định tuyến truyền tải video trực tiếp qua TCP Passthrough (`googlevideo.com`).
- Bổ sung cơ chế bảo vệ phạm vi traffic nghịch đảo (`allow_hosts` và `ignore_hosts`) giúp zero-overhead cho các ứng dụng công việc, game online và telemetry hệ thống.

## 2. Mục đích & Ý nghĩa
- **Tính đồng nhất kiến trúc (Single Source of Truth):** Tránh hiện tượng tài liệu mô tả kiến trúc cũ gây hiểu lầm cho người dùng hoặc nhà phát triển mới khi tiếp cận mã nguồn.
- **Minh bạch hóa các tính năng nâng cao:** Giúp người dùng nắm rõ cách thức hoạt động của tính năng chặn quảng cáo YouTube, cơ chế Anti-AFK, cũng như lý do các dịch vụ game và công việc không bị chậm khi chạy qua Proxify.

## 3. Mối liên hệ
- Phản ánh trực tiếp hiện trạng của:
  - `backend/extensions/youtube/`: Module YouTube Enhancer.
  - `backend/extensions/facebook/`: Module Facebook Crawler & Bridge.
  - `backend/extensions/zalo/`: Module Zalo Decryption.
  - `backend/proxify/server.py`: Module quản lý phạm vi mạng và Mitmproxy DumpMaster.
  - `scripts/create_chrome_shortcuts.py`: Tiện ích tạo shortcut Chrome cách ly.

## 4. Rủi ro (Risks & Edge Cases)
- **Tài liệu song ngữ (Song ngữ Anh - Việt):** Cần đảm bảo cập nhật đồng thời cả hai file `README.md` và `README_vi.md` mỗi khi có thay đổi lớn về tính năng hoặc kiến trúc thư mục để tránh độ lệch thông tin.
