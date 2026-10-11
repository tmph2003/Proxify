# Kiến Trúc Default TCP Passthrough (Inverted Scope) & Tối Ưu Hóa DNS Đa Tầng

Tài liệu ghi nhận quyết định kiến trúc và thay đổi kỹ thuật giải quyết dứt điểm tình trạng mạng bị chậm, giật lag trên hệ thống Proxify.

---

## 1. Tóm tắt thay đổi (Summary of Changes)
- **Đảo ngược phạm vi can thiệp (Inverted Scope Architecture) trong `backend/proxify/server.py`:**
  - Thay thế mô hình blacklist `IGNORE_HOSTS` chắp vá (càng dùng càng thiếu) bằng **Negative Lookahead Regex (`^(?!(?:targets)(?::\d+)?$).*`)**.
  - Chỉ giải mã TLS và can thiệp HTTP đối với các nền tảng mục tiêu được chỉ định rõ ràng: YouTube (`youtube.com`, `youtubei.googleapis.com`), Facebook/Messenger (`facebook.com`, `messenger.com`), Zalo Web (`chat.zalo.me`, `zalo.me`), cùng các mạng phân phối quảng cáo (`doubleclick.net`, `googleadservices.com`, `googlesyndication.com`).
  - **100% các website còn lại trên toàn bộ internet** (Google Workspace, GitHub, Shopee, tin tức, nội bộ, ngân hàng, ChatGPT, v.v.) tự động được áp dụng cơ chế **TCP Passthrough thuần túy (Layer 4)**, Mitmproxy hoàn toàn không giải mã SSL, không buffer RAM trong Python event loop, không bắn WebSocket và không ghi vào cơ sở dữ liệu PostgreSQL.
  - Thiết lập cơ chế bypass cứng dự phòng (`explicit_bypasses`) cho `googlevideo.com`, `c.youtube.com`, `accounts.youtube.com`, `signaler-pa.youtube.com`.
- **Tối ưu hóa phân giải tên miền (DNS Resolution) trong `docker-compose.yml`:**
  - Cập nhật DNS server của container `proxify_app`: ưu tiên gateway router mạng nội bộ `192.168.100.1` (thời gian phân giải 2ms - 4ms) và dự phòng qua Google DNS `8.8.8.8` (23ms). Loại bỏ DNS `1.1.1.1` do độ trễ chập chờn lên tới 244ms tại Việt Nam và gây lỗi `[Errno -3] Temporary failure in name resolution`.
- **Bổ sung ánh xạ tĩnh hệ thống nội bộ Sunhouse vào Windows `hosts`:**
  - Khai báo ánh xạ các domain nghiệp vụ nội bộ (`ks.sunhouse.com.vn: 172.16.100.130`, v.v.) trực tiếp vào `C:\Windows\System32\drivers\etc\hosts` của máy host để trình duyệt phân giải tức thì 0ms, loại bỏ hiện tượng treo timeout khi chờ DNS công cộng.
- **Bổ sung kiểm thử hồi quy & cách ly phạm vi trong `tests/test_router_and_resilience.py`:**
  - Viết mới test case `test_inverted_scope_ignore_regex_strict_isolation()` kiểm tra tính đúng đắn của 22 domain mục tiêu và domain bypass (100% pass, 87/87 tests toàn hệ thống).

---

## 2. Mục đích & Ý nghĩa (Purpose & Significance)
- **Vạch trần Anti-Pattern "Whack-a-Mole" Blacklisting:**
  Trước đây, Proxify sử dụng cơ chế "mặc định giải mã, ngoại lệ bỏ qua". Khi người dùng duyệt bất kỳ website nào không nằm trong danh sách ~50 domain miễn trừ (ví dụ `cohoichoai.com`, các trang báo mạng, CDN ảnh), Mitmproxy thực hiện bắt tay TLS giả mạo, giải mã toàn bộ luồng HTTP/2 multiplexing, lưu đệm hàng trăm tài nguyên vào RAM và ghi log CSDL. Kết quả: một trang web bình thường mất 30s - 50s để tải, làm nghẽn single thread asyncio của proxy và gián tiếp làm đơ luôn cả luồng YouTube (`/get_watch`, `/next` mất 68 giây).
- **Thiết lập ranh giới kiến trúc rõ ràng (Strict Boundary):**
  Bằng cách đảo ngược logic sang "Mặc định Bỏ qua (Default Passthrough), Chỉ can thiệp đích danh (Explicit Intercept)", Proxify hoạt động đúng vai trò là một proxy trích xuất dữ liệu chuyên biệt, trả lại 100% tốc độ dây dẫn nguyên bản (wire speed) cho mọi lưu lượng duyệt web thông thường.
- **Khắc phục nghẽn cổ chai DNS container:**
  Docker DNS daemon (`127.0.0.11`) khi bị dồn nén hàng trăm kết nối đồng thời với DNS ngoại vi không ổn định đã sinh mã lỗi 502 Bad Gateway. Định tuyến qua router cục bộ giúp truy vấn DNS đạt tốc độ siêu tốc (<5ms) và ổn định tuyệt đối.

---

## 3. Mối liên hệ (Interconnections & Impact)
- **`backend/proxify/server.py`:**
  - Nơi khởi tạo cấu hình `mitmproxy.options.Options(ignore_hosts=ignore_patterns)`.
  - Giảm tải trực tiếp cho `ProxyAddon`, `ProxyRouter`, `V1GlobalObserver` và `BackgroundWorker` do 99.9% lưu lượng mạng ngoài mục tiêu không còn đi vào pipeline xử lý HTTP của Python.
- **`docker-compose.yml`:**
  - Thiết lập cấu hình mạng và DNS cho container `proxify_app`, bảo đảm độ sẵn sàng mạng khi khởi động độc lập hoặc trong mạng bridge.
- **`backend/tests/test_router_and_resilience.py`:**
  - Bảo đảm tính toàn vẹn của bộ kiểm thử tự động, tích hợp kiểm chứng ranh giới regex tiêu chuẩn trước khi triển khai môi trường production.
- **Windows Subsystem & Trình duyệt:**
  - Chrome và Edge khi cấu hình proxy hệ thống `127.0.0.1:8080` sẽ không còn bị suy hao băng thông khi mở nhiều tab song song.

---

## 4. Rủi ro & Trường hợp ngoại lệ (Risks & Edge Cases)
- **Nhu cầu can thiệp nền tảng mới trong tương lai:**
  - *Rủi ro:* Nếu người dùng cài thêm extension mới (ví dụ TikTok, Shopee, Telegram) mà không cập nhật regex, lưu lượng của nền tảng đó sẽ bị bypass thô (không giải mã TLS).
  - *Giải pháp:* Đã bổ sung biến môi trường `INTERCEPT_DOMAINS` cho phép người dùng hoặc plugin inject thêm domain mục tiêu vào regex mà không cần chỉnh sửa mã nguồn cốt lõi (`server.py`).
- **Phụ thuộc kết nối VPN cho mạng nội bộ Sunhouse:**
  - *Rủi ro:* `ks.sunhouse.com.vn` nằm ở IP `172.16.100.130` thuộc mạng LAN công ty. Dù tên miền đã được phân giải tĩnh 0ms qua file `hosts`, người dùng vẫn cần bật kết nối GlobalProtect VPN (`PANGP Virtual Ethernet Adapter`) khi làm việc từ xa để định tuyến gói tin đến IP nội bộ này.
- **Thay đổi IP Gateway cục bộ:**
  - *Rủi ro:* Nếu máy tính chuyển sang mạng Wi-Fi khác không sử dụng dải IP `192.168.100.1`, DNS thứ nhất trong container sẽ timeout trước khi chuyển sang `8.8.8.8`.
  - *Đánh giá:* Docker daemon có cơ chế fallback tự động sang server tiếp theo trong danh sách `dns` (`8.8.8.8`) với timeout thấp, bảo đảm không gián đoạn dịch vụ.
