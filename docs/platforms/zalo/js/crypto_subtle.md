# Tài liệu: `crypto_subtle.js` (Thư mục platforms/zalo/js)

## 1. Tóm tắt tổng quan
File `crypto_subtle.js` là một đoạn script tiêm (inject) vào môi trường trình duyệt (trang web Zalo Chat). Nó thực hiện việc ghi đè (hook) API mã hóa gốc của trình duyệt là `window.crypto.subtle.decrypt` nhằm bắt, giải mã, và thu thập các gói dữ liệu End-to-End Encryption (E2EE) của Zalo ngay trên client.

## 2. Mục đích & Ý nghĩa
- **Mục đích:** Xuyên thủng lớp mã hóa của Zalo Web mà không cần phải nắm giữ trực tiếp private key phức tạp tại proxy server. Toàn bộ payload được giải mã tại client (trình duyệt) thông qua API chuẩn, sau đó script này sẽ đánh cắp dữ liệu rõ (plaintext) trả về.
- **Ý nghĩa:** Cung cấp giải pháp để hệ thống proxy bắt được danh sách thành viên hoặc thông tin nhóm vốn bị mã hóa theo luồng bảo mật cao của Zalo, từ đó đẩy về cơ sở dữ liệu phân tích.

## 3. Mối liên hệ
- Hoạt động phối hợp với các plugin của Proxify: File script này được plugin `zalo.py` tải lên trình duyệt của người dùng (có thể thông qua mitmproxy response injection hoặc Playwright/Selenium).
- Liên kết với API nội bộ của máy chủ proxy thông qua một endpoint bắt dữ liệu được giả mạo trên miền của Zalo: `https://chat.zalo.me/api/capture_dump`.

## 4. Rủi ro (Risks & Edge Cases)
- **Rủi ro Bảo mật/Lộ lọt:** Script lấy trộm dữ liệu trên luồng trình duyệt rồi gửi qua API POST không bảo mật xác thực nội bộ. 
- **Lỗi hiển thị / Crash trình duyệt:** Thao tác hook một hàm lõi của trình duyệt (WebCrypto API) có thể gây xung đột nếu có sự bất đồng bộ hoặc lỗi parse `DecompressionStream`. Nếu hook sinh ra Exception không được bọc kỹ, nó có thể phá vỡ luồng tải tin nhắn của Zalo.
- **Theo vết (Fingerprinting):** Zalo hoàn toàn có khả năng viết mã kiểm tra xem hàm `decrypt` có phải là native code không (thông qua `toString().includes("[native code]")`), và khóa tính năng nếu phát hiện bị hook.

## 5. Chi tiết các Class và Hàm
- **`IIFE (Immediately Invoked Function Expression)`**: Khởi tạo bằng `(function(){ ... })()` để tạo không gian biến cục bộ. Sử dụng cờ `g.__zalo_crypto_hooked` để đảm bảo không bị hook trùng lặp khi script bị tiêm nhiều lần.
- **`g.crypto.subtle.decrypt (Ghi đè)`**: 
  - **Chức năng:** Thay thế hàm giải mã gốc của trình duyệt. 
  - **Luồng xử lý:** 
    1. Đợi hàm giải mã gốc `_orig.apply(this, arguments)` thực thi và lấy `ArrayBuffer` đã giải mã thô.
    2. **Giải nén:** Payload của Zalo thường bị nén. Hàm sẽ thử nghiệm `DecompressionStream` với thuật toán `deflate-raw` hoặc `deflate` để bung file.
    3. **Chuyển đổi văn bản:** Parse mảng byte thành chuỗi văn bản UTF-8 bằng `TextDecoder`.
    4. **Kiểm tra luồng đích (Target Filter):** Lấy `currentGroupId` từ biến môi trường `window.__zalo_groupRuntime` hoặc đọc trực tiếp từ chuỗi URL hiện tại để bỏ qua các tin nhắn nền không thuộc về nhóm đang xem.
    5. **Lọc từ khoá (Keyword Filtering):** Chặn (intercept) các luồng có chứa từ khóa chuyên biệt của nhóm như `"memberIds"`, `"memberList"`, `"topMember"` và gửi nội dung qua lệnh `fetch` (POST) đến endpoint `capture_dump`. 
    6. Trả lại kết quả gốc `res` để trình duyệt và ứng dụng Zalo tiếp tục hoạt động mà không nhận ra sự can thiệp.
