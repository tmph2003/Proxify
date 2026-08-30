# Tài liệu: Sửa lỗi injection JS hook Zalo (Lỗi nén GZIP)

## Tóm tắt thay đổi
- Chỉnh sửa hàm `modify_zalo_response` trong `proxify/platforms/zalo/extractor.py`.
- Thay thế đoạn code đọc nội dung thô `flow.response.content.decode("utf-8")` thành thuộc tính được quản lý tự động `flow.response.text` của mitmproxy.

## Mục đích & Ý nghĩa
- Web của Zalo (và hầu hết các web hiện đại) trả về file `.js` ở dạng đã nén (gzip hoặc brotli) để tối ưu băng thông. Thuộc tính `flow.response.content` của mitmproxy trả về byte RAW nguyên bản (đang bị nén).
- Việc cố gắng gọi hàm `decode("utf-8")` lên một chuỗi byte bị nén sẽ gây ra lỗi `UnicodeDecodeError` hoặc sinh ra một đống ký tự rác (nếu rớt vào fallback `latin-1`). 
- Vì body là rác, logic tìm kiếm chuỗi để chèn hook JS sẽ thất bại hoàn toàn. Kết quả là hàm trả về `None`, Zalo Web load JS gốc, không hề có JS Hook nào được cài vào. Bot Playwright sẽ đợi mòn mỏi và báo lỗi "JS hooks chưa inject".
- Sử dụng `flow.response.text` giúp mitmproxy tự động giải nén (decompress) theo `Content-Encoding`, cho ta chuỗi JS sạch để thao tác, sau đó tự động nén lại khi gán giá trị mới.

## Mối liên hệ
- Liên kết với Zalo Bot (`bot.py`), đặc biệt là thông báo lỗi *"JS hooks chưa inject — đang reload trang..."*.
- Đảm bảo JS Hook `window.__proxify_fetchFullGroupInfo` hoạt động như thiết kế.

## Rủi ro (Risks & Edge Cases)
- `flow.response.text` có thể tốn thêm một chút CPU để giải nén/nén, nhưng đối với các file JS kích thước vài MB thì thời gian xử lý là không đáng kể so với I/O mạng. Code đã trở nên an toàn hơn nhiều.
