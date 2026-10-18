# ⚡ Tối Ưu Hóa Event Loop & Loại Bỏ Jitter Ngắt Quãng Khi Duyệt Web Qua Proxify

## 1. Tóm tắt thay đổi
Khắc phục triệt để hiện tượng mạng "thi thoảng bị khựng/chậm" (intermittent latency spikes) khi bật Proxify do **nghẽn Single Event Loop** và **giải mã TLS dư thừa trên các CDN tĩnh**:

1. **`backend/proxify/dashboard.py`**:
   - Chuyển toàn bộ các lời gọi đồng bộ xuống `RequestStorage` (`query_requests`, `get_request`, `get_domains`, `get_stats`, `get_requests_for_export`, `delete_requests`) sang thread pool thông qua `await asyncio.to_thread(...)`.
   - Trước đó, mỗi lần giao diện hoặc Chrome Extension gọi `/api/domains`, `/api/stats`, `/api/requests`, hàm `self.storage.flush()` (`threading.Event.wait()`) và truy vấn `psycopg2` chạy trực tiếp trên main thread của `asyncio`, làm đóng băng hoàn toàn `mitmproxy` (vốn dùng chung 1 event loop) trong suốt thời gian chờ ổ cứng/DB.

2. **`backend/proxify/core/listeners.py` & `backend/proxify/server.py`**:
   - Trong `DashboardBroadcaster`: Thay `len(response.content)` bằng `len(response.raw_content)`. Trong `mitmproxy`, việc truy cập thuộc tính `.content` sẽ kích hoạt giải nén đồng bộ (Zstd / Brotli / Gzip) trên toàn bộ body ngay trên main event loop chỉ để đếm số byte.
   - Trong `V1GlobalObserver.handle_response`: Bỏ qua ngay các response đã được đánh dấu `flow.response.stream = True` và đẩy `self.db_writer(flow, db_save)` sang `loop.run_in_executor(None, ...)` khi `db_save=True` để việc giải nén/parse JSON payload lớn không bao giờ chặn luồng mạng.

3. **`backend/proxify/server.py` (`explicit_bypasses`)**:
   - Bổ sung các domain CDN tĩnh và MQTT/WebSocket chat (`fbcdn.net`, `fbsbx.com`, `edge-chat.facebook.com`, `web-chat-e2ee.facebook.com`, `gateway.facebook.com`, `ytimg.com`, `ggpht.com`, `gstatic.com`, `githubassets.com`, `githubusercontent.com`) vào `explicit_bypasses` (`ignore_hosts` ở tầng TCP của mitmproxy).
   - Giúp hàng chục kết nối tải ảnh/video/font/socket đi thẳng qua TCP Passthrough ở tốc độ gốc mà không tốn CPU sinh chứng chỉ RSA/ECDSA giả lập cho từng subdomain CDN.

## 2. Mục đích & Ý nghĩa
- **Đảm bảo Zero Event-Loop Blocking**: Vì `Mitmproxy DumpMaster` và `aiohttp Dashboard` cùng chia sẻ một `asyncio` event loop duy nhất, bất kỳ tác vụ blocking I/O hoặc CPU-bound nào trong Dashboard/Observer cũng sẽ làm toàn bộ các gói tin đang duyệt trên trình duyệt bị khựng lại. Việc tách hoàn toàn sang `asyncio.to_thread` / `run_in_executor` giữ cho event loop luôn phản hồi dưới 1ms.
- **Loại bỏ chi phí MITM TLS Handshake vô ích trên CDN**: Khi lướt Facebook hoặc YouTube, trình duyệt mở đồng thời kết nối tới hàng chục shard `scontent.*.fna.fbcdn.net` và `i.ytimg.com`. Việc bypass ở tầng TCP giúp ảnh và video hiện ra tức thì.

## 3. Mối liên hệ
- Ảnh hưởng trực tiếp đến `backend/proxify/server.py`, `backend/proxify/dashboard.py`, và `backend/proxify/core/listeners.py`.
- Tương thích hoàn toàn với toàn bộ 52 bài kiểm thử trong `backend/tests/`.

## 4. Rủi ro (Risks & Edge Cases)
- **Kích thước hiển thị trên Dashboard (`response_size`)**: Do `DashboardBroadcaster` đọc `len(response.raw_content)` để tránh giải nén trên main loop, kích thước hiển thị trên bảng Live Traffic sẽ là kích thước gói tin thực tế truyền qua mạng (compressed wire size), còn khi lưu vào DB (`DatabaseWriter` chạy trên background thread) vẫn giải nén đầy đủ nội dung văn bản.
