# Tài liệu: `exporter.py`

## 1. Tóm tắt tổng quan
File `exporter.py` là một mô-đun tiện ích (utility) độc lập cung cấp các hàm xuất dữ liệu. Nó chuyển đổi các bản ghi HTTP request/response thô từ hệ thống thành nhiều định dạng chuẩn khác nhau bao gồm JSON, HAR, đoạn mã nguồn Python (`requests`), và chuỗi lệnh cURL.

## 2. Mục đích & Ý nghĩa
- Giúp người dùng xuất các yêu cầu đã bắt (captured requests) để sao lưu, chia sẻ, phân tích bằng các công cụ bên ngoài (ví dụ: import file HAR vào Chrome DevTools hoặc Postman).
- Cho phép tái sử dụng cấu hình yêu cầu một cách nhanh chóng dưới dạng mã Python hoặc lệnh cURL để tự động hóa hoặc thực hiện các script khai thác/quét kiểm tra, loại bỏ việc phải copy từng header/cookie thủ công.

## 3. Mối liên hệ
- Được gọi chủ yếu bởi `proxify.dashboard.Dashboard` thông qua API router `/api/export/{format}`.
- Có khả năng xử lý cấu trúc dữ liệu trả về từ hệ thống `proxify.storage.RequestStorage` để định dạng lại và xuất ra đúng cú pháp chuẩn.

## 4. Rủi ro (Risks & Edge Cases)
- **Tải lượng lớn (Out of Memory):** Khi người dùng muốn xuất hàng ngàn request cùng lúc, việc nối chuỗi (string concatenation) hoặc serialize lượng lớn object JSON vào bộ nhớ (RAM) trước khi trả về web response có thể làm quá tải server (OOM crash). Lý tưởng nhất là dùng dạng stream.
- **Lỗi ký tự Escape:** Hàm chuyển đổi sang cURL (`export_to_curl`) phải xử lý việc escaping các ký tự đặc biệt như dấu nháy đơn (`'`). Dù có bọc cơ chế escape cơ bản, một số payload nhị phân hoặc chuỗi phức tạp có thể phá vỡ syntax shell trên các hệ điều hành khác nhau.
- **Lộ lọt thông tin:** Việc xuất mã Python hoặc cURL không thực hiện lọc bỏ thông tin nhạy cảm. Mã xuất ra có thể chứa toàn bộ Cookies, Access Tokens hoặc Authorization Header. Người dùng cần cẩn trọng trước khi chia sẻ.

## 5. Chi tiết các Class và Hàm
- **`export_to_json(requests: list[dict], pretty: bool = True) -> str`**: Biến đổi danh sách dictionary thô thành cấu trúc phân tầng JSON (có `request`, `response`, và phân giải `graphql` nếu có). Trả về chuỗi JSON string được định dạng chuẩn.
- **`export_to_har(requests: list[dict]) -> str`**: Chuyển đổi dữ liệu sang định dạng HAR (HTTP Archive) 1.2. Hàm này phân tách URL thành `queryString`, parse cookie/headers, và bọc lại trong cấu trúc quy chuẩn `log.entries`, cho phép Chrome DevTools và các ứng dụng phân tích đọc được biểu đồ thời gian/luồng.
- **`export_to_python(requests: list[dict]) -> str`**: Sinh ra một file mã nguồn `.py` tự động. Nó lọc bỏ bớt các Header nhảy hop (`content-length`, `connection`, `host`), tách riêng Cookie ra một object riêng, tự động parse payload (`x-www-form-urlencoded` hay JSON), sau đó ghép thành lệnh `requests.get/post(...)`.
- **`export_to_curl(requests: list[dict]) -> str`**: Sinh ra danh sách lệnh `curl` bash script. Nó cũng làm sạch header thừa, lặp chuỗi escape `'\''` để chèn Body qua tham số `--data-raw`, và làm ngắn bớt Body nếu kích thước lớn hơn 2000 ký tự (tránh lỗi buffer limit trên Terminal).
- **`_headers_to_har(headers: Any) -> list[dict]`**: Hàm Helper nội bộ, chuyển đổi một dictionary HTTP Headers thành List các phần tử `{"name": k, "value": v}` theo đúng format HAR chuẩn.
- **`_safe_json_parse(s: Optional[str]) -> Any`**: Hàm Helper nội bộ cố gắng parse chuỗi string thành JSON Object. Nếu lỗi hoặc string không phải định dạng JSON (như Form-data), nó sẽ catch exception và trả về chính chuỗi gốc để tránh ứng dụng bị crash.
- **`_format_dict(d: dict) -> str`**: Hàm Helper nội bộ định dạng một Dictionary của Python thành Literal String nhiều dòng, hỗ trợ làm đẹp (pretty-print) khi sinh mã nguồn Python tự động.
