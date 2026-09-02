# Hỗ trợ Proxy Chrome Extension cho Facebook

## Tóm tắt thay đổi
- Chỉnh sửa `frontend/src/hooks/useFacebook.ts` để tự động kéo Cookie đã được Extension đồng bộ từ Backend mỗi khi tải trang.
- Chỉnh sửa `backend/proxify/plugins/facebook.py` để ưu tiên sử dụng `fb_dtsg` và `cookie` từ Extension (nếu có), bỏ qua việc gọi trình cào tự động (`auth_fetcher`) để chống lỗi Checkpoint/chặn IP.
- Tìm thấy và hoàn thiện một thư mục Chrome Extension có sẵn tại `backend/chrome_extension` với đầy đủ tính năng lấy `fb_dtsg`, `lsd`, và Cookie tự động từ Facebook rồi gửi về API.

## Mục đích & Ý nghĩa
- Khắc phục triệt để lỗi không lấy được `fb_dtsg` bằng thư viện Python (`curl_cffi`) do Facebook tăng cường bảo mật. Bằng cách sử dụng Chrome Extension, mọi thao tác lấy Token đều diễn ra ở môi trường trình duyệt thật của người dùng -> Hợp lệ 100%.

## Mối liên hệ
- Frontend `Dashboard.tsx` -> `useFacebook.ts` (Gọi API lấy Cookie).
- Backend `facebook.py` -> Nhận Cookie từ Extension và xử lý Crawler.

## Rủi ro (Risks & Edge Cases)
- Trải nghiệm người dùng thay đổi (Người dùng phải cài đặt Chrome Extension thủ công).
- Cookie được gửi về Backend được lưu trên RAM, nếu Backend bị khởi động lại, người dùng phải bấm "Đồng bộ ngay" lại trên Extension.
