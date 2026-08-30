# Tài liệu: Sửa lỗi Import thiếu class DataHelper trong facebook/crawler.py

## Tóm tắt thay đổi
Trong file `proxify/platforms/facebook/crawler.py`, đoạn code dùng để bóc tách node GraphQL đang gọi đến hàm `DataHelper.extract_nodes(...)`. Tuy nhiên ở đầu file lại thiếu câu lệnh import class `DataHelper`. 
Tôi đã tiến hành bổ sung `DataHelper` vào câu lệnh import từ module `proxify.platforms.facebook.extractor`.

## Mục đích & Ý nghĩa
- Khắc phục lỗi `unknown-name` (như linter của bạn đã báo) giúp file chạy bình thường, không bị văng lỗi `NameError` khi đến bước xử lý `extract_nodes` của GraphQL.
- Đảm bảo tính toàn vẹn của mã nguồn khi chạy.

## Mối liên hệ
- Lỗi này xảy ra ở file `proxify/platforms/facebook/crawler.py`.
- Lấy `DataHelper` từ file `proxify/platforms/facebook/extractor.py`.

## Rủi ro (Risks & Edge Cases)
- Vì đây chỉ là sửa lỗi thiếu import, không thay đổi logic code, nên hoàn toàn không có rủi ro nào. Linter của bạn bây giờ sẽ báo xanh (pass).
