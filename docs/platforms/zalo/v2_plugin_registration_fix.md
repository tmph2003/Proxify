# Tài liệu: Sửa lỗi Plugin Zalo không hoạt động trên Server v2

## Tóm tắt thay đổi
- Chỉnh sửa file `proxify/server_v2.py`: Thêm dòng `router.register_mutator(zalo_plugin)` để đăng ký plugin Zalo vào hệ thống Proxy Router (V2).

## Mục đích & Ý nghĩa
- Trong quá trình thiết kế Server v2, code khởi tạo ZaloPlugin đã được thêm vào nhưng lại quên mất bước quan trọng nhất: Đăng ký plugin này với bộ định tuyến luồng (ProxyRouter). 
- Hậu quả là toàn bộ các phương thức `on_request` và `on_response` của ZaloPlugin không bao giờ được gọi khi có request đi qua Proxy. Việc đăng ký nó dưới dạng Mutator cho phép ZaloPlugin bắt được các request/response từ máy khách, thực hiện chặn, thay đổi (chèn JS Hook vào giao diện web của Zalo) và lấy dữ liệu.

## Mối liên hệ
- Liên quan tới luồng khởi tạo của Server V2 (`server_v2.py`) và module định tuyến trung tâm (`ProxyRouter`). 
- Liên quan trực tiếp tới khả năng thu thập thông báo từ Zalo của `ZaloPlugin`.

## Rủi ro (Risks & Edge Cases)
- Do ZaloPlugin chặn toàn bộ các domain của Zalo để phân tích nội dung, việc đưa ZaloPlugin vào luồng Mutator (chạy đồng bộ) có thể thêm 1 chút overhead nhỏ, nhưng cần thiết vì ta phải can thiệp (chèn JS) trực tiếp vào file phản hồi của trình duyệt.
