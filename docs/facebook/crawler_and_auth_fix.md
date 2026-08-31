# Tóm tắt thay đổi

1. Sửa lỗi "dict object has no attribute status" trong `proxify/platforms/facebook/crawler.py` dòng 412.
2. Refactor cơ chế lấy token tự động trong `proxify/platforms/facebook/auth_fetcher.py`.
3. Cập nhật `proxify/plugins/facebook.py` và `proxify/platforms/facebook/api.py` để truyền `User-Agent` thực tế của client xuống script lấy token.

# Mục đích & Ý nghĩa

- Sửa lỗi crash khi `FacebookCrawler` cố gắng cập nhật trạng thái kết thúc luồng chạy (do nhầm lẫn cấu trúc dữ liệu `crawl_state` là một object thay vì một dict). Việc sửa thành `self.crawl_state.get("status")` và `self.crawl_state.update({"status": "idle"})` đảm bảo crawler worker có thể kết thúc và thông báo trạng thái "Hoàn tất" chính xác lên UI.
- `auth_fetcher.py` được viết lại để sử dụng `aiohttp` thay cho `curl_cffi`, giải quyết tận gốc vấn đề bất đồng bộ TLS Fingerprint với chuỗi User-Agent, giúp hạn chế việc Facebook chặn mbasic và điều hướng về trang Checkpoint.
- Đã sửa lỗi logic bắt nhận diện trang đăng nhập (loại bỏ check `<title>Facebook</title>` quá nghiêm ngặt gây bắt nhầm trang chủ khi đã đăng nhập trên bản mobile).
- Bổ sung xác thực cấu trúc Cookie sơ bộ để tránh lỗi ngớ ngẩn từ phía người dùng copy sai định dạng.

# Mối liên hệ

- Các thay đổi trong `crawler.py` ảnh hưởng trực tiếp đến `api_worker_loop` (nơi phân phối và xử lý các RefreshCommand/CrawlCommand).
- Các file `api.py` và `plugins/facebook.py` nay phụ thuộc vào User-Agent Header của request được gửi từ Dashboard giao diện, đảm bảo tính liên kết môi trường mạng cho Cookie.

# Rủi ro (Risks & Edge Cases)

- **Hiệu năng / Caching**: `aiohttp` không hỗ trợ Fake TLS. Mặc dù mbasic ít khắt khe về TLS, nhưng nếu Facebook bật cơ chế quét TLS trên mbasic, `aiohttp` thuần túy vẫn có nguy cơ bị phát hiện. Giải pháp thay thế sau này có thể phải dùng lại curl_cffi nhưng bỏ `impersonate` (chỉ spoof header).
- **Edge Case**: Facebook thay đổi lại cấu trúc trang chủ hoặc tên thẻ input của `fb_dtsg` khiến regex thất bại. Tuy nhiên đã có kịch bản dự phòng fallback về www.facebook.com để tìm kiếm JSON object `DTSGInitialData`.
