# Cập nhật logic trạng thái Crawler (crawler.py)

## Tóm tắt thay đổi
Sửa đổi logic cập nhật trạng thái ở cuối hàm `_execute_crawl_group_feed` trong file `crawler.py`. Chỉ ghi đè trạng thái thành `idle` (Hoàn tất) nếu trạng thái trước đó đang là `running`. 

## Mục đích & Ý nghĩa
Trước đây, dù vòng lặp crawl kết thúc sớm do lỗi (ví dụ: lỗi xác thực 1357001 từ GraphQL do cookie hết hạn) hoặc do bị Facebook block, hàm vẫn luôn thực thi câu lệnh cập nhật trạng thái `idle` và thông báo "Hoàn tất thu thập..." ở dòng cuối cùng của hàm. Việc này khiến giao diện người dùng hiển thị thông báo "Hoàn tất" sai lệch thay vì hiển thị lỗi thực sự, làm người dùng khó hiểu vì sao crawler không thu thập được bài nào mà lại báo xong ngay lập tức.

## Mối liên hệ
- File bị ảnh hưởng: `proxify/platforms/facebook/crawler.py`.
- Liên quan tới trải nghiệm người dùng trên Dashboard khi theo dõi thanh trạng thái crawl.

## Rủi ro (Risks & Edge Cases)
- Các lỗi nội bộ hoặc các trường hợp break vòng lặp mới phát sinh sau này nếu chưa được cập nhật trạng thái lỗi cụ thể thì crawler sẽ giữ nguyên trạng thái cũ (chẳng hạn `running`), có thể dẫn đến treo UI nếu không xử lý kỹ.
- Giải pháp: Đảm bảo mọi nhánh `break` trong vòng lặp đều phải cập nhật `self.crawl_state` (error, blocked, paused) trước khi thoát vòng lặp.
