# Tối Ưu Hóa Mạng Gia Đình (Home Wi-Fi), Đồng Bộ MTU Docker Và Zero-Copy JS/CSS Streaming

## 1. Tóm tắt thay đổi
- **[`backend/proxify/core/router.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/core/router.py):**
  - Bổ sung `.css` vào `_STREAM_EXTENSIONS` và `text/css` vào `_STREAM_CONTENT_TYPES` để stream trực tiếp mọi file stylesheet mà không cần đệm trong RAM.
  - Bổ sung cơ chế **Smart JS Streaming** (`_JS_EXTENSIONS = (".js", ".mjs")`, `_JS_CONTENT_TYPES`) tại bước 6 của `ProxyRouter.route_responseheaders`: Tự động bật `flow.response.stream = True` cho tất cả các file JavaScript nếu domain đích không có Mutator nào cần sửa đổi mã nguồn JS (hoặc chỉ có `YouTube Enhancer` vốn chỉ xử lý HTML/JSON).
- **[`backend/extensions/zalo/extension.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/extensions/zalo/extension.py) & [`backend/extensions/zalo/plugin.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/extensions/zalo/plugin.py):**
  - Đăng ký tường minh tên miền CDN `zdn.vn` cùng với `chat.zalo.me` và `zalo.me` vào danh sách domain Mutator của `ZaloPlugin`, đảm bảo `ProxyRouter` vẫn giữ lại luồng đọc/inject JS hooks cho Zalo trong khi giải phóng 100% các trang web còn lại sang chế độ Zero-Copy Streaming.
- **[`docker-compose.yml`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/docker-compose.yml):**
  - Cấu hình `com.docker.network.driver.mtu: "1420"` cho mạng `default` bridge của Docker Compose để đồng bộ với giới hạn `MTU = 1420` của card mạng `Wi-Fi` trên máy chủ Windows.
- **[`backend/tests/test_router_and_resilience.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/tests/test_router_and_resilience.py):**
  - Bổ sung unit test `test_proxy_router_smart_js_and_css_streaming` (sử dụng `ExtensionLoader.discover_and_load`) kiểm chứng việc stream trực tiếp `.js`/`.css` trên các trang web phổ thông và YouTube, đồng thời bảo toàn cơ chế buffer để sửa `.js` trên `chat.zalo.me` và `zdn.vn` (57/57 unit tests pass 100%).
- **Hạ tầng DNS card Wi-Fi Windows & Xác thực Container:**
  - Chuyển DNS của card mạng `Wi-Fi` từ địa chỉ router gia đình (`192.168.100.1`) sang Cloudflare (`1.1.1.1`) và Google (`8.8.8.8`), xóa cache DNS hệ thống (`ipconfig /flushdns`).
  - Xác thực trực tiếp trong `proxify_app`: `/sys/class/net/eth0/mtu` đạt chuẩn **`1420`** và `TCP_MAXSEG` (MSS) hạ từ `1448` xuống **`1368`**.

---

## 2. Mục đích & Ý nghĩa
- **Triệt tiêu độ trễ Store-and-Forward trên các gói JavaScript lớn (1MB – 4MB):**
  - Trước đây, `ProxyRouter` không dám bật `stream = True` cho bất kỳ file `.js` hoặc `.css` nào trên toàn bộ Internet chỉ vì một mình `ZaloPlugin` cần sửa file `.js`. Điều này khiến Mitmproxy phải tải trọn vẹn 100% các gói bundle `.js` nặng vào RAM của container rồi mới bắt đầu gửi về trình duyệt Chrome. Trên mạng Wi-Fi 2.4GHz tại nhà, cơ chế *Store-and-Forward* này làm nhân đôi thời gian chờ tải trang.
  - Với cơ chế *Smart JS Streaming*, chỉ đúng các domain của Zalo (`zalo.me`, `chat.zalo.me`, `zdn.vn`) mới bị giữ lại trong RAM để tiêm hook, còn toàn bộ file `.js`/`.css` của YouTube (`base.js`), GitHub, ChatGPT, báo chí... đều được truyền thẳng qua ống TCP (Zero-Copy Streaming) với độ trễ bằng 0.
- **Xóa bỏ xung đột MTU (Split-TCP MSS Mismatch) giữa Docker và đường truyền PPPoE tại nhà:**
  - Card `Wi-Fi` trên Windows đã được cấu hình `MTU = 1420` (`TCP_MAXSEG = 1380`), nhưng card `eth0` bên trong container `proxify_app` trước đó vẫn giữ mặc định của Docker là `MTU = 1500` (`TCP_MAXSEG = 1448`).
  - Khi đi qua MITM Proxy (Split-TCP), kết nối từ container ra Internet đàm phán `MSS = 1448`, dẫn đến các gói tin lớn có cờ `DF (Don't Fragment)` bị rớt tại tầng vật lý/router nhà và phải chờ gói ICMP báo lỗi để truyền lại (TCP Retransmission).
  - Việc ép `com.docker.network.driver.mtu: "1420"` trong `docker-compose.yml` giúp container đàm phán chuẩn `MSS = 1380` ngay từ gói `SYN` đầu tiên.
- **Chấm dứt lỗi treo 8 giây (`[Errno -3] Temporary failure in name resolution`) do nghẽn DNS Router nhà:**
  - Khi mở trang web có hàng chục kết nối đồng thời, bộ chuyển tiếp DNS (`dnsmasq`) trên router gia đình `192.168.100.1` bị tràn hàng đợi UDP làm rơi truy vấn DNS từ Docker, gây treo đúng 8 giây cho mỗi kết nối lỗi. Chuyển DNS card `Wi-Fi` sang `1.1.1.1` / `8.8.8.8` giải quyết triệt để điểm nghẽn này mà không ảnh hưởng đến cấu hình DNS nội bộ khi cắm dây LAN hoặc VPN ở công ty.

---

## 3. Mối liên hệ
- **[`backend/proxify/core/router.py`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/core/router.py):** Liên kết trực tiếp với hệ thống `IMutatorInterceptor` của các extension (`YouTubeExtension`, `ZaloExtension`) để quyết định động việc bật/tắt `flow.response.stream` ngay tại pha `responseheaders`.
- **[`docker-compose.yml`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/docker-compose.yml):** Quản lý giao diện mạng `eth0` của toàn bộ các container (`proxify_app`, `proxify_ui`, `proxify_db`).

---

## 4. Rủi ro (Risks & Edge Cases)
- **Khi thêm Extension mới có nhu cầu sửa đổi file `.js`:**
  - Nếu trong tương lai có thêm một `IMutatorInterceptor` mới cần sửa đổi nội dung file `.js` trên một tên miền cụ thể, developer chỉ cần đăng ký đúng tên miền đó (bao gồm cả domain CDN chứa file `.js`, tương tự như cách `zdn.vn` được đăng ký cho `ZaloExtension`). `ProxyRouter` sẽ tự động nhận diện có mutator trên domain đó và tắt streaming `.js` cho riêng domain đó mà không cần sửa lại code của `ProxyRouter`.
