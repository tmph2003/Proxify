# Bỏ Ignore Domain `company.com.vn` - Khôi Phục Bắt Request

## Tóm tắt thay đổi

Xoá `company.com.vn` khỏi danh sách `IGNORE_HOSTS` tại 3 file:
- `backend/proxify/server.py` (giá trị fallback mặc định)
- `docker-compose.yml` (biến môi trường template)
- `.env` (giá trị thực tế được Docker Compose sử dụng — **đây là file quan trọng nhất**)

> ⚠️ **Bài học rút ra:** Docker Compose dùng cú pháp `${VAR:-default}`. Nếu `.env` đã set biến `IGNORE_HOSTS`, giá trị default trong `docker-compose.yml` bị bỏ qua hoàn toàn. Khi sửa env var, **luôn kiểm tra file `.env` trước**.

Domain `company.com.vn` và toàn bộ subdomain (`*.company.com.vn`) sẽ không còn được TCP Passthrough mà sẽ đi qua proxy, được giải mã SSL và ghi log vào CSDL.

## Mục đích & Ý nghĩa

Người dùng yêu cầu khôi phục lại việc bắt request từ domain `company.com.vn` mà trước đó đã được thêm vào danh sách ignore (tham khảo tài liệu gốc tại `docs/infrastructure/internal_subdomains_dns_passthrough_fix.md`).

Mục tiêu: Proxy sẽ can thiệp (MITM) vào các kết nối đến `*.company.com.vn`, cho phép:
- Ghi log request/response vào database
- Các plugin/observer có thể xử lý traffic từ domain này
- Phân tích dữ liệu truy cập nội bộ

## Mối liên hệ

| File | Vai trò |
|---|---|
| `backend/proxify/server.py` | Nơi parse `IGNORE_HOSTS` env var thành danh sách regex pattern, truyền vào `mitmproxy.options.Options` |
| `docker-compose.yml` | Khai báo giá trị mặc định cho biến `IGNORE_HOSTS` khi chạy container |
| `backend/proxify/core/router.py` | `ProxyRouter` nhận `ignored_hosts` để quyết định có xử lý request hay không |

## Rủi ro (Risks & Edge Cases)

> ⚠️ **Rủi ro SSL nội bộ (Nghiêm trọng):**
> - Các subdomain nội bộ (`trino.company.com.vn`, `erp.company.com.vn`, `bi.company.com.vn`...) sử dụng Split-Horizon DNS, resolve về IP mạng LAN (`172.16.100.x`).
> - Proxy sẽ cố giải mã SSL bằng cert giả → trình duyệt hiện lỗi `NET::ERR_CERT_AUTHORITY_INVALID`.
> - Các subdomain có header `Strict-Transport-Security: includeSubDomains` → trình duyệt CHẶN HOÀN TOÀN, không cho "Proceed anyway".

> ⚠️ **Giải pháp khắc phục (nếu bị lỗi):**
> - **Cách 1**: Cấu hình bypass proxy trên Windows: `*.company.com.vn;<local>` trong Proxy Settings.
> - **Cách 2**: Thêm lại `company.com.vn` vào `IGNORE_HOSTS` nếu cần rollback.
> - **Cách 3**: Cài cert CA của mitmproxy (`~/.mitmproxy/mitmproxy-ca-cert.pem`) vào trust store của máy client.

> ⚠️ **Hiệu năng:**
> - Traffic nội bộ (đặc biệt Trino query engine) có thể có lượng data lớn. Việc giải mã SSL + ghi log có thể gây tăng tải cho proxy server.
