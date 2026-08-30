# Auto Documentation: Offline Parsing & Stealth Addon (CQRS Full Loop)

## 1. Tóm tắt thay đổi
- `server_v2.py`: Đã kích hoạt module `StealthUpstreamAddon` để thay đổi JA3 TLS Fingerprint, ngụy trang proxy thành trình duyệt Chrome thật nhằm vượt qua Antibot của Facebook/Zalo.
- `interceptor.py`: Bổ sung khả năng sao chép toàn bộ cục JSON phản hồi (GraphQL Response) khi lướt web và đẩy xuống `facebook.graphql.response`.
- `worker.py`: Worker giờ đây đã có khả năng đọc các event `facebook.graphql.response`. Nó ném cục JSON vào hàm `extract_from_responses` (chạy trên thread riêng) để bóc tách tự động và insert vào Database.

## 2. Mục đích & Ý nghĩa
- Hoàn thiện khép kín vòng lặp CQRS Data Normalization. Nhờ vậy, *ngay cả khi Crawler không chạy*, việc người dùng mở trình duyệt lướt Facebook cũng sẽ tự động thu thập bài viết và bình luận một cách âm thầm thông qua Background Worker. 
- Tính năng Stealth đảm bảo Server không bị khóa IP khi gửi quá nhiều request.

## 3. Rủi ro (Risks & Edge Cases)
- Hàm bóc tách cũ `extract_from_responses` đòi hỏi biến `vars_dict` (trích xuất từ request) để lấy `group_id` phòng hờ. Vì HTTP Response và Request đang bị tách rời trong kiến trúc mới (bắt ở 2 event khác nhau), Worker tạm thời trích xuất mà không có `vars_dict`. Điều này có nghĩa là một số bài viết có thể không có `group_id` nếu bản thân cục JSON response không chứa thông tin đó. Cần tối ưu bằng cách lưu Cache nối Request/Response theo `flow_id` sau này.
