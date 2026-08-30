# Tài liệu: `proxify/platforms/zalo/extractor.py`

## 1. Tóm tắt tổng quan
File `extractor.py` là trung tâm trích xuất và giải mã dữ liệu của nền tảng Zalo. Cơ chế hoạt động của nó dựa trên MITM Proxy (Proxy trung gian). Nó tiêm (inject) mã Javascript giả mạo vào thẳng các file mã nguồn Web của Zalo để móc nối (hook) vào các hàm `crypto.subtle` (giải mã E2EE) hoặc `JSON.parse`. Dữ liệu sau khi giải mã sẽ được gửi lén về Proxy qua đường dẫn `/api/capture_dump`, tại đây Proxy sẽ tự động phân loại, đọc và lưu thẳng vào CSDL PostgreSQL (users, groups, messages).

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Bắt, trích xuất và phân tích cú pháp gói dữ liệu mã hóa khép kín (End-to-End Encryption) mà Zalo sử dụng ở phía Frontend (Trình duyệt Web).
- **Ý nghĩa**: Zalo Web sử dụng cơ chế bảo mật tinh vi (mã hóa luồng dữ liệu AES). Bằng cách chặn trực tiếp dữ liệu tại thời điểm nó bị giải mã thành văn bản rõ (plaintext) trong nhân Javascript, hệ thống có thể bóc tách được toàn bộ dữ liệu thành viên, tin nhắn mà không cần phải can thiệp phá vỡ khóa (crypto-breaking).

## 3. Mối liên hệ
- Nó là một Add-on/Module chặn (Interceptor) được đính kèm vào luồng đi của MITM proxy (`ZaloHookBlocker` trong proxify proxy core).
- Có 2 hàm `handle_capture_dump` và `modify_zalo_response` được hook trực tiếp vào Request và Response flow của HTTP(s).
- Gọi trực tiếp module CSDL Zalo `from proxify.platforms.zalo import zalo_db` để upsert bản ghi.
- Hỗ trợ chạy thủ công (CLI script) để bóc tách tệp `.bin` cũ trong thư mục `dumps/`.

## 4. Rủi ro (Risks & Edge Cases)
- **Treo Proxy do I/O nặng**: Hàm `handle_capture_dump` xử lý ngay trên thread chính của Proxy. Nếu dữ liệu JSON Zalo lên tới 50MB (với các nhóm vạn thành viên), việc Parse JSON rồi chạy loop lưu vào PostgreSQL sẽ làm treo toàn bộ luồng mạng đi qua Proxy vài giây đến hàng chục giây.
- **Rủi ro mã Javascript (JS Fingerprint/Change)**: Nếu Zalo cập nhật mã JS Webpack (ví dụ: đổi tên thuộc tính, đổi logic mã hóa WASM Trusted-Device-Bridge), đoạn Regex tìm và thay thế của file này sẽ thất bại hoàn toàn. Crawler sẽ không móc được dữ liệu.
- **Xung đột bộ nhớ**: Cache chống trùng (`_seen_hashes`) nếu phình to có thể chiếm RAM proxy, tuy nhiên code đã giới hạn 500 hashes để xóa bớt.

## 5. Chi tiết các Class và Hàm

### 1. Biến & Các hàm tải file Hook (Global)
- `load_js_hook`: Tải file mã JavaScript thô từ thư mục `js/` (chứa 2 file `crypto_subtle.js` và `json_parse.js`).
- `WASM_HOOKS`: Một biến `dict` cung cấp mã thay thế để hook vào luồng giải mã WASM (WebAssembly) của Zalo.

### 2. Hàm `inject_hooks(url: str, body: str) -> Optional[str]`
- **Mô tả**: Chèn các đoạn JS Hooks vào phần nội dung trả về của Zalo.
- **Cách hoạt động**:
  - Nếu file tên là `trusted-device-bridge`, thay thế mã WASM bằng các lệnh `console.log` và giải mã.
  - Nếu là file `.js` thường của Zalo, nó nối đoạn hook `crypto.subtle.decrypt` và hook `JSON.parse` vào cuối file JS.

### 3. Hàm `handle_capture_dump(flow: http.HTTPFlow) -> bool`
- **Mô tả**: Lắng nghe mọi request đi qua Proxy. Nếu request POST vào đường dẫn giả `/api/capture_dump`, nó tiến hành chụp dữ liệu.
- **Cách hoạt động**:
  - Dùng thuật toán băm (MD5) kiểm tra trùng lặp qua `_seen_hashes` cache.
  - Gọi class `ZaloExtractor` để giải mã tệp bytes (GZIP, Text,...).
  - Phân loại 2 nhánh:
    - Nếu là `userProfiles` (từ API riêng fetchProfiles), vòng lặp bóc trần từng User ID (`uid`, `globalId`, `displayName`, `avatar`, `phone`) rồi lưu vào DB `zalo_db.users`.
    - Nếu là dữ liệu nhóm (Group), chạy hàm `ext.get_groups()`. Lặp qua từng Group Upsert DB. Lặp qua các ID thành viên và gọi `link_members`.
  - Cuối cùng, trả về HTTP status 200 `b"ok"` cho Javascript frontend (trình duyệt) để nó không bị lỗi ném ngoại lệ (Exception).

### 4. Hàm `modify_zalo_response(flow: http.HTTPFlow) -> None`
- **Mô tả**: Được Proxy gọi mỗi khi có Response HTTP đổ về máy khách (Browser). 
- **Cách hoạt động**: Lọc xem URL có chứa Zalo JS không. Nếu đúng, giải mã (decode latin-1 hoặc utf-8), gọi `inject_hooks` sửa đổi body rồi ghi lại (encode utf-8) nhồi vào Response, kèm theo Header Content-Type `charset=utf-8` để chống lỗi phông chữ.

### 5. `ZaloExtractor` (Class)
- **Mô tả**: Trình hỗ trợ bóc tách, có thể đọc trực tiếp từ thư mục chứa các tệp nhị phân (`dumps/*.bin`) khi chạy dưới dạng CLI hoặc đọc trực tiếp từ Memory (từ luồng Proxy).
- **Các hàm**:
  - `_iter_payloads`: Trả về các file hợp lệ hoặc payload memory.
  - `_decode`: Xác định định dạng tệp thô (Nếu là `1f 8b` thì dùng Gzip, nếu có nhãn `[JSON.parse]` thì cắt nhãn, sau đó parse từ chuỗi JSON thành Dict Python).
  - `_normalize_group_id` / `_pick_group_id`: Các hàm tiện ích giúp bóc tách đúng chuẩn `group_id` trong mớ JSON hỗn độn (VD: loại bỏ tiền tố `g`).
  - `get_messages`, `get_users`, `get_reactions`, `get_groups`: Quét sâu (deep-scan) qua tất cả các lớp của các đoạn JSON lồng nhau, nhận dạng và bóc tách chuẩn chỉnh các mô hình Đối tượng (Group, User, Text). Hàm này sử dụng hàng loạt câu `if-else` khổng lồ và phức tạp với mọi tên field (từ khóa) có thể có do Zalo thay đổi liên tục (`memberList`, `memVerList`, `dName`, `zName`,...).
  - `summary`, `export_groups_json`: Trả về thống kê hoặc kết xuất (Export) dữ liệu ra tệp JSON nếu dùng qua Command Line Interface (Script).
