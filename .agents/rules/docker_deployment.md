# Docker Deployment Rule

Trong suốt quá trình làm việc với dự án **Proxify**, Agent **BẮT BUỘC** phải luôn ghi nhớ và tuân thủ các quy tắc về môi trường phát triển (Docker) như sau:

1. **Môi trường hoạt động:** Dự án này được người dùng phát triển và triển khai hoàn toàn trên **Docker** (thông qua file `docker-compose.yml`), **không chạy trực tiếp (local) trên máy host**.
2. **Khởi động & Khởi động lại Server:** 
   - Sau khi sửa bất kỳ file mã nguồn (`.py`, `.js`, `.css`, v.v.) nào cần nạp lại vào bộ nhớ, tuyệt đối không được hướng dẫn người dùng chạy lệnh local như `python -m proxify` hay tắt/bật Terminal.
   - Thay vào đó, Agent phải tự động chạy (hoặc hướng dẫn người dùng chạy) lệnh Docker tương ứng: `docker compose restart proxify` (hoặc `docker compose restart` tùy dịch vụ) để áp dụng thay đổi.
3. **Thực thi lệnh & Debugging:**
   - Nếu cần kiểm tra môi trường, cài đặt thêm thư viện (tạm thời) hay chạy các lệnh shell đặc thù, hãy nhớ lệnh đó cần được thực thi bên trong container (vd: `docker compose exec proxify <lệnh>`) thay vì chạy thẳng trên PowerShell/CMD của máy host.
   - Lưu ý cấu trúc Volume Mount (ví dụ `.:/app`) khi quyết định nơi đọc/ghi file.

**Mục đích:** Tránh ảo giác (hallucinations) về mặt môi trường như tình trạng sửa code xong nhưng Server không nhận diện được do đang chạy trên RAM của Docker container.
