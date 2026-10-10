# Tài liệu Kỹ thuật: Khắc Phục Nghẽn Mạng Do Bão Telemetry YouTube Live & Mở Rộng Shared Memory PostgreSQL

## 1. Tóm tắt thay đổi
- **Bộ lọc Triệt tiêu Nhiễu Telemetry & Polling ([backend/proxify/server.py](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/backend/proxify/server.py)):**
  - Bổ sung logic chặn tại `V1GlobalObserver.handle_response`: Ngăn chặn tuyệt đối việc lưu trữ vào CSDL (`requests`) và phát tán qua WebSocket (`broadcaster`) đối với các endpoint thăm dò tần suất cao của YouTube Live và Google:
    - `/api/stats/` (QOE, watchtime, atr, playback)
    - `/youtubei/v1/live_chat/` (polling tin nhắn chat luồng live mỗi 1-2s)
    - `/youtubei/v1/updated_metadata` (nạp metadata live stream kích thước ~1MB mỗi vài giây)
    - `/youtubei/v1/log_event`, `/punctual/`, `/generate_204`, `/ptracking`
  - Cập nhật danh sách mặc định `IGNORE_HOSTS` bao gồm các dịch vụ phụ trợ: `signaler-pa.youtube.com`, `googleapis.com`, `nel.goog`, `withgoogle.com`, `adtrafficquality.google`.
- **Hạ tầng Docker & CSDL ([docker-compose.yml](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/docker-compose.yml)):**
  - Mở rộng biến môi trường `IGNORE_HOSTS` của `proxify` tương ứng.
  - Cấu hình `shm_size: 512mb` cho container `proxify_db` (mặc định của Docker là 64MB, gây lỗi `could not resize shared memory segment: No space left on device` khi PostgreSQL thực thi VACUUM và sắp xếp chỉ mục GIN full-text).
- **Hệ điều hành Windows (WinINet & WinHTTP):**
  - Đồng bộ danh sách bypass mới vào `ProxyOverride`: `signaler-pa.youtube.com;*.googleapis.com;googleapis.com;*.nel.goog;*.withgoogle.com;*.adtrafficquality.google`.
  - Gọi Win32 API `InternetSetOption` làm mới tức thì.
- **Tối ưu hóa dữ liệu:**
  - Dọn dẹp hơn 49.000 dòng log rác telemetry tích tụ trong bảng `requests` và thực hiện `VACUUM ANALYZE` thành công.

---

## 2. Mục đích & Ý nghĩa
- **Hiện tượng:** Người dùng phản ánh mạng "lại bị chậm rồi" sau khi xem YouTube một lúc.
- **Nguyên nhân gốc rễ (Root Cause):**
  1. **Bão Telemetry từ YouTube Live Stream:** Khi người dùng xem một luồng trực tiếp (Live Stream), Chrome gửi liên tục 2–10 request/giây bao gồm thăm dò kênh multi-watch (`signaler-pa.youtube.com` - hơn 60 req/phút), lấy tin nhắn live chat (`get_live_chat` - ~30 req/phút), và metadata (`updated_metadata` - payload 1MB JSON).
  2. **Nghẽn Cổ Chai Event Loop & Disk I/O:** 
     - Toàn bộ lượng traffic này đều bị Mitmproxy giải mã TLS, sau đó đưa vào hàm insert của PostgreSQL.
     - Tại PostgreSQL, trigger `tsvectorupdate` buộc phải băm từ điển, tính toán lexemes và cập nhật chỉ mục GIN cho các file JSON 1MB liên tục.
     - Container DB ghi nhận hơn 19GB Block I/O và chiếm 1.67GB RAM, làm bão hòa hàng đợi event loop đơn luồng của Python (CPU vọt lên 17-25%). Bất kỳ request duyệt web mới nào của người dùng đều phải xếp hàng chờ sau hàng chục gói tin telemetry, gây cảm giác mạng bị giật/lag nghiêm trọng.
  3. **Lỗi Docker Shared Memory (/dev/shm):** Docker giới hạn `/dev/shm` ở 64MB. Khi chỉ mục GIN phình to, PostgreSQL không thể phân bổ bộ nhớ dùng chung, gây crash truy vấn VACUUM.
- **Ý nghĩa giải pháp:** Loại bỏ 95% lưu lượng rác không cần thiết, giải phóng hoàn toàn Event Loop của Mitmproxy (CPU app giảm từ 17% xuống dưới 1%), đưa tốc độ phản hồi mạng trở lại thời gian thực.

---

## 3. Mối liên hệ
- **`backend/proxify/server.py`:** Bảo vệ tầng Application Logic và Database khỏi hiện tượng DDoS nội bộ từ các luồng streaming.
- **`docker-compose.yml`:** Tăng giới hạn tài nguyên nhân phần cứng cho PostgreSQL.
- **`ProxyOverride` Windows:** Giảm tải ngay từ nguồn phát Chrome tại tầng Winsock.

---

## 4. Rủi ro (Risks & Edge Cases)
- **Truy vết lỗi YouTube Live:** Nếu trong tương lai cần debug tính năng chat của YouTube, các request này sẽ không có sẵn trong bảng `requests` vì đã bị lọc bỏ chủ động. Điều này hoàn toàn có thể bật lại nếu chuyển sang chế độ debug có chủ đích.
