# Khắc Phục Lỗi Thu Thập Bài Viết Group Facebook (Feed GraphQL Query & Pagination Extraction)

## 1. Tóm tắt thay đổi
- **File sửa đổi:**
  - `backend/proxify/platforms/facebook/crawler.py`
  - `backend/proxify/platforms/facebook/api.py`
  - `backend/tests/test_crawler_synthetic_feed.py`
- **Các điểm cải tiến cốt lõi:**
  1. **Khôi phục đầy đủ bộ biến GraphQL (`DEFAULT_FEED_VARIABLES`):** Bổ sung đầy đủ ~30 tham số bắt buộc của Facebook doc_id `38367899859521393` (`GroupsCometFeedRegularStoriesPaginationQuery`) gồm `feedLocation: "GROUP"`, `feedType: "DISCUSSION"`, `renderLocation: "group"`, `privacySelectorRenderLocation: "COMET_STREAM"`, `scale: 1`, `stream_initial_count: 1` và các Relay feature provider flags. Khi tổng hợp synthetic feed template (`_synthesize_feed_template`) hoặc cập nhật biến (`_set_variables`), hệ thống merge các biến này thay vì ghi đè bằng một dict 3 trường sơ sài.
  2. **Tái cấu trúc thứ tự trích xuất dữ liệu trong vòng lặp phân trang (`crawl_group_feed`):** Di chuyển lời gọi `extract_from_responses` lên **TRƯỚC** các kiểm tra ngắt vòng lặp (`should_stop` do bài viết cũ và `if not cursor: break`). Đảm bảo toàn bộ bài viết hợp lệ trên trang hiện tại đều được bóc tách và ghi nhận vào cơ sở dữ liệu trước khi quyết định dừng phiên cào.
  3. **Bắt lỗi GraphQL Error JSON đầy đủ:** Bổ sung cơ chế phát hiện lỗi trả về từ Facebook khi response dạng `{"errors": [{"message": "...", "code": ...}]}` bên cạnh định dạng truyền thống `for (;;);\n{"error": ...}`.
  4. **Bổ sung Persistence & Fallback cho Token Xác Thực (`fb_dtsg`, `lsd`):** Khi server khởi động lại (container restart), nếu RAM trống, `api.py` sẽ tự động đọc lại token gần nhất từ bảng `requests` hoặc `facebook.config` thay vì báo lỗi thiếu `fb_dtsg`. Đồng thời lưu `fb_dtsg` và `lsd` vào persistent DB khi Extension đồng bộ cookie.
  5. **Chuẩn hóa Header:** Loại bỏ các header trùng tên không phân biệt hoa thường (`Cookie`/`cookie`, `Referer`/`referer`) để tránh xung đột HTTP header.

---

## 2. Mục đích & Ý nghĩa
- **Vấn đề thực tế gặp phải:**
  - Khi người dùng chọn cào bài viết một nhóm (ví dụ: `653788109986328`) từ ngày 3/9 đến 4/9:
    - Template tự động tổng hợp chỉ truyền 3 tham số `{id, sortingSetting, count}`.
    - Facebook trả về mã HTTP 200 kèm payload JSON: `{"errors":[{"message":"A server error missing_required_variable_value occured. Check server logs for details.","code":1675012}]}`.
    - Do payload này không có cursor, hàm `_extract_cursor` trả về rỗng (`""`).
    - Đoạn code cũ có logic `if not cursor: break` đặt **trước** hàm trích xuất `extract_from_responses`, dẫn đến việc crawler ngay lập tức `break` ở Page 1 mà không bóc tách bất kỳ bài viết nào, đồng thời báo "Hoàn tất thu thập" với 0 bài viết.
- **Ý nghĩa giải pháp:**
  - Đảm bảo các gói tin GraphQL gửi lên Facebook tuân thủ nghiêm ngặt schema mà Facebook Relay Compiler yêu cầu, loại bỏ triệt để lỗi `missing_required_variable_value`.
  - Đảm bảo tính toàn vẹn dữ liệu (Data Integrity): dữ liệu của trang cuối cùng hoặc trang chứa bài viết chuyển tiếp ngày luôn được lưu trữ trước khi ngắt vòng lặp.

---

## 3. Mối liên hệ kiến trúc
- **`crawler.py` (Domain / Application Layer):** Quản lý chu trình cào phân trang qua Extension Bridge và bảo vệ chống ngắt kết nối đột ngột.
- **`extractor.py` (Data Extraction Layer):** Chịu trách nhiệm bóc tách các Story node, lọc bài viết theo dải ngày (`start_ts`, `end_ts`), loại bỏ bài viết rác từ Page/User bên ngoài Group và upsert vào cơ sở dữ liệu.
- **`api.py` (Interface / Controller Layer):** Nhận request từ React Frontend, khởi tạo state và điều phối Background Worker thực thi lệnh `CrawlFeedCommand`.
- **Extension Bridge (Infrastructure Layer):** Thực thi request in-tab trên trình duyệt của người dùng để bảo vệ phiên đăng nhập an toàn, sử dụng cookie và token sống từ browser context.

---

## 4. Rủi ro & Giải pháp phòng ngừa (Risks & Edge Cases)
- **Rủi ro Facebook cập nhật Relay Provider flags:**
  - Facebook thường xuyên thay đổi tên các Relay providers (`__relay_internal__pv__...`).
  - *Giải pháp:* `_synthesize_feed_template` ưu tiên lấy template thực tế từ bảng `requests` nếu người dùng vừa lướt Facebook trên trình duyệt. Bộ `DEFAULT_FEED_VARIABLES` đóng vai trò là "lưới an toàn" (safety net) khi Extension chưa kịp bắt request thực tế.
- **Rủi ro bài viết ghim (Pinned Posts) có ngày đăng rất cũ:**
  - Nếu nhóm có các bài ghim từ nhiều năm trước, `_check_old_posts` yêu cầu phải gặp ít nhất 3 trang liên tiếp toàn bộ bài viết cũ hơn `start_ts` mới dừng cào, ngăn chặn dừng non ở trang 1.
- **Rủi ro trùng lặp khóa chính:**
  - Toàn bộ thao tác ghi dữ liệu sử dụng UPSERT (`ON CONFLICT (post_id) DO UPDATE`), đảm bảo chạy lại nhiều lần không làm hỏng dữ liệu hoặc trùng lặp bài viết.
