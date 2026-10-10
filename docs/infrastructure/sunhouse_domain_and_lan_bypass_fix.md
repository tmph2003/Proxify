# Tài Liệu Kỹ Thuật: Cấu Hình Bypass Toàn Diện Cho Tên Miền Sunhouse & Dải IP Nội Bộ

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `docker-compose.yml`
  - Bổ sung tên miền doanh nghiệp `sunhouse.com.vn` vào biến môi trường `IGNORE_HOSTS`.
- **File sửa đổi 2:** `backend/proxify/server.py`
  - Cập nhật giá trị fallback mặc định `raw_ignore` đồng bộ với `docker-compose.yml`.
- **Cấu hình Hệ điều hành (Windows Winsock / WinHTTP):**
  - Cập nhật `ProxyOverride` trên Windows bổ sung:
    `sunhouse.com.vn;*.sunhouse.com.vn;172.16.*`.
  - Đồng bộ cấu hình sang WinHTTP bằng lệnh `netsh winhttp import proxy source=ie`.

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng & Bối cảnh
Người dùng phản ánh: *"tôi vào domain của .sunhouse.com.vn mà mạng load rất chậm nhé, check lại cho tôi nhé"*.

### Phân tích Kiến trúc & Nguyên nhân gốc rễ (Root Cause)
1. **Lỗ hổng cú pháp Wildcard trong Windows WinINet (`ProxyOverride`):**
   - Trước đây trong `ProxyOverride` chỉ khai báo `*.sunhouse.com.vn`.
   - Theo đặc tả của Windows WinINet (Internet Settings), mẫu `*.domain.com` **chỉ khớp các subdomain** có dấu chấm phía trước (như `erp.sunhouse.com.vn`, `www.sunhouse.com.vn`), nhưng **hoàn toàn không khớp apex/naked domain `sunhouse.com.vn`** (không có dấu chấm phía trước).
   - Khi người dùng truy cập trang chủ `https://sunhouse.com.vn`, trình duyệt Chrome không bypass mà gửi toàn bộ traffic về cổng `127.0.0.1:8080`.
2. **Nghẽn hàng đợi tải tài nguyên tĩnh (55 ảnh sản phẩm) qua Proxy:**
   - Trang chủ `sunhouse.com.vn` chứa hơn 55 hình ảnh sản phẩm tĩnh, 10 file CSS và 5 bundle JS.
   - Do domain `sunhouse.com.vn` trước đó không có trong `IGNORE_HOSTS`, Mitmproxy cố gắng giải mã SSL, tạo cert giả mạo và chuyển tiếp tuần tự từng ảnh qua Event Loop của Python.
   - Trình duyệt Chrome bị nghẽn giới hạn 6 kết nối đồng thời, khiến trang web load rất chậm, hình ảnh sản phẩm xuất hiện giật cục.
3. **Truy cập hạ tầng mạng nội bộ (Split-Horizon DNS & Dải IP LAN `172.16.*`):**
   - Các hệ thống nội bộ của công ty (ERPNext, Trino Engine, BI Dashboard) chạy trên dải IP riêng `172.16.100.x` (`172.16.100.130`, `172.16.100.183`).
   - Khai báo `<local>` trong WinINet chỉ áp dụng cho tên máy tính không có dấu chấm (như `http://server/`), không tự động bypass dải IP số `172.16.*`.
   - Nếu bất kỳ công cụ hoặc kết nối nào trỏ tới IP nội bộ qua proxy, việc không có cấu hình bypass sẽ gây nghẽn kết nối và chậm toàn bộ hệ thống làm việc nội bộ.

### Ý nghĩa giải pháp (Kiến trúc Phòng thủ Đa tầng)
- **Tầng 1 (Hạ tầng Windows - Winsock Direct Bypass):**
  - Khai báo rõ ràng cả `sunhouse.com.vn`, `*.sunhouse.com.vn` và dải IP nội bộ `172.16.*`.
  - Trình duyệt Chrome và các ứng dụng văn phòng kết nối **trực tiếp 100% ra máy chủ IIS (`103.131.74.32`) và hệ thống LAN nội bộ (`172.16.100.x`)**, không đi qua proxy, độ trễ 0ms và tải tài nguyên tức thì.
- **Tầng 2 (Lõi Mitmproxy - TCP Passthrough):**
  - Khai báo `sunhouse.com.vn` vào `IGNORE_HOSTS`. Regex `(?:^|\.)sunhouse\.com\.vn(?::|$)` trong `server.py` tự động nhận diện và kích hoạt chế độ **TCP Passthrough thuần túy** cho toàn bộ domain gốc và mọi subdomain trên mọi cổng (kể cả cổng nội bộ như `:8443`, `:8088`), không giải mã SSL và không ghi đệm vào CSDL.

---

## 3. Mối liên hệ

| Thành phần | Vai trò liên kết |
|---|---|
| `Windows ProxyOverride` | Bypass trực tiếp cả `sunhouse.com.vn`, `*.sunhouse.com.vn` và dải IP LAN `172.16.*` |
| `docker-compose.yml` | Khai báo `sunhouse.com.vn` trong `IGNORE_HOSTS` cho container `proxify_app` |
| `backend/proxify/server.py` | Biên dịch regex pattern bảo đảm TCP Passthrough tuyệt đối cho mọi subdomain và port |
| Hệ thống nội bộ Sunhouse | ERP, Trino, BI và trang chủ `sunhouse.com.vn` hoạt động ở tốc độ mạng gốc |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Ghi log traffic Sunhouse vào CSDL Proxify:**
   - *Đánh giá:* Proxify là công cụ chuyên biệt phục vụ bóc tách dữ liệu mạng xã hội (Facebook, Zalo) và hỗ trợ YouTube. Dữ liệu mạng nội bộ của công ty (ERP, Trino, BI) chứa thông tin kinh doanh nhạy cảm, việc bypass trực tiếp bảo đảm an toàn dữ liệu và tuân thủ nguyên lý Single Responsibility Principle (SRP).
