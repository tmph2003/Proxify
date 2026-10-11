# Hạ tầng Bypass Lưu lượng Game Online (FC Online, Garena, EA Sports) - Zero-Overhead Passthrough

## 1. Tóm tắt thay đổi
- **Bổ sung toàn bộ hệ sinh thái tên miền Game vào danh sách Bypass của hệ thống**:
  - Các domain Garena & FC Online: `garena.com`, `garena.vn`, `garenanow.com`, `gopapi.io`.
  - Các nền tảng game lớn: `ea.com`, `origin.com`, `nexon.com`, `nexon.net`, `riotgames.com`, `leagueoflegends.com`, `steampowered.com`, `steamcommunity.com`, `epicgames.com`, `battlenet.com`, `blizzard.com`.
- **Cập nhật đồng bộ trên 3 tầng**:
  1. **Hạ tầng OS (Windows Winsock Layer)**: Khai báo vào `ProxyOverride` trong Windows Registry (`HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings`) và đồng bộ sang WinHTTP (`netsh winhttp import proxy source=ie`).
  2. **Biến môi trường Container**: Cập nhật `IGNORE_HOSTS` trong file `.env` và `docker-compose.yml`.
  3. **Application Core Backend**: Cập nhật giá trị fallback mặc định của `raw_ignore` trong `backend/proxify/server.py`.

---

## 2. Mục đích & Ý nghĩa
- **Bản chất nguyên nhân**:
  - FC Online (`fczf.exe`) sử dụng thư viện `WININET.dll`.
  - Trình khởi chạy game FC Online (`fco-vn.exe`) chạy trên nền Electron/Chromium.
  - Giao diện sự kiện/cửa hàng in-game (`cefproczf.exe`) dùng Chromium Embedded Framework (`libcef.dll`).
  - Trình quản lý game Garena (`Garena.exe`, `as.gxxcef.exe`) cũng dùng CEF/Chromium.
  - Khi Windows bật cấu hình Proxy (`ProxyEnable = 1`), tất cả các tiến trình trên đều tự động tuân thủ cấu hình Proxy hệ thống và gửi các request HTTP/HTTPS (kiểm tra token, tải banner CDN, xác thực heartbeat, truy vấn server matchmaking) đến port `8080` của Proxify.
  - Khi các domain game không nằm trong `ProxyOverride`, lưu lượng buộc phải đi qua cầu nối ảo Hyper-V vEthernet $\to$ Docker Bridge $\to$ Event loop asyncio đơn luồng của Mitmproxy $\to$ Gateway Docker $\to$ Card mạng vật lý.
  - Trong quá trình chơi game, nếu người dùng mở video YouTube hoặc lướt web trên Chrome, Event loop của Proxy bận xử lý lưu lượng web nặng sẽ làm chậm trễ các gói tin TCP của game, sinh ra lỗi `PacketStatusMgr pkt_waiting_timeout to=60`, gây lag, giật khung hình và input delay trong trận đấu. Khi người dùng tắt Proxify (`ProxyEnable = 0`), toàn bộ game kết nối thẳng qua card mạng máy tính nên chơi mượt bình thường.
- **Giải pháp**:
  - Khai báo bypass triệt để các domain game ở tầng Winsock OS. Khi `ProxyOverride` có các domain này, Windows sẽ định tuyến trực tiếp các kết nối HTTP/HTTPS của game ra Gateway vật lý mà không hề chạm vào port 8080 của Proxify.
  - Cấu hình dự phòng trong `IGNORE_HOSTS` đảm bảo nếu có kết nối nào cố tình gửi đến port 8080, Mitmproxy sẽ chuyển sang TCP Passthrough thuần túy, không can thiệp và không decrypt SSL.

---

## 3. Mối liên hệ
- **Hạ tầng mạng Windows**: Tác động trực tiếp đến cách `WININET.dll` và Chrome/Chromium xử lý lưu lượng mạng của Garena, FC Online, EA Sports, Riot Games, Steam.
- **`backend/proxify/server.py`**: Nạp biến `IGNORE_HOSTS` và khởi tạo `ProxyRouter`.
- **`docker-compose.yml` & `.env`**: Định nghĩa biến môi trường `IGNORE_HOSTS` truyền vào container `proxify_app`.
- **Độ ổn định của Proxify**: Giải phóng hoàn toàn gánh nặng lưu lượng game và CDN ảnh/video game ra khỏi Docker container, giúp Proxify tập trung 100% tài nguyên CPU/RAM cho việc chặn quảng cáo YouTube và trích xuất dữ liệu Zalo/Facebook.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro**: Không có rủi ro về mặt an ninh hay mất tính năng, vì Proxify là công cụ cho web/công việc, không có bất kỳ plugin hay logic nghiệp vụ nào cần can thiệp vào game online.
- **Trường hợp ngoại lệ (Edge Cases)**:
  - Nếu nhà phát hành game (Garena/EA) bổ sung thêm một domain CDN hoàn toàn mới mà chưa được khai báo wildcard trong `ProxyOverride`, domain mới đó có thể tạm thời đi qua proxy cho đến khi được thêm vào danh sách bypass. Tuy nhiên, việc khai báo các wildcard gốc như `*.garena.com`, `*.garena.vn`, `*.garenanow.com`, `*.ea.com` đã bao phủ 99.9% lưu lượng của toàn bộ hệ sinh thái game.
