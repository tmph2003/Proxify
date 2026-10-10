# Tài Liệu Kỹ Thuật: Đại Tu Độ Ổn Định Hệ Thống Và Độ Tin Cậy Mạng (Proxify Stabilization & Network Reliability Overhaul)

## 1. Tóm tắt thay đổi

### A. Tầng Container & Điều Phối Dịch Vụ (`docker-compose.yml`)
1. **Loại bỏ thẻ cấu hình lỗi thời:** Gỡ bỏ `version: '3.8'` theo chuẩn Docker Compose v2 hiện đại, loại bỏ warning khởi động.
2. **Bổ sung Native Healthcheck cho toàn bộ container:**
   - `proxify_app`: Kiểm tra đồng thời socket port 8080 (Mitmproxy) và port 8888 (Dashboard Backend) bằng script socket Python nội bộ (`interval: 10s`, `timeout: 5s`, `retries: 3`, `start_period: 15s`).
   - `proxify_ui`: Kiểm tra HTTP server Nginx port 80 bằng `wget -q --spider http://127.0.0.1:80/` (`interval: 10s`, `timeout: 5s`, `retries: 3`, `start_period: 5s`).
   - Ràng buộc quan hệ phụ thuộc: `ui` phụ thuộc `proxify` với `condition: service_healthy`; `proxify` phụ thuộc `db` với `condition: service_healthy`.
   - Giữ vững chính sách tự phục hồi `restart: unless-stopped` trên cả 3 dịch vụ.

### B. Phân Định Ranh Giới Lưu Lượng & Đồng Bộ Bypass (`docker-compose.yml`, `.env`, `server.py`, `router.py`, Windows Registry, WinHTTP)
1. **Target Intercept Domains (Kích hoạt MITM & Plugins trích xuất / chặn quảng cáo):**
   - YouTube: `youtube.com`, `googlevideo.com`, `youtubei.googleapis.com` (chặn quảng cáo, anti-AFK, streaming trực tiếp).
   - Facebook: `facebook.com`, `messenger.com` (trích xuất GraphQL).
   - Zalo Web: `chat.zalo.me` (trích xuất tin nhắn, nhóm, thành viên).
   - **Thay đổi then chốt:** Đã loại bỏ `zalo.me`, `chat.zalo.me`, `zaloapp.com` khỏi danh sách `IGNORE_HOSTS` và `ProxyOverride` trên Windows để đảm bảo Zalo Web trên trình duyệt được chuyển tiếp qua proxy và kích hoạt plugin trích xuất bình thường.
2. **Direct Passthrough / System Bypass (Zero SSL decryption, Zero protocol overhead):**
   - Google Workspace: `mail.google.com`, `chat.google.com`, `accounts.google.com`, `*.clients6.google.com`, `client-channel.google.com`, `contacts.google.com`, `meet.google.com`, `drive.google.com`, `docs.google.com`.
   - GitHub: `github.com`, `*.github.com`, `*.githubassets.com`, `*.githubusercontent.com`.
   - Zalo PC Native Desktop App: `*.zadn.vn`, `*.zing.vn` (media CDN và telemetry/sync server).
   - Windows OS Telemetry: `*.microsoft.com`, `*.windowsupdate.com`, `*.live.com`, `*.office.com`, `*.msftncsi.com`.
3. **Đồng bộ hóa Windows:**
   - Cập nhật Windows Registry `ProxyOverride` (`HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings`).
   - Đồng bộ sang WinHTTP (`netsh winhttp set proxy proxy-server="127.0.0.1:8080" bypass-list="..."`).
   - Chuẩn hóa tiền tố wildcard: Hỗ trợ cả định dạng `*.domain.com` và `domain.com` trong `ProxyRouter` và `server.py` bằng cơ chế strip `*.` tự động.

### C. Khả Năng Tự Phục Hồi & Chống Sập Proxy Khi Gặp Sự Cố Kết Nối / Database
1. **`backend/proxify/core/database.py`:**
   - Bổ sung `import asyncio` (sửa lỗi nghiêm trọng `NameError: name 'asyncio' is not defined` làm sập vòng lặp retry kết nối CSDL).
   - Bổ sung cơ chế thử lại tự động (`max_retries=5`, `retry_interval=2.0s`) trong `DatabaseManager.connect()` khi khởi tạo `asyncpg.Pool`, giúp Proxify tự động đợi và kết nối lại nếu PostgreSQL đang khởi động hoặc gặp chập chờn mạng.
2. **`backend/proxify/core/eventbus.py` & `backend/proxify/core/worker.py`:**
   - Kiểm tra trạng thái pool (`if not self.db_pool or getattr(self.db_pool, '_closed', False): return`) trước khi acquire connection, tránh unhandled exception làm gián đoạn worker loop hoặc event bus.
3. **`backend/proxify/database/connection.py`:**
   - Tự động phát hiện connection bị đóng (`conn.closed != 0` theo đúng mã integer của psycopg2) trong `DatabasePool.get_connection()`, hủy bỏ connection chết và cấp mới; trong `release_connection()`, truyền `close=True` cho `putconn()` nếu socket đã ngắt.
   - Bổ sung `self.close()` khi gặp ngoại lệ và kiểm tra `getattr(self._pool, 'closed', False)` trong `_ensure_pool()` để tự động tái tạo pool sạch khi CSDL khởi động lại.
4. **`backend/proxify/core/router.py`:**
   - **Khử trùng lặp Interceptor trong Trie Router (Interceptor Deduplication):** Bổ sung cơ chế khử trùng lặp có bảo toàn thứ tự duyệt cho `matched_observers` và `matched_mutators` trong `_search()`. Ngăn chặn việc một interceptor đăng ký cho cả domain cha và domain con (ví dụ `zalo.me` và `chat.zalo.me`) bị kích hoạt 2 lần trên cùng một HTTP flow, gây ra tình trạng tiêm script lặp lại hoặc ghi CSDL trùng bản ghi.
   - **Chuẩn hóa đối sánh ranh giới tên miền (Domain Boundary Isolation):** Chuyển từ kiểm tra chuỗi con lỏng lẻo (`h in host_lower`) sang đối sánh hậu tố tên miền chặt chẽ (`host_lower == h or host_lower.endswith('.' + h)`), ngăn chặn việc các domain giả mạo/nhái (ví dụ `fake-github.com`, `amazing.vn`) bị bypass sai lệch.
   - **Chuẩn hóa Host kèm Port (`host:port` Normalization):** Tách bỏ cổng `:port` (`raw_host.split(':', 1)[0]`) trong `is_ignored`, `stream_domains`, `_search`, và `_insert`. Đảm bảo các luồng HTTP/CONNECT gửi kèm cổng (ví dụ `youtube.com:443`, `googlevideo.com:443`, `github.com:443`) khớp chính xác vào cây Radix Trie và danh sách streaming thay vì bị rớt tìm kiếm.
   - **Bảo vệ toàn diện trước NoneType:** Kiểm tra `if not flow or not flow.request:` và bọc an toàn `domain = flow.request.pretty_host or ""`, loại bỏ hoàn toàn lỗi `AttributeError: 'NoneType' object has no attribute 'lower'` trong `_search` khi xử lý luồng lỗi hoặc ngắt kết nối socket thô.
   - **Xử lý an toàn Content-Length & URL:** Bọc chuyển đổi `int(content_length)` trong khối `try...except (ValueError, TypeError)` và gán mặc định chuỗi rỗng cho `urlparse(flow.request.pretty_url or "")`.
   - **Bảo vệ luồng streaming:** Áp dụng đối sánh hậu tố tên miền cho `stream_domains` (`clean_host == d or clean_host.endswith('.' + d)`).
   - Đóng gói (isolate) toàn bộ quá trình thực thi của Observers và Mutators trong `route_request`, `route_responseheaders`, và `route_response` bằng block `try...except`. Nếu một plugin hoặc observer phát sinh ngoại lệ, lỗi chỉ được ghi log an toàn và tuyệt đối không bao giờ làm sập luồng xử lý proxy của người dùng.
5. **`backend/proxify/server.py` & SDK (`backend/proxify/sdk/context.py`):**
   - **Lưới an toàn cấp cao (Top-Level Exception Safety) trong `ProxyAddon`:** Bọc toàn bộ các hook `request()`, `responseheaders()`, và `response()` trong khối `try...except Exception as e:` ghi log chi tiết, bảo đảm không một ngoại lệ ngoài dự kiến nào từ router có thể làm crash pipeline hoặc làm rớt luồng HTTP của Mitmproxy.
   - **Tích lũy tên miền mục tiêu trong SDK (`ExtensionContext`):** Sửa đổi `register_mutator()` và `register_observer()` trong `context.py` để sử dụng phép hợp (`union`) tên miền thay vì ghi đè (`set(domains)`), bảo đảm các lần gọi đăng ký bổ sung không làm mất đi các domain mục tiêu đã đăng ký trước đó.
   - **Neo biểu thức chính quy (Regex Boundary Anchors) cho Mitmproxy `ignore_hosts`:** Xây dựng pattern `rf"(?:^|\.){re.escape(h)}(?::|$)"` đảm bảo chỉ khớp chính xác domain hoặc subdomain hợp lệ (kèm port tùy chọn), loại bỏ hoàn toàn nguy cơ bypass các domain chứa chuỗi con trùng lặp.
   - Sử dụng tách cổng và đối sánh hậu tố tên miền trong `V1GlobalObserver.handle_response`, kèm None-guard trên `flow.response`.
6. **`backend/proxify/dashboard.py`:**
   - Khôi phục route `/api/config` bên cạnh `/api/health` và `/api/status` (khắc phục lỗi 404 Not Found khi frontend hoặc kịch bản kiểm thử đọc cấu hình).
   - Bổ sung `/api/health` vào bộ lọc `PollingEndpointFilter` để giữ cho console log sạch sẽ.
   - Bọc an toàn `await request.json()` trong `_handle_toggle_db` bằng `try...except` trả về HTTP 400 Bad Request thay vì crash 500 khi nhận body dị dạng.
7. **`backend/proxify/utils/youtube_utils.py` & Extensions (`youtube`, `zalo`, `facebook`):**
   - **`is_youtube_ad_request`:** Chuẩn hóa domain và sử dụng đối sánh hậu tố domain chặt chẽ (`clean_domain == ad_d or clean_domain.endswith('.' + ad_d)`), ngăn chặn việc chặn nhầm các domain bên thứ ba có chuỗi con giống DoubleClick (`fake-doubleclick.net`).
   - **`YouTubeExtension` & `YouTubePlugin`:** Đăng ký toàn bộ `_yt_mutator_domains` trong một lệnh gọi duy nhất thay vì lặp qua từng domain làm ghi đè mất `youtube.com`. Bổ sung kiểm tra an toàn `flow.request` và chuẩn hóa host, đảm bảo `www.youtube.com/pagead/...` bị chặn dứt điểm với HTTP 204.
   - **`ZaloPlugin` & `ZaloExtension`:** Định nghĩa `target_domains = ["chat.zalo.me", "zalo.me"]` và chuẩn hóa kiểm tra domain bằng `self.target_domains` thay vì substring `'zalo' in domain`, chấm dứt việc Zalo plugin chạy như mutator toàn cục trên mọi request của hệ thống.
   - **`FacebookGraphQLObserver`:** Bổ sung `messenger.com` vào `target_domains` theo đúng yêu cầu R2.

### D. Kịch Bản Kiểm Tra Tự Động Toàn Diện (`scripts/verify_system_stability.py`) & Bộ Test Mở Rộng
- Xây dựng script Python độc lập kiểm chứng khách quan 4 trụ cột hệ thống:
  1. Kiểm tra sức khỏe Docker (`proxify_app`, `proxify_ui`, `proxify_db` đều chạy và ở trạng thái healthy) cùng tính khả dụng của port 8080 và 8888, kèm endpoint `/api/health` và `/api/config`.
  2. Kiểm tra kết nối YouTube (HTTP 200) và tính tương thích streaming video (`googlevideo.com`).
  3. Kiểm tra Direct Passthrough cho Google Workspace (`mail.google.com`) và GitHub (`github.com`) với chứng chỉ số TLS xịn (Google Trust Services, Sectigo/DigiCert), 0 lỗi SSL, 0 lỗi giao thức, kiểm chứng danh sách bypass Windows `ProxyOverride` / WinHTTP (bao gồm toàn bộ 12 domain yêu cầu: Google Workspace, GitHub, Zalo PC native app, Windows Update), và xác minh cô lập ranh giới tên miền của Router (chuẩn hóa port, từ chối bypass các domain nhái như `fake-github.com`, `amazing.vn`, an toàn với input None).
  4. Chạy toàn bộ 86 test unit/integration backend mà không gây hồi quy (72 test nguyên bản + 14 test mở rộng bao quát: khử trùng lặp Trie, tích lũy `target_domains`, chặn ad YouTube qua Extension, exception guard của ProxyAddon, None safety, port normalization, và phục hồi pool trong `tests/test_router_and_resilience.py`).

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Vấn đề Cần Khắc Phục
1. **Thiếu cơ chế Healthcheck chuẩn:** Trước đây Docker chỉ hiển thị `Up ...` mà không giám sát socket port 8080 hay 8888, khiến Docker daemon không thể phát hiện nếu process Python bên trong bị treo (hang) hoặc rớt socket.
2. **Mập mờ ranh giới lưu lượng (Traffic Boundary Ambiguity):**
   - Zalo Web (`chat.zalo.me`) bị nhầm lẫn và đưa chung vào `IGNORE_HOSTS` cùng Zalo PC, dẫn đến việc plugin trích xuất tin nhắn Zalo Web không thể can thiệp dữ liệu.
   - Windows Telemetry (`microsoft.com`, `windowsupdate.com`, `msftncsi.com`) không có trong `IGNORE_HOSTS`, làm tăng tải vô ích cho event loop của mitmproxy khi Windows liên tục gửi HTTP CONNECT đến proxy.
3. **Nguy cơ gián đoạn do ngoại lệ không xử lý:**
   - Khi client ngắt kết nối giữa chừng hoặc pool database gặp sự cố gián đoạn tạm thời, các tác vụ async không được bọc try/except có thể ném exception không bắt được, tiềm ẩn nguy cơ làm gián đoạn pipeline proxy.
   - Khi request gửi kèm cổng trên header Host hoặc ngắt kết nối socket trước khi gửi header, các hàm router xử lý chuỗi trực tiếp mà không tách port hoặc không kiểm tra NoneType gây ra lỗi `AttributeError` hoặc thất bại trong đối sánh trie.

### Giá trị Kiến trúc Mang Lại
- **Nguyên lý Single Responsibility & Open-Core Boundary:** Phân định rõ ràng: việc gì cần can thiệp (YouTube adblock, Zalo Web / Facebook crawl) thì can thiệp sâu; việc gì là lưu lượng công việc / hệ điều hành (Google Mail, Google Chat, GitHub, Windows Telemetry, Zalo PC Native) thì chuyển tiếp trực tiếp (Zero SSL Decryption, Zero Overhead Passthrough).
- **Phòng thủ đa tầng (Defense-in-Depth):** Hệ thống có 2 tầng bypass: tầng Winsock OS (`ProxyOverride`) chuyển thẳng ra Gateway mạng không chạm vào port 8080; tầng Mitmproxy (`IGNORE_HOSTS`) làm lưới an toàn dự phòng thực hiện TCP Tunneling thô nếu ứng dụng gửi nhầm đến port 8080.
- **Tính tự phục hồi cao (Self-Healing & Resilience):** Mọi sự cố ngắt kết nối client hoặc khởi động lại database đều có cơ chế retry và bắt lỗi tại chỗ, đảm bảo dịch vụ proxy duy trì thời gian uptime 100%.

---

## 3. Mối liên hệ

| File / Thành phần | Mối liên hệ & Tác động |
|---|---|
| `docker-compose.yml` | Khai báo healthcheck, restart policy, phụ thuộc service_healthy và biến `IGNORE_HOSTS` cho toàn bộ container |
| `.env` / `backend/proxify/server.py` | Cung cấp giá trị cấu hình đồng bộ `IGNORE_HOSTS` cho môi trường chạy độc lập và container |
| `backend/proxify/core/router.py` | Định tuyến lưu lượng theo Radix Trie, chuẩn hóa domain bỏ qua, chuẩn hóa cổng `:port`, cách ly ngoại lệ của interceptors |
| `backend/proxify/core/database.py` | Quản lý kết nối `asyncpg.Pool` với retry tự động khi kết nối CSDL |
| `backend/proxify/core/eventbus.py` | Bộ đệm lưu trữ sự kiện phi đồng bộ, kiểm tra trạng thái pool trước khi flush |
| `backend/proxify/core/worker.py` | Worker chuẩn hóa nền (CQRS), bảo vệ vòng lặp xử lý không bị crash bởi lỗi dữ liệu |
| `backend/proxify/database/connection.py` | Pool đồng bộ psycopg2, tự động thanh lọc kết nối hỏng/chết và tái tạo khi pool đóng |
| `backend/proxify/dashboard.py` | Cung cấp API giám sát và endpoint `/api/health` cho Docker healthcheck, bảo vệ `/api/toggle_db` |
| `backend/proxify/utils/youtube_utils.py` | Tiện ích bóc tách quảng cáo và chống AFK, đối sánh tên miền nghiêm ngặt |
| `backend/extensions/youtube/` | Extension YouTube: chuẩn hóa an toàn host, chặn quảng cáo không gây lỗi |
| `backend/extensions/zalo/` | Extension Zalo: giới hạn đúng phạm vi tên miền mục tiêu Zalo Web thay vì can thiệp toàn cục |
| `backend/extensions/facebook/` | Extension Facebook: bổ sung messenger.com vào danh sách theo dõi |
| `scripts/verify_system_stability.py` | Công cụ tự động hóa kiểm định toàn diện chất lượng và độ ổn định của hệ thống |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Khách hàng truy cập domain Zalo mới:**
   - *Rủi ro:* Nếu Zalo phát hành thêm domain CDN mới ngoài `*.zadn.vn` và `*.zing.vn`, Zalo PC có thể gửi request qua proxy.
   - *Khắc phục:* Có thể dễ dàng bổ sung domain mới vào `ProxyOverride` và `IGNORE_HOSTS` mà không cần sửa code lõi.
2. **Khởi động lại hệ điều hành Windows:**
   - *Đánh giá:* Cấu hình `ProxyOverride` đã được lưu vĩnh viễn vào Windows Registry và WinHTTP, bảo toàn cấu hình sau khi restart máy.
3. **Kiểm tra thu hồi chứng chỉ khi dùng công cụ dòng lệnh (curl):**
   - *Đánh giá:* Windows Schannel curl thực hiện kiểm tra OCSP/CRL nghiêm ngặt. Khi curl truy cập domain bị MITM (như `youtube.com`), file cấu hình `.curlrc` / `_curlrc` chứa `ssl-no-revoke` giúp curl kiểm thử tự động mượt mà, trong khi các trình duyệt thông thường (Chrome, Edge) đã tin cậy CA cục bộ trong Windows Trusted Root Store mà không bị ảnh hưởng.

