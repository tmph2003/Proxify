# Tài liệu: Tích hợp lại YouTubePlugin vào Server V2

## Tóm tắt thay đổi
- Chỉnh sửa file `proxify/server_v2.py`. Bổ sung đoạn code khởi tạo và đưa `YouTubePlugin` vào `ProxyRouter` (với tư cách là một observer) bằng phương thức `router._insert(...)`.
- Khi plugin này được nạp thành công, sẽ có dòng log `📺 YouTube Plugin ENABLED in v2`.

## Mục đích & Ý nghĩa
- Người dùng phàn nàn rằng **việc chặn quảng cáo YouTube không hoạt động** trên phiên bản Server V2. Nguyên nhân là do cấu trúc `server_v2.py` đã chuyển qua mô hình Router & Plugins mới, nhưng mới chỉ có `FacebookPlatform` được load lên, bỏ quên mất `YouTubePlugin`. Việc thêm plugin này giúp khôi phục hoàn toàn tính năng tự động chặn (fast-skip) quảng cáo và tracker trên YouTube theo logic có sẵn.

## Mối liên hệ
- Sử dụng trực tiếp `YouTubePlugin` từ `proxify/plugins/youtube.py` (nơi chứa các logic block tracking và inject script bỏ qua quảng cáo).

## Rủi ro (Risks & Edge Cases)
- `router._insert` được gọi trực tiếp (dù là hàm private) để đăng ký thủ công thay vì thông qua một Platform lớn. Tuy nhiên, cách làm này an toàn vì `YouTubePlugin` đã được thiết kế sẵn chuẩn `BasePlugin` và cung cấp đầy đủ danh sách `target_domains`. Việc gọi sai hàm hoặc tên miền không hợp lệ đều được bảo vệ bởi khối `try-except`.
