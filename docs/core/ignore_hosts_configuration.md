# Tài Liệu Kỹ Thuật: Cấu Hình Bỏ Qua Domain (Ignore Hosts & TCP Passthrough)

- **Ngày cập nhật:** 2026-09-03
- **Tác giả:** Antigravity Principal Architect
- **Các module tác động:**
  - `docker-compose.yml`
  - `.env`
  - `backend/proxify/core/router.py`
  - `backend/proxify/server.py`
- **Tài liệu tham chiếu:** `.agents/rules/auto_doc.md`, `GEMINI.md`

---

## 1. Tóm tắt thay đổi

1. **Cấu hình môi trường (`.env` & `docker-compose.yml`)**:
   - Khai báo và bổ sung `trino.sunhouse.com.vn` vào biến môi trường `IGNORE_HOSTS`.
   - Đảm bảo biến này được truyền đầy đủ vào container `proxify_app` qua docker-compose.

2. **Nạp `ignore_hosts` vào lõi Mitmproxy (`server.py`)**:
   - Phân giải danh sách domain trong `IGNORE_HOSTS` thành các mẫu Regex an toàn (`re.escape(host)`).
   - Truyền tham số `ignore_hosts=ignore_patterns` vào `mitmproxy.options.Options`: Kích hoạt cơ chế **TCP Passthrough** của Mitmproxy. Bất kỳ kết nối nào hướng tới `trino.sunhouse.com.vn` (cổng 443 hoặc cổng khác) đều được truyền thẳng mức TCP, không giải mã SSL/TLS, không tạo chứng chỉ giả mạo và không làm gián đoạn kết nối của các client nội bộ (Trino CLI, DBeaver, JDBC, Airflow, v.v.).

3. **Bỏ qua trong tầng Application Router & Logger (`router.py` & `server.py`)**:
   - `ProxyRouter`: Thêm thuộc tính `ignored_hosts` và phương thức `is_ignored(host)`. Tự động bỏ qua các domain bị ignore ngay tại `route_request`, `route_responseheaders` và `route_response` mà không tốn tài nguyên tìm kiếm Trie.
   - `V1GlobalObserver`: Không phát tin nhắn WebSocket lên Dashboard và không ghi log vào bảng CSDL `requests` cho các domain trong danh sách bỏ qua.

---

## 2. Mục đích & Ý nghĩa

- **Giải quyết vấn đề người dùng yêu cầu:** *"ignore trino.sunhouse.com.vn trong proxy ra nhé"*.
- **Ý nghĩa kỹ thuật:**
  - `trino.sunhouse.com.vn` là hạ tầng cơ sở dữ liệu / query engine phục vụ trích xuất dữ liệu nội bộ.
  - Khi máy host hoặc tool nội bộ bật Proxy `127.0.0.1:8080`, việc giải mã TLS của Trino có thể gây lỗi chứng chỉ SSL hoặc làm nghẽn bộ nhớ của Proxify do truyền tải các tập dữ liệu lớn (dataset hàng triệu dòng).
  - Thiết lập TCP Passthrough giúp đảm bảo kết nối tới Trino luôn đạt tốc độ tối đa của mạng nội bộ và ổn định 100%.

---

## 3. Mối liên hệ kiến trúc

- **`Options(ignore_hosts)`**: Thuộc tầng Network Driver (Mitmproxy Core).
- **`ProxyRouter` (`router.py`)**: Thuộc tầng Routing & Dispatching (Application Layer).
- **`V1GlobalObserver` (`server.py`)**: Thuộc tầng Persistence & WebSocket Broadcasting (Infrastructure Layer).

---

## 4. Rủi ro (Risks & Edge Cases) và Giải pháp Kiểm soát

1. **Domain sử dụng IP thay vì hostname hoặc sử dụng cổng tùy biến (vd: `trino.sunhouse.com.vn:8443`):**
   - *Giải pháp:* Mitmproxy `ignore_hosts` áp dụng regex so khớp trên cả chuỗi `host:port`. Mẫu `trino\.sunhouse\.com\.vn` sẽ tự động khớp cả khi có cổng đi kèm.
2. **Cần bổ sung thêm domain trong tương lai:**
   - *Giải pháp:* Chỉ cần thêm domain vào biến `IGNORE_HOSTS` trong file `.env` (phân cách bằng dấu phẩy) và chạy `docker compose restart proxify` mà không cần sửa code.
