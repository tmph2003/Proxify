# Tài liệu: `proxify/platforms/facebook/delay.py`

## 1. Tóm tắt tổng quan
File `delay.py` cung cấp cơ chế tạo ra độ trễ (delay) giống con người (human-like delay) để áp dụng giữa các lần gửi request đến Facebook. Việc này được thực hiện thông qua mô hình phân phối chuẩn (Gaussian distribution) có kẹp giới hạn (clamped) và đôi khi thêm vào những khoảng ngưng dài (long pause) để giả lập thời gian người dùng thực sự đọc bài viết.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Cung cấp các hàm sinh thời gian chờ (sleep time) ngẫu nhiên nhưng có tính quy luật để làm chậm lại tốc độ crawler.
- **Ý nghĩa**: Là thành phần cực kỳ quan trọng trong việc vượt qua hệ thống chống bot (anti-bot) của Facebook. Việc gửi request với tốc độ cố định hoặc quá nhanh sẽ dễ dàng bị đánh dấu là bot và tài khoản/IP sẽ bị khóa. Độ trễ giống người thật giúp tăng độ uy tín và an toàn cho session.

## 3. Mối liên hệ
- File này được import và sử dụng trực tiếp bởi `FacebookCrawler` (trong `crawler.py`) để tính toán thời gian `asyncio.sleep` giữa việc cào các page của group, cũng như khi cào các bình luận (comments) và trả lời (replies).
- Đây là một Strategy Pattern, cho phép Crawler gọi delay mà không cần quan tâm đến cách tính toán phức tạp ở bên dưới.

## 4. Rủi ro (Risks & Edge Cases)
- **Cấu hình trễ quá thấp**: Nếu các hằng số `min`, `max` bị đặt quá thấp (ví dụ < 1s cho page delay), nguy cơ bị Facebook soft-block tăng vọt.
- **Chặn luồng (Thread Blocking)**: Các hàm ở đây chỉ trả về một số thực (float) tính bằng giây. Lập trình viên phải dùng hàm `asyncio.sleep()` không đồng bộ. Nếu dùng `time.sleep()`, toàn bộ thread của server sẽ bị kẹt.

## 5. Chi tiết các Class và Hàm

### 1. `CrawlDelayConfig` (Dataclass)
- **Mô tả**: Data class định nghĩa các tham số (bằng giây) cấu hình cho quá trình tạo độ trễ.
- **Thuộc tính**:
  - `page_mean`, `page_std`, `page_min`, `page_max`: Thông số Gaussian cho thời gian nghỉ giữa các phân trang bảng tin (mặc định: mean=4.0, std=1.5, giới hạn [2.0, 8.0]).
  - `comment_mean`, `comment_std`, `comment_min`, `comment_max`: Thông số Gaussian cho thời gian nghỉ giữa các request load comment (nhanh hơn, mặc định: mean=0.7, std=0.3).
  - `long_pause_chance`, `long_pause_min`, `long_pause_max`: Thông số xác suất xảy ra nghỉ dài (mặc định 10% cơ hội, nghỉ từ 5 - 15 giây).

### Biến toàn cục: `DEFAULT_DELAY_CONFIG`
- Khởi tạo mặc định của `CrawlDelayConfig`, dùng làm tham số mặc định cho các hàm sinh thời gian.

### 2. Hàm `_gaussian_clamped(mean: float, std: float, lo: float, hi: float) -> float`
- **Mô tả**: Hàm tính toán nội bộ để sinh một số ngẫu nhiên theo phân phối chuẩn, sau đó giới hạn chặn trên (hi) và chặn dưới (lo).
- **Cách hoạt động**: Gọi `random.gauss(mean, std)`, sau đó dùng hàm `max` và `min` để đảm bảo kết quả không vượt qua khoảng `[lo, hi]`.

### 3. Hàm `page_delay(config: CrawlDelayConfig = DEFAULT_DELAY_CONFIG) -> float`
- **Mô tả**: Sinh ra thời gian chờ giả lập độ trễ khi người dùng lướt phân trang.
- **Cách hoạt động**: Lấy một số từ `_gaussian_clamped` theo cấu hình `page_...`. Sau đó, dùng `random.random()` để quyết định có thêm một khoảng nghỉ dài `random.uniform(long_pause_min, long_pause_max)` vào hay không (giả lập việc người dùng dừng lại đọc một bài post thú vị).
- **Giá trị trả về**: Số giây cần chờ (float).

### 4. Hàm `comment_delay(config: CrawlDelayConfig = DEFAULT_DELAY_CONFIG) -> float`
- **Mô tả**: Sinh ra thời gian chờ khi người dùng click "Xem thêm bình luận".
- **Cách hoạt động**: Trả về trực tiếp số tính được từ `_gaussian_clamped` sử dụng các tham số `comment_...` trong cấu hình.
- **Giá trị trả về**: Số giây cần chờ (float).
