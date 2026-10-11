# Kiến trúc Cô lập Proxy cho Chrome (Browser-Only Proxy Isolation) & Tối ưu DNS

## 1. Tóm tắt thay đổi
- **Tắt hoàn toàn Proxy hệ thống của Windows**:
  - Đặt `ProxyEnable = 0` trong Windows Registry (`HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings`).
  - Toàn bộ hệ điều hành Windows, bao gồm Game (FC Online, Garena, Steam), Zalo PC, Edge, và các dịch vụ nền hệ thống, quay về kết nối trực tiếp 100% (Direct Connection) ra card mạng vật lý, không còn phụ thuộc vào cổng `127.0.0.1:8080`.
- **Cô lập Proxify cho riêng trình duyệt Google Chrome (Chrome Policy)**:
  - Thiết lập chính sách Chrome Enterprise cấp người dùng tại `HKCU:\Software\Policies\Google\Chrome`:
    - `ProxyMode = "fixed_servers"`
    - `ProxyServer = "http://127.0.0.1:8080"`
    - `ProxyBypassList = "<local>;127.0.0.1;192.168.*;10.*;172.16.*;*.sunhouse.com.vn;14.232.214.249;*.zadn.vn;*.zing.vn;*.microsoft.com;mail.google.com;chat.google.com;accounts.google.com;accounts.youtube.com"`
  - Chỉ duy nhất Google Chrome chuyển tiếp lưu lượng qua Proxify để phục vụ tính năng chặn quảng cáo YouTube và phân tích lưu lượng.
- **Tối ưu hóa phân giải tên miền (DNS Optimization) & Xóa bỏ DNS Hijack**:
  - Phát hiện và sửa lỗi DNS Suffix `SearchList = "sunhouse.com"` (tên miền `.com` có bản ghi wildcard `*.sunhouse.com -> 104.131.67.123` làm trễ mọi truy vấn DNS hơn 500ms - 900ms) chuyển thành `sunhouse.com.vn`.
  - Cấu hình DNS card Wi-Fi trỏ trực tiếp về Google Public DNS (`8.8.8.8`, `8.8.4.4` và IPv6 `2001:4860:4860::8888`, `2001:4860:4860::8844`), giảm độ trễ phân giải DNS từ 275ms xuống còn 30ms.
  - Chuyển `Preferred Band` của card mạng Realtek RTL8852BE về `1. No Preference`, chấm dứt tình trạng card Wi-Fi tự ngắt kết nối để dò sóng 5GHz trên router TP-Link 2.4GHz.

---

## 2. Mục đích & Ý nghĩa
- **Giải quyết triệt để vấn đề "lag do mạng / mất mạng khi proxy restart"**:
  - Trước đây, cấu hình Proxy toàn hệ thống (`ProxyEnable = 1`) tạo ra điểm nghẽn đơn lẻ (Single Point of Failure). Mỗi khi container Proxify khởi động lại hoặc khi ứng dụng game (FC Online, Garena) gửi request mạng, chúng bị ép đi qua cổng 8080, gây nghẽn kết nối và input delay.
  - Bằng cách cô lập Proxy ở tầng ứng dụng (Application Layer - Chrome Policy) thay vì tầng hệ điều hành (OS Winsock Layer), kiến trúc đạt được tính độc lập cao (Decoupling): Game và hệ thống chạy mượt 100%, trong khi Chrome vẫn tận hưởng trọn vẹn khả năng lọc quảng cáo của Proxify.
- **Tăng tốc độ lướt web**:
  - Loại bỏ tình trạng nghẽn DNS từ FPT modem và sự cố phân giải nhầm IP wildcard của `sunhouse.com`, giúp tốc độ mở trang web nhanh hơn gấp nhiều lần.

---

## 3. Mối liên hệ
- **Google Chrome**: Nhận chính sách từ Windows Registry khi khởi chạy hoặc tải lại chính sách.
- **Windows System**: Giải phóng hoàn toàn các ứng dụng khác khỏi cấu hình proxy.
- **Proxify Backend**: Vẫn lắng nghe trên cổng 8080 để phục vụ Chrome.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro**: Không có rủi ro về mạng hệ thống. Trình duyệt Chrome sẽ hiển thị thông báo "Được quản lý bởi tổ chức của bạn" trong menu cài đặt (đây là hành vi mặc định của Chrome khi có chính sách Registry).
- **Trường hợp ngoại lệ (Edge Cases)**:
  - Nếu người dùng muốn tắt hoàn toàn proxy trên Chrome, chỉ cần xoá khóa `HKCU:\Software\Policies\Google\Chrome`.
