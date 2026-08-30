# Tài liệu: Sửa lỗi con trỏ trang (Cursor) không bị reset khi khởi chạy Crawler mới

## Tóm tắt thay đổi
- Sửa lỗi trong hàm `_execute_crawl_group_feed` của `proxify/platforms/facebook/crawler.py`: Logic trước đó gọi `fb_db.config.get(...)` để lấy cursor phân trang cũ từ database, nhưng lại **bỏ qua hoàn toàn tham số `reset_cursor`** truyền vào hàm.
- Sửa thành: `cursor = "" if reset_cursor else (fb_db.config.get(...) or "")`.

## Mục đích & Ý nghĩa
- Nguyên nhân khiến Crawler hiển thị trạng thái đang ở những ngày rất cũ (ví dụ 22/08) ngay ở Trang 2, mặc dù người dùng vừa lọc ngày mới (26/08 - 27/08), là do nó đã "vớ" lấy con trỏ của lần chạy trước đó trong database. Lần chạy trước đó dừng lại ở ngày 22/08, nên lần này nó chạy tiếp từ 22/08 thay vì bắt đầu từ đầu (Trang 1 thực sự của Group).
- Vì nó quét từ 22/08 (nhỏ hơn 26/08), hàm check điều kiện dừng đã bị kích hoạt sớm (báo là đã quá sâu) rồi tắt tool, khiến các bài viết cần thiết bị bỏ qua sạch sẽ.
- Sửa lỗi này giúp Crawler luôn quét lại từ đầu (Trang 1 mới nhất) mỗi khi người dùng bấm "Đang cào...", đảm bảo dữ liệu mới nhất được lấy về.

## Mối liên hệ
- Liên quan trực tiếp tới luồng phân trang (Pagination Loop) của Crawler.
- Giải thích hoàn toàn bức ảnh chụp màn hình UI hiện lỗi nhảy cóc ngày.

## Rủi ro (Risks & Edge Cases)
- Với thay đổi này, Crawler sẽ mất đi khả năng quét tiếp từ vị trí cũ NẾU tham số `reset_cursor=True`. Tuy nhiên, flow gọi API từ UI mặc định hiện đang set là True để lấy bài mới. Nếu tương lai cần tính năng Resume (Tiếp tục quét), ta chỉ cần set API gửi `reset_cursor=False`.
