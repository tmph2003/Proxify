# Tài Liệu Kỹ Thuật: Rà Soát & Loại Bỏ Định Danh Doanh Nghiệp (Privacy & Security Sanitization)

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `docs/infrastructure/chrome_proxy_bypass_fix.md`
  - Loại bỏ tên doanh nghiệp cụ thể, thay thế bằng định danh chung "mạng nội bộ công ty".
- **File sửa đổi 2:** `docs/infrastructure/zalo_pc_and_system_bypass_fix.md`
  - Ẩn dải domain bypass cụ thể của doanh nghiệp thành `*.company.com.vn`.
- **File sửa đổi 3:** `docs/tools/powerbi_permission_automation.md`
  - Làm sạch các định danh bảo mật, tài khoản Active Directory cá nhân (`COMPANY\admin_user`, `COMPANY\user1`) và domain PBIRS nội bộ.
- **File sửa đổi 4:** `docs/core/ignore_hosts_configuration.md`
  - Đổi domain truy vấn Trino nội bộ thành `trino.company.com.vn`.
- **File sửa đổi 5:** `docs/AI_log.md`
  - Chuẩn hóa lịch sử nhật ký phát triển, che giấu domain doanh nghiệp.
- **Tái cấu trúc file tài liệu:**
  - `docs/infrastructure/sunhouse_subdomains_dns_passthrough_fix.md` -> `docs/infrastructure/internal_subdomains_dns_passthrough_fix.md`.
  - `docs/infrastructure/remove_sunhouse_ignore.md` -> `docs/infrastructure/remove_internal_domain_ignore.md`.
  - Làm sạch toàn bộ nội dung bên trong hai file này.
- **Kiểm tra rà soát toàn dự án:**
  - Thực thi kiểm tra regex toàn bộ workspace và git index, xác nhận 0 còn bất kỳ từ khóa định danh doanh nghiệp nào xuất hiện trong mã nguồn, tài liệu hoặc cấu hình.

---

## 2. Mục đích & Ý nghĩa

### Bối cảnh & Yêu cầu
Người dùng yêu cầu loại bỏ toàn bộ các comment, ghi chú và định danh liên quan đến doanh nghiệp ra khỏi repository dự án Proxify.

### Ý nghĩa Kỹ thuật & Bảo mật (Information Security & Privacy)
1. **Tuân thủ Nguyên tắc Bảo vệ Dữ liệu Doanh nghiệp:**
   - Ngăn chặn lộ lọt tên miền nội bộ, cấu trúc phân quyền Active Directory, tên tài khoản nhân sự và sơ đồ mạng LAN (`172.16.x.x`).
2. **Tổng quát hóa Mã nguồn (Codebase Generalization):**
   - Giúp repository giữ được tính độc lập, sẵn sàng mở mã nguồn hoặc chia sẻ mà không làm rò rỉ thông tin hạ tầng bí mật của bất kỳ tổ chức nào.

---

## 3. Mối liên hệ

| Thành phần | Vai trò |
|---|---|
| Toàn bộ thư mục `docs/` | Đã được chuẩn hóa và loại bỏ hoàn toàn các định danh nhạy cảm |
| `backend/` & `frontend/` | Đảm bảo tính trung lập, không phụ thuộc vào hạ tầng mạng cục bộ |
| Git Index & Working Tree | Đã được đồng bộ, các file đổi tên được theo dõi qua `git mv` |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Gãy liên kết tham chiếu (Broken Document Links):**
   - *Rủi ro:* Các tài liệu cũ trỏ tới `sunhouse_subdomains_dns_passthrough_fix.md` có thể bị lỗi liên kết nếu đường dẫn không được cập nhật.
   - *Giảm thiểu:* Đã cập nhật tất cả các đường dẫn nội bộ trong `docs/` trỏ tới tên file mới `internal_subdomains_dns_passthrough_fix.md`.
2. **Khả năng ảnh hưởng logic chạy code:**
   - *Đánh giá:* 0% rủi ro do tất cả thay đổi đều nằm trên tầng tài liệu (`docs/`), không can thiệp vào logic thực thi của core proxy hay database.
