# Tài liệu: content.py

## 1. Tóm tắt tổng quan
Module cung cấp các hằng số và hàm tiện ích chia sẻ để nhận diện, xử lý các định dạng nội dung (content-type) đi qua hệ thống proxy.

## 2. Mục đích & Ý nghĩa
Dùng để nhanh chóng phân biệt loại nội dung HTTP response có phải là dạng văn bản (text-based: HTML, JSON, XML, GraphQL,...) hay không. Nhờ đó, các interceptor trong Proxify có thể quyết định đọc/parse nội dung một cách an toàn mà không làm treo hệ thống (ví dụ: tránh đọc nhầm file video hoặc file ảnh nhị phân dung lượng lớn).

## 3. Mối liên hệ
Được tái sử dụng rộng rãi bởi các parser, interceptor (như mitmproxy script) và engine cốt lõi trong Proxify khi cần inspect body của HTTP Response.

## 4. Rủi ro (Risks & Edge Cases)
- **Thiếu sót Content-Type:** Tuple `_TEXT_CONTENT_PREFIXES` chứa các danh sách cố định. Nếu một ứng dụng dùng một định dạng content-type dạng text nhưng không chuẩn hoặc không có trong danh sách (VD: `application/x-ndjson`), hệ thống sẽ hiểu nhầm đó là file nhị phân.
- **Sai lệch logic Split:** Cắt chuỗi bằng `split(";")` khá ổn với đa số trường hợp, nhưng đôi khi các Header bị dị dạng khoảng trắng có thể không khớp chính xác.

## 5. Chi tiết các Class và Hàm

- **Hằng số `MAX_RESPONSE_SIZE`**: Đặt giới hạn cứng là `5 * 1024 * 1024` (5MB). Những response nào có dung lượng lớn hơn mốc này sẽ không được hệ thống Proxify tải vào RAM để lưu trữ hoặc can thiệp, tránh rủi ro Out-of-Memory (OOM).
- **Hằng số `_TEXT_CONTENT_PREFIXES`**: Một Tuple chứa các tiền tố (prefixes) phổ biến của các loại MIME text (ví dụ: `text/`, `application/json`, `application/xml`, `application/graphql`,...). Được lưu bằng kiểu Tuple để tận dụng hiệu năng của hàm `startswith` dựng sẵn trong Python.
- **Hàm `is_text_content(content_type: str) -> bool`**: 
  - Nhiệm vụ: Kiểm tra một chuỗi `Content-Type` được gửi từ HTTP Header có thuộc về kiểu text-based hay không.
  - Logic: Tách phần MIME type cốt lõi (bỏ qua charset), xóa khoảng trắng, sau đó dùng `startswith` so khớp với tuple `_TEXT_CONTENT_PREFIXES`. Trả về `True` nếu khớp và `False` nếu không. Trả về `False` nếu đầu vào rỗng.
