# Tài liệu: circuit_breaker.py

## 1. Tóm tắt tổng quan
Hệ thống ngắt mạch (Circuit Breaker) dành cho crawler. Cơ chế này tự động dừng toàn bộ các thao tác gửi request đi khi hệ thống phát hiện bị chặn tạm thời (soft-block), chuyển sang trạng thái chờ/cooldown.

## 2. Mục đích & Ý nghĩa
Mục đích chính là ngăn chặn việc tiếp tục gửi request khi đang bị các nền tảng (ví dụ: Facebook) báo checkpoint hoặc rate limit. Việc liên tục gửi yêu cầu khi bị soft-block rất dễ dẫn đến việc bị khóa tài khoản vĩnh viễn (permanent ban) hoặc khóa địa chỉ IP dài hạn. Circuit Breaker giúp đảm bảo an toàn cho các tài khoản crawler.

## 3. Mối liên hệ
Đây là một module tiện ích độc lập nhưng đóng vai trò như một Singleton global (`crawl_breaker`) được import và sử dụng chung (shared) bởi mọi crawler worker trong toàn bộ ứng dụng Proxify.

## 4. Rủi ro (Risks & Edge Cases)
- **Vấn đề phân tán (Distributed System):** Circuit Breaker hiện tại được triển khai dạng in-memory với `threading.Lock`. Do đó, nó chỉ có tác dụng trên một process duy nhất. Nếu Proxify chạy trên nhiều tiến trình (multiprocessing) hoặc nhiều server khác nhau, cơ chế này không đồng bộ được trạng thái.
- **Thời gian Cooldown:** Mức cooldown hiện đang fix ngẫu nhiên từ 30 đến 60 phút. Nếu nền tảng gỡ block nhanh hơn, hệ thống vẫn lãng phí thời gian chờ. Ngược lại, nếu nền tảng block lâu hơn, việc test request lại có thể gây gia hạn thời gian block.
- **Deadlock:** Việc sử dụng Lock cần cẩn thận trong các luồng xử lý phức tạp để tránh gây treo chương trình.

## 5. Chi tiết các Class và Hàm

- **Class `CrawlCircuitBreaker`**: Lớp chính triển khai mẫu thiết kế Circuit Breaker.
  - `__init__(self, min_cooldown, max_cooldown)`: Khởi tạo các trạng thái mặc định (CLOSED), bộ đếm thời gian, lock an toàn cho thread và số lần bị trip (ngắt mạch).
  - `Property state(self) -> str`: Trả về trạng thái hiện tại (CLOSED, OPEN, HALF_OPEN). Đặc biệt, property này có chức năng tự động chuyển trạng thái từ OPEN sang HALF_OPEN nếu thời gian cooldown đã kết thúc.
  - `Property remaining_cooldown(self) -> float`: Tính toán số giây chờ còn lại (trả về 0 nếu không ở trạng thái OPEN).
  - `allow_request(self) -> bool`: Hàm kiểm tra xem có được phép gửi request mạng hay không. Trả về `True` nếu trạng thái là CLOSED hoặc HALF_OPEN (cho phép 1 request thử nghiệm), trả về `False` nếu đang bị ngắt (OPEN).
  - `trip(self, reason: str = "") -> None`: Hàm kích hoạt ngắt mạch. Đổi trạng thái sang OPEN, lưu lại thời điểm ngắt, sinh ngẫu nhiên khoảng thời gian chờ (cooldown) và ghi log cảnh báo.
  - `record_success(self) -> None`: Hàm ghi nhận request thử nghiệm thành công (khi đang ở HALF_OPEN), sau đó chuyển trạng thái về CLOSED để tiếp tục hoạt động bình thường.
  - `reset(self) -> None`: Hàm cưỡng chế khôi phục trạng thái về CLOSED một cách thủ công (manual override), xóa mọi thời gian đếm ngược.
  - `Property info(self) -> dict`: Trả về thông tin trạng thái mạch (dưới dạng dictionary) phục vụ cho hiển thị giao diện UI hoặc ghi log.

- **Biến Global `crawl_breaker`**: Instance duy nhất của class `CrawlCircuitBreaker` được khởi tạo sẵn ở cuối file, dùng làm biến toàn cục cho mọi module import nó vào.
