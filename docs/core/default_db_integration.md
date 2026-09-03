# Tài liệu Kỹ thuật: Thiết lập Mặc định Bật Ghi Database (DB Integration Default True)

## Tóm tắt thay đổi

1. **`docker-compose.yml`**:
   - Thêm biến môi trường `DB_INTEGRATION_ENABLED=true` vào service `proxify`.
2. **`backend/proxify/storage/__init__.py`**:
   - Đổi giá trị mặc định của `DB_INTEGRATION_ENABLED` từ `"false"` thành `"true"`.
3. **`frontend/src/pages/Dashboard.tsx`**:
   - Khởi tạo giá trị `dbIntegrationEnabled` mặc định là `true` (chỉ `false` khi người dùng đã chủ động bấm tắt trong session).
4. **`backend/proxify/ui/templates/index.html`**:
   - Đổi biến `let dbIntegrationEnabled = true;` và giao diện nút bấm ban đầu thành `🟢 Ghi DB: BẬT`.

---

## Mục đích & Ý nghĩa

- Đáp ứng yêu cầu của người dùng: Mặc định bật ghi cơ sở dữ liệu để hệ thống tự động lưu trữ các request và bài viết/bình luận Facebook, Zalo vào PostgreSQL mà không cần người dùng phải bấm bật thủ công trên giao diện mỗi khi mở Dashboard.
- Giúp việc kiểm tra, theo dõi dữ liệu đã cào trong PostgreSQL (`facebook.posts`, `public.requests`, `core.raw_payloads`) diễn ra liên tục, tự động.

---

## Mối liên hệ

- `storage/__init__.py` $\leftrightarrow$ `RequestStorage.db_integration_enabled`: Cờ quyết định việc đẩy các HTTP flow vào database pool.
- `Dashboard.tsx` & `index.html`: Đồng bộ trạng thái hiển thị của nút toggle "🟢 Ghi DB: BẬT" với backend.
- `docker-compose.yml`: Đảm bảo khi deploy hoặc rebuild container, cờ này luôn được gán bằng `true`.

---

## Rủi ro & Lưu ý

- Khi ghi DB mặc định bật, dung lượng database có thể tăng nhanh hơn nếu có nhiều request đi qua proxy. Tuy nhiên hệ thống đã có sẵn tính năng "Lọc Ghi DB" (Domain Filtering) để người dùng có thể giới hạn tên miền cần ghi nếu muốn.
