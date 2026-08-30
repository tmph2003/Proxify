# Tài liệu: graphql.py

## 1. Tóm tắt tổng quan
Module cung cấp tiện ích phân tích và trích xuất dữ liệu từ payload của các request GraphQL.

## 2. Mục đích & Ý nghĩa
Chuẩn hóa việc bóc tách thông tin từ các request GraphQL đi qua mạng. Do GraphQL có thể được gửi dưới dạng JSON chuẩn hoặc dạng form URL-encoded (đặc thù của hạ tầng Facebook), hàm tiện ích trong file này giúp hệ thống lấy được các tham số cốt lõi (`operationName`, `doc_id`, `variables`) bất kể định dạng truyền tải.

## 3. Mối liên hệ
Module được sử dụng bởi các luồng giải mã (decoder) hoặc filter trong Proxify khi hệ thống cần biết chính xác loại truy vấn (query) hoặc mutation nào đang được thực thi trên Facebook/GraphQL endpoints.

## 4. Rủi ro (Risks & Edge Cases)
- **Parse JSON không an toàn:** Mặc dù đã có khối `try...except`, nhưng quá trình sử dụng `json.loads` với dữ liệu không đáng tin cậy vẫn cần giám sát.
- **Bắt Keyword Cứng Nhắc:** Thuật toán bắt URL-encoded phụ thuộc vào các tham số cụ thể của Facebook (như `fb_api_req_friendly_name` hay `doc_id`). Nếu Facebook thay đổi cơ chế hoặc đổi tên tham số, module sẽ trả về `None` làm hỏng luồng parse.

## 5. Chi tiết các Class và Hàm

- **Hàm `parse_graphql_request(request_body: str) -> Tuple[Optional[str], Optional[str], Optional[str]]`**:
  - **Mục đích**: Nhận vào nội dung text của HTTP request body và trả về một Tuple chứa 3 thông tin `(operation_name, doc_id, variables)`.
  - **Logic xử lý**:
    - Kiểm tra nếu body trống thì trả về `None` cho cả 3.
    - **Trường hợp 1:** Thử parse theo cấu trúc Facebook. Nhận diện nếu body chứa chuỗi `fb_api_req_friendly_name=` hoặc `doc_id=`. Sử dụng `urllib.parse.parse_qs` để bóc tách. Nếu tham số `variables` có tồn tại, hàm còn cẩn thận thử nghiệm parse JSON để đảm bảo tính hợp lệ trước khi lấy.
    - **Trường hợp 2:** Thử parse theo cấu trúc chuẩn JSON GraphQL. Nếu body bắt đầu bằng dấu `{`, sử dụng `json.loads` để chuyển thành từ điển (Dict) và lấy ra `operationName`, `variables`. `variables` sau đó được dump lại thành chuỗi JSON đảm bảo format unicode chuẩn.
    - Hàm có sử dụng vòng vây `try...except Exception` tổng quát để bắt mọi sự cố parse, đảm bảo không làm crash chương trình.
