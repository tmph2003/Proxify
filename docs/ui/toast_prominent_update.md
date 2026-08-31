# Tóm tắt thay đổi

1. Sửa đổi CSS của thành phần `.toast-container` và `.toast` trong file `proxify/ui/templates/facebook.html`.

# Mục đích & Ý nghĩa

- Chuyển vị trí hiển thị của thông báo Toast từ góc dưới bên phải (`bottom: 24px`) lên góc trên bên phải (`top: 24px`) để dễ quan sát hơn.
- Áp dụng nền gradient nổi bật (Xanh lam - Tím), chữ trắng, viền sáng và hiệu ứng phát sáng mờ (glow shadow) để Toast thu hút được sự chú ý của người dùng mỗi khi có biến động về dữ liệu (ví dụ: crawl được bài viết mới).

# Mối liên hệ

- File `facebook.html` (chứa giao diện người dùng của phần quản lý Facebook).

# Rủi ro (Risks & Edge Cases)

- Giao diện có thể che khuất một phần menu ở góc trên bên phải nếu màn hình quá nhỏ, tuy nhiên do Toast chỉ hiện trong vài giây rồi tự ẩn nên rủi ro này là không đáng kể.
