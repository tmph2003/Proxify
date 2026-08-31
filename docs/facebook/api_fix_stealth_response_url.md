# Sửa lỗi Typo r.url trong curl_cffi (api.py)

## Tóm tắt thay đổi
Trong file `proxify/platforms/facebook/api.py` (hàm `_update_tokens_via_http`):
Gỡ bỏ đoạn mã kiểm tra `r.url` vì `StealthSessionManager.request()` trả về `StealthResponse`, đối tượng này không chứa thuộc tính `url`.

## Mục đích & Ý nghĩa
- **Lỗi cũ:** Sau khi nâng cấp từ `curl_cffi.AsyncSession` lên `StealthSessionManager` (để sửa lỗi Fingerprint), hàm request trả về object tùy chỉnh `StealthResponse`. Khi code gọi `r.url`, Python ném ra exception `AttributeError: 'StealthResponse' object has no attribute 'url'`. Exception này làm hàm bắt lỗi trả về `None`, dẫn đến hiển thị lỗi giả "Cookie Facebook đã hết hạn".
- **Giải pháp:** Xóa đoạn check `r.url`. Bản thân `StealthSessionManager` đã tự động ném ra `AccountCheckpointError` nếu Facebook trả về trang `/checkpoint` hoặc bị soft-block. Do đó, nếu request thành công (không có exception), chúng ta chỉ cần kiểm tra xem có bắt được `fb_dtsg` hay không là đủ.

## Mối liên hệ
- File sửa đổi: `proxify/platforms/facebook/api.py`.
- Tác động: Khôi phục lại tính năng lấy template/token tự động không cần dùng Extension.

## Rủi ro (Risks & Edge Cases)
Không có. Code an toàn hơn vì loại bỏ được lỗi crash do sai kiểu đối tượng.
