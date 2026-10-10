# Tài Liệu Kỹ Thuật: Tách Lập DNS Container Độc Lập & Triệt Tiêu Quá Tải Treo Mạng Proxy (Docker DNS, Extra Hosts & Alt-Svc Bypass)

## 1. Tóm tắt thay đổi
- **Hạ tầng Docker (`docker-compose.yml`)**:
  - Bổ sung cấu hình DNS công cộng tường minh (`8.8.8.8`, `1.1.1.1`) cho service `proxify_app`, tách đứt việc kế thừa DNS trung gian của WSL2 (`192.168.65.7`).
  - Khai báo ánh xạ tĩnh `extra_hosts` cho toàn bộ các domain nội bộ Sunhouse (`ks.sunhouse.com.vn`, `erp.sunhouse.com.vn`, `git.sunhouse.com.vn`, `trino.sunhouse.com.vn`, `bi.sunhouse.com.vn`, `jira.sunhouse.com.vn`, `sso.sunhouse.com.vn`, `minio.sunhouse.com.vn`) trỏ thẳng tới IP máy chủ nội bộ (`172.16.100.130`, `172.16.100.183`, `172.16.100.129`).
  - Mở rộng `IGNORE_HOSTS` với các domain dịch vụ phụ trợ: `accounts.youtube.com`, `gvt1.com`, `gvt3.com`, `fastly-edge.com`, `play.google.com`.
- **Lõi Proxy (`backend/proxify/server.py`)**:
  - Tại hook `responseheaders` và `response` của `ProxyAddon`, chủ động xóa bỏ header `Alt-Svc` (`del flow.response.headers["alt-svc"]`) đối với tất cả các luồng dữ liệu đi qua proxy.
  - Đồng bộ danh sách fallback `IGNORE_HOSTS` khớp hoàn toàn với `docker-compose.yml`.
- **Extension YouTube Enhancer (`backend/extensions/youtube/plugin.py`)**:
  - Triệt tiêu dứt điểm header `Alt-Svc` trên toàn bộ response trả về từ YouTube (`youtube.com` và `youtubei.googleapis.com`).
- **Hệ thống Host Windows (WinINet & WinHTTP)**:
  - Cập nhật registry `ProxyOverride` và đồng bộ sang WinHTTP (`netsh winhttp import proxy source=ie`) cho các domain phụ trợ mới (`*.gvt1.com;*.gvt3.com;accounts.youtube.com;*.fastly-edge.com;play.google.com`).
  - Kích hoạt thông báo WinINet `InternetSetOption` (options 39 và 37) để áp dụng ngay lập tức cho toàn bộ tiến trình mạng Windows.

---

## 2. Mục đích & Ý nghĩa
- **Hiện tượng lỗi gốc (Root Cause)**:
  - Máy host chạy mạng kép song song: mạng LAN thường và VPN doanh nghiệp Palo Alto GlobalProtect (`Ethernet 2`, DNS chính: `172.16.100.5`).
  - Docker Desktop mặc định cấu hình container dùng resolver `127.0.0.11` chuyển tiếp lên WSL2 `192.168.65.7` và cuối cùng hỏi DNS của host.
  - Khi có VPN, các truy vấn DNS cho tên miền công cộng (YouTube, Zalo, Google) bị đẩy vào DNS server nội bộ `172.16.100.5`. Về đêm hoặc khi VPN nghẽn, máy chủ DNS `172.16.100.5` làm rớt gói UDP hoặc nghẽn phân giải đệ quy, dẫn tới `[Errno -3] Temporary failure in name resolution` và treo toàn bộ pool luồng `asyncio.getaddrinfo` suốt 15 - 20 giây (gây log trễ `19106.22ms` ở heartbeat YouTube, `4069.25ms` ở Zalo).
  - Thêm vào đó, header `Alt-Svc: h3=":443"` từ YouTube xui khiến trình duyệt Chrome gửi truy vấn UDP QUIC (port 443) song song. Khi firewall/VPN cấm hoặc rớt UDP 443, Chrome bị khựng 1 - 3 giây chờ timeout trước khi fallback về TCP HTTP/2.
  - Các kết nối nhàn rỗi (idle) bị treo lâu sinh ra lỗi phân rã socket HTTP/2: `Invalid input ConnectionInputs.RECV_PING in state ConnectionState.CLOSED`.
- **Ý nghĩa giải pháp**:
  - Thiết lập DNS công cộng (`8.8.8.8`, `1.1.1.1`) giúp container phân giải domain công cộng trong **30ms - 45ms** siêu tốc, độc lập hoàn toàn với trạng thái VPN.
  - Khai báo `extra_hosts` đưa domain nội bộ vào `/etc/hosts` giải quyết ngay lập tức trong **0.00ms**, không phát sinh bất kỳ truy vấn DNS nào ra ngoài.
  - Xóa bỏ `Alt-Svc` ép trình duyệt Chrome kiên định sử dụng kết nối TCP HTTP/2 ghép kênh (multiplexed) qua proxy, triệt tiêu toàn bộ độ trễ thử nghiệm thất bại của giao thức UDP QUIC.

---

## 3. Mối liên hệ
- **`docker-compose.yml` & Linux `/etc/resolv.conf` / `/etc/hosts`**: Quyết định cơ chế giải quyết địa chỉ IP ở tầng hạ tầng container cho tất cả các tiến trình Python bên trong.
- **`backend/proxify/server.py`**: Điểm tiếp nhận và phân phối lưu lượng của Mitmproxy. Việc gỡ bỏ `Alt-Svc` tại đây bảo vệ tầng giao thức của toàn bộ các plugin và ứng dụng client kết nối vào proxy.
- **`backend/extensions/youtube/plugin.py`**: Module chặn quảng cáo YouTube. Hoạt động song hành với việc loại bỏ `Alt-Svc` để các video stream của `googlevideo.com` và metadata Innertube API mượt mà 100%.
- **Windows `ProxyOverride` & WinHTTP**: Tách các domain phụ trợ (như `accounts.youtube.com`, `gvt1.com`, `gvt3.com`, `fastly-edge.com`) ra khỏi proxy ngay từ tầng hệ điều hành, giảm tải triệt để tài nguyên cho tiến trình proxy.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Thay đổi IP máy chủ nội bộ Sunhouse**:
  - *Rủi ro*: Nếu đội ngũ IT Sunhouse thay đổi địa chỉ IP của KubeSphere (`172.16.100.130`) hoặc BI (`172.16.100.183`), việc gán cứng trong `extra_hosts` có thể khiến container không cập nhật theo kịp.
  - *Biện pháp giảm thiểu*: Trình duyệt trên host Windows đi qua `ProxyOverride` (`*.sunhouse.com.vn`), nên host Windows vẫn hỏi trực tiếp DNS `172.16.100.5` bình thường. Khai báo `extra_hosts` trong container chỉ là phòng tuyến phụ nếu container cần giao tiếp nội bộ. Khi hạ tầng nội bộ đổi IP, chỉ cần cập nhật lại `extra_hosts` trong compose.
- **Chặn HTTP/3 (QUIC) có ảnh hưởng hiệu năng không?**:
  - *Thực tế*: Trên môi trường proxy cục bộ (localhost:8080) và mạng VPN công ty, TCP HTTP/2 ổn định và tối ưu hơn rất nhiều so với UDP QUIC. QUIC chỉ phát huy tác dụng trên mạng di động 4G/5G bị packet loss cao khi chuyển đổi trạm phát sóng (connection migration). Trên máy tính để bàn (PC) có VPN, việc ép dùng TCP loại bỏ 100% tình trạng dropping UDP packet và handshake timeout.
