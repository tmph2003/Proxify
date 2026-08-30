# Tài liệu cập nhật Crawler (Facebook)

**File bị ảnh hưởng:** `proxify/platforms/facebook/crawler.py`

## 1. Tóm tắt thay đổi
- Sửa lại hàm `_check_old_posts` để trả về danh sách các timestamps của các bài viết có trong trang.
- Sửa lỗi vòng lặp vô hạn (infinite loop) khi bỏ giới hạn "40% bài cũ". Crawler giờ đây sẽ dừng khi phát hiện bài viết cũ hơn `start_timestamp`.
- **Cập nhật (Bug Fix):** Cải tiến thuật toán bỏ qua Bài Viết Ghim (Pinned Posts). Trước đây, Crawler dừng ngay nếu phát hiện bài viết cũ. Tuy nhiên, nếu Group ghim 3-5 bài cũ ở đầu trang, Crawler sẽ lầm tưởng đã lướt hết mốc thời gian và dừng sớm. Thuật toán mới áp dụng cơ chế `consecutive`: Crawler chỉ thực sự dừng khi gặp **3 trang liên tiếp (khoảng 9 bài viết)** mà TẤT CẢ đều cũ hơn thời gian quy định. Điều này đảm bảo crawler đã "xuyên qua" lớp bài ghim ở trên cùng và đang thực sự quét dòng thời gian cũ.
- Cập nhật giao diện Status Box: Thay vì hiển thị "Đã thu thập X bài...", Crawler sẽ chỉ hiển thị "Đang thu thập trang Y... (Đã quét đến ngày DD/MM/YYYY)" để người dùng dễ theo dõi tiến độ lùi về quá khứ.

**File bị ảnh hưởng phụ:** `proxify/platforms/facebook/template_fetcher.py`
- **Cập nhật (Bug Fix):** Sửa lỗi Crawler bị "mù" thời gian do Facebook trả về dữ liệu theo chế độ "Top Posts" (Hoạt động mới) thay vì "Chronological" (Bài mới nhất). Cụ thể, khi Playwright mở trang Group để mồi lấy Template GraphQL, nó mặc định lấy Template của "Top Posts" (vốn xếp bài cũ nhưng có bình luận mới lên đầu). Điều này khiến Crawler thấy toàn bài cũ từ nhiều tháng trước ở ngay Trang 1 và tắt máy sớm. Đã fix bằng cách ép Playwright truy cập URL kèm `?sorting_setting=CHRONOLOGICAL`.

## 2. Mục đích & Ý nghĩa
- **Khắc phục lỗi nghiêm trọng:** Trước đó, việc ép hàm `_check_old_posts` trả về `False` liên tục đã vô tình phá vỡ hoàn toàn cơ chế dừng của Crawler, khiến nó chạy mãi mãi (hoặc đến khi chạm giới hạn 1000 trang của Session). Bản vá này khôi phục lại khả năng dừng đúng mốc thời gian `Từ ngày` mà người dùng đã cài đặt.
- **Cải thiện Trải nghiệm Người dùng (UX):** Việc hiển thị số lượng bài thu thập trên Status Box gây hiểu lầm cho người dùng (vì các bài ngoài khoảng thời gian vẫn bị đếm là 3 bài do pagination của Facebook). Việc đổi sang hiển thị "Đã quét đến ngày..." giúp người dùng an tâm rằng hệ thống đang đi đúng hướng về mốc thời gian họ yêu cầu.

## 3. Mối liên hệ
- Hoạt động chặt chẽ với hàm `extract_from_responses` trong `extractor.py` (hàm này có nhiệm vụ lọc các bài viết nằm ngoài khoảng thời gian, trả về `p_count = 0`).
- Giao diện UI (`facebook.html`) đọc trực tiếp thông báo này thông qua polling `/api/facebook/crawl_status` và hiển thị trực tiếp lên giao diện (Status Box).

## 4. Rủi ro (Risks & Edge Cases)
- **Thiếu `creation_time`:** Nếu một trang (page) toàn các bài ghim hoặc bài viết lỗi không có trường `creation_time`, biến `timestamps` sẽ rỗng. Trong trường hợp này, thông báo sẽ bỏ qua phần "(Đã quét đến ngày...)" và tiếp tục lướt trang tiếp theo.
- **Timezone (Múi giờ):** `datetime.fromtimestamp` sẽ sử dụng múi giờ mặc định của Server (có thể là UTC hoặc GMT+7 tuỳ cấu hình Docker). Điều này có thể dẫn đến lệch vài giờ khi hiển thị so với giờ thực tế ở Việt Nam, nhưng không ảnh hưởng đến logic lọc bài (do logic lọc dùng Unix Timestamp tuyệt đối).
