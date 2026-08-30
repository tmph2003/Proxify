# Báo cáo: Fix lỗi giải mã Brotli (br) trong hàm phân giải Group ID

## Tóm tắt thay đổi
Đã chỉnh sửa hàm `_resolve_numeric_group_id` trong file `proxify/platforms/facebook/crawler.py` bằng cách thêm header `"accept-encoding": "gzip, deflate"` vào request gửi tới Facebook.

## Mục đích & Ý nghĩa
Sửa lỗi `[Crawler] Lỗi phân giải slug apikhongngonxoagroup: 400, message: Can not decode content-encoding: br`.
Khi gửi request bình thường (hoặc impersonate), Facebook trả về mã nguồn HTML được nén bằng thuật toán Brotli (`br`). Tuy nhiên, thư viện HTTP client hiện tại (như `curl_cffi`) hoặc môi trường Python không thể giải nén định dạng này, dẫn tới lỗi khi đọc `r.text`.
Bằng cách giới hạn `accept-encoding` chỉ nhận `gzip, deflate`, ta buộc Facebook phải trả về dạng dữ liệu dễ giải mã hơn, qua đó loại bỏ được lỗi này và crawler có thể đọc được HTML để lấy ra Group ID thành công.

## Mối liên hệ
- Code bị sửa đổi: `proxify/platforms/facebook/crawler.py`.
- Module liên quan: Ảnh hưởng tới luồng chuyển đổi Slug thành Numeric ID của các request Facebook Graph/GraphQL. 

## Rủi ro (Risks & Edge Cases)
- **Hiệu năng & Băng thông:** Việc tắt `br` compression có thể làm tăng dung lượng phản hồi (payload size) lên một chút so với khi dùng `brotli`, dẫn đến tốn băng thông và có thể mất thêm vài mili-giây thời gian tải. Tuy nhiên so với request crawler lấy cấu trúc trang thì chi phí này không đáng kể.
- **Bảo mật/Cơ chế Anti-Bot:** Việc sử dụng một header `accept-encoding` khác lạ so với một User-Agent Chrome thực tế (`gzip, deflate, br`) có thể tạo ra dấu hiệu bất thường (fingerprint mismatch) khiến Facebook dễ dàng phát hiện đây là một crawler bot nếu họ phân tích header chặt chẽ.
