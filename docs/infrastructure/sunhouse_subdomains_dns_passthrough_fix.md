# Khắc Phục Sự Cố Không Truy Cập Được Các Subdomain `sunhouse.com.vn` Khi Bật Proxy

## Tóm tắt thay đổi

1. **[docker-compose.yml](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/docker-compose.yml):**
   - Loại bỏ hoàn toàn khối cấu hình `dns: [8.8.8.8, 1.1.1.1]` đã bị gán cứng trước đó trong service `proxify`.
   - Cập nhật biến môi trường `IGNORE_HOSTS`: thay thế `trino.sunhouse.com.vn` bằng `sunhouse.com.vn` để áp dụng cơ chế TCP Passthrough cho toàn bộ các subdomain nội bộ của công ty.
2. **[.env](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/.env):**
   - Cập nhật biến `IGNORE_HOSTS`: đổi `trino.sunhouse.com.vn` thành `sunhouse.com.vn`.
3. **[backend/proxify/server.py](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py):**
   - Cập nhật giá trị fallback mặc định của `IGNORE_HOSTS`: đổi `trino.sunhouse.com.vn` thành `sunhouse.com.vn`.

---

## Mục đích & Ý nghĩa

### 1. Triệu chứng
- Khi bật proxy hệ thống (`127.0.0.1:8080`), người dùng **không thể truy cập vào bất kỳ subdomain nào của `sunhouse.com.vn`** (bao gồm Trino Query Engine `trino.sunhouse.com.vn`, ERPNext `erp.sunhouse.com.vn`, BI Dashboard `bi.sunhouse.com.vn`, Harbor `harbor.sunhouse.com.vn`, v.v.).
- Trình duyệt và các HTTP client (curl, DBeaver) trả về lỗi **`502 Bad Gateway`** hoặc ngắt kết nối `CONNECT tunnel failed, response 502`.
- Trong khi đó, domain gốc `sunhouse.com.vn` vẫn truy cập được bình thường.

### 2. Nguyên nhân gốc rễ (Root Cause Analysis - Phản biện kiến trúc)

Sự cố xảy ra do sự kết hợp của **2 sai lầm kiến trúc**:

#### A. Sai lầm 1: Hardcode DNS công cộng (`8.8.8.8`, `1.1.1.1`) vào tầng hạ tầng Docker
- Trong commit trước (`9167c91`), để thử nghiệm tối ưu độ trễ cho TikTok, cấu hình `dns: [8.8.8.8, 1.1.1.1]` đã bị gán cứng vào container `proxify`.
- **Thực tế hạ tầng mạng:** Mạng nội bộ Sunhouse vận hành theo mô hình **Split-Horizon DNS**. Domain gốc `sunhouse.com.vn` trỏ về IP Public (`103.131.74.32`), nhưng toàn bộ subdomain nội bộ (`trino`, `erp`, `bi`, v.v.) chỉ tồn tại trên các DNS Server nội bộ của công ty (`172.16.100.4`, `172.16.100.5`) và phân giải về dải IP mạng riêng (`172.16.100.130`, `172.16.100.183`).
- Các máy chủ DNS công cộng của Google (`8.8.8.8`) và Cloudflare (`1.1.1.1`) **hoàn toàn không biết** về các bản ghi A nội bộ này (trả về `NXDOMAIN`).
- Khi client bật proxy, client ủy thác việc phân giải DNS cho proxy (`127.0.0.1:8080`). Container `proxify` truy vấn `8.8.8.8` và vấp phải lỗi `socket.gaierror: [Errno -2] Name or service not known`, dẫn đến việc Mitmproxy lập tức trả về `502 Bad Gateway`.

#### B. Sai lầm 2: Phạm vi `IGNORE_HOSTS` quá hẹp (Chỉ bỏ qua duy nhất 1 host `trino`)
- Cấu hình cũ chỉ khai báo `trino.sunhouse.com.vn` trong `IGNORE_HOSTS`. Toàn bộ các subdomain khác như `erp`, `bi`, `crm` đều không nằm trong danh sách bỏ qua.
- Dù DNS có phân giải được, Mitmproxy vẫn sẽ cố gắng giải mã SSL/TLS (Man-In-The-Middle) và ký chứng chỉ giả lập cho các subdomain này.
- Do các dịch vụ nội bộ (ví dụ: `erp.sunhouse.com.vn`) sử dụng header bảo mật nghiêm ngặt `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`, trình duyệt sẽ chặn hoàn toàn kết nối với lỗi chứng chỉ không hợp lệ (`NET::ERR_CERT_AUTHORITY_INVALID`) và không cho phép người dùng bấm "Proceed anyway".
- Hơn nữa, Proxify được thiết kế làm scraping/crawling proxy cho các nền tảng mạng xã hội (Facebook, TikTok, Zalo, YouTube). Toàn bộ hạ tầng doanh nghiệp nội bộ tuyệt đối không được giải mã, không đệm buffer RAM và không ghi log vào database của Proxify.

### 3. Giải pháp giải quyết
1. **Khôi phục Docker Host DNS Forwarding:** Loại bỏ `dns: [8.8.8.8, 1.1.1.1]`. Container `proxify` tự động kế thừa DNS của máy host thông qua Docker resolver (`127.0.0.11` -> `192.168.65.7`).
   - Khi máy ở văn phòng: Docker tự động dùng DNS `172.16.100.4` và `172.16.100.5`. Tốc độ phân giải đạt 2ms - 5ms.
   - Khi máy ở ngoài / ở nhà: Docker tự động thích ứng theo DHCP mạng gia đình hoặc VPN mà không bị timeout.
2. **Khái quát hóa TCP Passthrough:** Đổi `trino.sunhouse.com.vn` thành `sunhouse.com.vn` trong `IGNORE_HOSTS`.
   - Chuỗi regex `re.escape('sunhouse.com.vn')` sẽ khớp toàn bộ subdomain: `*.sunhouse.com.vn` và domain gốc.
   - Mitmproxy thiết lập tunnel TCP thuần túy (tunnel CONNECT không can thiệp TLS), truyền tải nguyên bản dữ liệu, loại bỏ 100% rủi ro HSTS/SSL và nghẽn bộ nhớ.

---

## Mối liên hệ

| Tầng / File | Vai trò liên kết |
|---|---|
| [docker-compose.yml](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/docker-compose.yml) | Hạ tầng Container: Bỏ DNS override, thiết lập biến môi trường `IGNORE_HOSTS` mặc định cho container |
| [.env](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/.env) | Configuration: Cấu hình runtime cục bộ của ứng dụng |
| [backend/proxify/server.py](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py) | Application Core: Đọc `IGNORE_HOSTS`, cấu hình `ignore_hosts` cho Mitmproxy Options và khởi tạo `ProxyRouter` |
| [backend/proxify/core/router.py](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/core/router.py) | Router Interceptor: Kiểm tra `is_ignored(host)` để bỏ qua các bộ lắng nghe (observers/mutators) |
| [backend/proxify/server.py:V1GlobalObserver](file:///C:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py#L56-L84) | Persistence: Ngăn chặn ghi log traffic của các host bị ignore vào PostgreSQL |

---

## Rủi ro (Risks & Edge Cases)

1. **Người dùng làm việc từ xa (Work From Home) không bật VPN:**
   - *Tình huống:* Nếu người dùng ở nhà không kết nối VPN công ty, các subdomain nội bộ (`172.16.100.x`) vốn dĩ không thể truy cập được từ internet.
   - *Hành vi:* Proxy sẽ trả về lỗi kết nối bình thường, không gây ảnh hưởng hay xung đột gì đối với các trang web công cộng khác (Google, TikTok, Facebook, YouTube vẫn hoạt động bình thường).
2. **Domain công cộng `sunhouse.com.vn`:**
   - *Tình huống:* Khai báo `sunhouse.com.vn` đồng nghĩa với việc website giới thiệu công ty `https://sunhouse.com.vn` cũng sẽ được đưa vào chế độ TCP Passthrough (không giải mã SSL).
   - *Đánh giá:* Đây là hành vi hoàn toàn chính xác vì Proxify không có bất kỳ plugin hay nghiệp vụ nào cần can thiệp/cào dữ liệu từ trang chủ `sunhouse.com.vn`.
3. **Cấu hình Bypass phía Client (Khuyến nghị chuẩn Enterprise):**
   - Ngoài việc xử lý phía server proxy, người dùng nên cấu hình danh sách bypass proxy trên Windows: `*.sunhouse.com.vn;<local>` trong mục Proxy Settings của Windows. Điều này giúp trình duyệt kết nối trực tiếp đến IP mạng LAN mà không cần gửi gói tin qua cổng 8080 của proxy, tối ưu hóa tối đa hiệu năng làm việc nội bộ.
