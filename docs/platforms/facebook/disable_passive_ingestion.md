# Tài liệu Kỹ thuật: Vô hiệu hóa Thu thập Bị động (Passive Ingestion) & Dọn dẹp Bài viết Rác

## Tóm tắt thay đổi

1. **`backend/proxify/platforms/facebook/interceptor.py`**:
   - Vô hiệu hóa việc đẩy sự kiện `facebook.graphql.response` vào EventBus khi người dùng duyệt web bình thường.
   - Giữ nguyên việc thu thập `facebook.graphql.request` để hệ thống vẫn tự động học mẫu query/headers/form_data (GroupsCometFeed, comment, reply).
2. **`backend/proxify/core/worker.py`**:
   - Vô hiệu hóa `_handle_fb_graphql_response()` trong vòng lặp của BackgroundWorker. Hệ thống sẽ không tự ý phân tích các gói tin phản hồi GraphQL ngẫu nhiên sinh ra từ trình duyệt.
   - Toàn bộ cơ chế bóc tách bài viết giờ đây chỉ diễn ra khi và chỉ khi người dùng **chủ động cào qua Dashboard hoặc Crawler API**.
3. **Dọn dẹp cơ sở dữ liệu (`facebook.posts`)**:
   - Đã xóa sạch 5 bài viết lạ/rác không mong muốn:
     - 1 video Reels từ "Yeah1 Music" (`1693109542180629`).
     - 1 bài viết từ nhóm "Cơm AI lo" (`965896003211080`).
     - 1 bài viết từ nhóm "Đảo Mèo" (`3001710800304737`).
     - 2 bài viết từ trang cá nhân của bạn bè (`122107610379418002`, `122107609791418002`).
   - Sau khi dọn dẹp, database chỉ còn lại 34 bài viết chính xác từ 2 nhóm mục tiêu:
     - `API Không Ngon, Xoá Group!` (8 bài)
     - `Data Jobs in Vietnam - Data Analysts / Data Scientist / Data Engineer 📊` (26 bài)

---

## Mục đích & Ý nghĩa

- Giúp bảo vệ tính trong sạch và chính xác của dữ liệu trong cơ sở dữ liệu.
- Ngăn ngừa tình trạng khi người dùng sử dụng trình duyệt để giải trí cá nhân (xem video Reels, xem trang cá nhân bạn bè, mở các nhóm khác), dữ liệu cá nhân đó bị vô tình cào ngầm vào hệ thống phân tích doanh nghiệp.
- Tiết kiệm đáng kể dung lượng ổ cứng, giảm thiểu I/O database và tải CPU của container `proxify_app`.

---

## Mối liên hệ

- `interceptor.py` $\rightarrow$ `EventBus` $\rightarrow$ `core.raw_payloads` $\rightarrow$ `worker.py` $\rightarrow$ `facebook.posts`.
- Luồng cào chủ động qua `crawler.py` (sử dụng Extension Tab hoặc Graph API) hoàn toàn không bị ảnh hưởng và vẫn hoạt động độc lập, chính xác.

---

## Rủi ro & Lưu ý

- Không có rủi ro. Việc vô hiệu hóa luồng bóc tách ngẫu nhiên giúp ứng dụng vận hành an toàn và bảo mật hơn rất nhiều.
