# Auto Documentation: Stream Bypassing (OOM Protection)

## 1. Tóm tắt thay đổi
- Cập nhật chuẩn `IObserverInterceptor` và `IMutatorInterceptor` bổ sung thêm event `handle_responseheaders`.
- Tích hợp tính năng bảo vệ RAM (OOM Protection) thẳng vào `ProxyRouter` (`proxify/core/router.py`). Khi nhận được gói tin có header `Content-Type` là video/audio hoặc có dung lượng `Content-Length > 5MB`, Router sẽ tự động bật cờ `flow.response.stream = True`.
- Cập nhật `ProxyAddon` trong `server_v2.py` để hứng sự kiện `responseheaders` từ Mitmproxy.

## 2. Mục đích & Ý nghĩa
- Khắc phục triệt để điểm yếu chí mạng của Mitmproxy: tự động load toàn bộ body của gói tin vào RAM. Nhờ tính năng Bypassing này, khi người dùng xem video livestream Facebook 100MB, proxy sẽ stream thẳng dữ liệu qua browser mà không nuốt 100MB RAM, giúp Server có thể chạy ròng rã nhiều tháng mà không bị Out of Memory (OOM).

## 3. Rủi ro (Risks & Edge Cases)
- Khi một flow bị bật cờ `stream = True`, sự kiện `response` phía sau sẽ không có nội dung (body trống). Điều này có nghĩa là các Addon đứng sau sẽ không đọc được nội dung của gói tin này. Tuy nhiên, vì chúng ta chỉ bypass đối với video/audio/file bự (những thứ vốn dĩ không chứa mã HTML/GraphQL cần bóc tách), nên rủi ro mất dữ liệu Facebook GraphQL là 0%.
