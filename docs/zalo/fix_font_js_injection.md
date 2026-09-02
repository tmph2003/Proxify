# Cập nhật: Sửa lỗi font chữ Zalo Web do JS Injection

## Tóm tắt thay đổi
- Sửa lỗi trong hàm `inject_hooks` của file `backend/proxify/platforms/zalo/extractor.py`.
- Thêm dấu chấm phẩy (`;`) trước khi nối thêm chuỗi nội dung của `JSON_PARSE_HOOK` và `CRYPTO_SUBTLE_HOOK` vào cuối file JS gốc.

- **Cập nhật thêm:** Sửa đổi logic để thực hiện nối chuỗi trên raw `bytes` thay vì giải mã/mã hóa qua `flow.response.text`.
- Xóa bỏ việc tự động thêm header `charset=utf-8` vào `Content-Type`. Thay vào đó, gọi `flow.response.decode()` để giải nén gzip/brotli, giữ nguyên chuẩn mã hóa gốc mà server Zalo trả về, và chỉ thao tác cộng chuỗi (append) ở dạng byte `b";\n" + HOOK.encode('utf-8')`.

## Mục đích & Ý nghĩa
- **Vấn đề:** Khi mở trang `chat.zalo.me`, font chữ bị lỗi hiển thị các ký tự lạ (VD: "ChÃ o má»«ng") và giao diện bị vỡ.
- **Nguyên nhân:** Có 2 nguyên nhân:
  1. Ban đầu, việc thiếu dấu chấm phẩy (;) khi tiêm script (IIFE) gây lỗi `TypeError: ... is not a function`, làm Zalo không tải được file font.
  2. Sau đó, khi dùng `flow.response.text`, MITMProxy tự động encode lại chuỗi sang byte dựa vào charset trong `Content-Type`. Nếu server Zalo trả về JS không có tham số charset, trình duyệt hoặc proxy có thể bị nhầm lẫn và ép kiểu utf-8 vào thành ISO-8859-1 (Mojibake).
- **Cách khắc phục:** 
  1. Nối chuỗi `\n;\n` trước các file hook.
  2. Xử lý trực tiếp trên mảng byte (`flow.response.content`) sau khi giải nén, không sử dụng string encode/decode mặc định của MITMProxy. Điều này đảm bảo nội dung JS giữ nguyên 100% định dạng mã hóa (UTF-8 nguyên thủy của Zalo) không bị thay đổi.

## Mối liên hệ
- Ảnh hưởng trực tiếp tới cơ chế can thiệp JS (`modify_response`) của MITM Proxy cho Zalo.
- Sửa chữa lỗi hiển thị trên trang Zalo Web của bot / người dùng.

## Rủi ro (Risks & Edge Cases)
- Các lỗi tương tự liên quan đến JS injection có thể vẫn tiềm ẩn nếu Zalo nén code JS bằng các chuẩn khác không tương thích hoặc có nội dung mã hóa non-UTF8. Tuy nhiên, việc bọc thêm dấu `;` đã là practice chuẩn mực nhất để chèn IIFE an toàn.
