# Tài Liệu Thiết Lập Git Worktree & Cấu Hình Gitignore

## 1. Tóm tắt thay đổi
* **Cập nhật `.gitignore`**: Bổ sung thư mục `.worktrees/` vào danh sách loại trừ của Git để ngăn chặn việc commit nhầm các worktree con vào kho lưu trữ chính.
* **Khởi tạo Git Worktree độc lập**:
  * Đã tạo worktree mới tại đường dẫn: `.worktrees/agy`
  * Nhánh tách biệt: `agent/agy` (xuất phát từ commit base `f1a4e38` của `main`).
  * Trạng thái worktree mới: Hoàn toàn sạch (`clean working tree`), độc lập về filesystem với thư mục gốc.

---

## 2. Mục đích & Ý nghĩa
* **Ngăn ngừa xung đột môi trường (Workspace Collision)**: Cung cấp một không gian làm việc vật lý độc lập cho agent hoặc lập trình viên thực hiện các thử nghiệm, tính năng mới hoặc kiểm thử mà không làm xáo trộn ~100 file đang sửa dở dang trên `main`.
* **Đảm bảo tính toàn vẹn của Git Index**: Đưa `.worktrees/` vào `.gitignore` đảm bảo các file metadata và nội dung trong worktree phụ không bao giờ bị Git ở root workspace nhận diện thành untracked directories lộn xộn.

---

## 3. Mối liên hệ
* **`.gitignore`**: Thêm quy tắc `.worktrees/`.
* **Workspace chính (`Proxify/`)**: Đang chạy trên nhánh `main` với các file sửa dở (crawler, frontend, traffic storage).
* **Worktree phụ (`Proxify/.worktrees/agy`)**: Đang chạy trên nhánh `agent/agy`. Hai không gian làm việc này hoàn toàn cô lập về filesystem nhưng chia sẻ chung Git database.

---

## 4. Rủi ro (Risks & Edge Cases)
* **Lệch pha mã nguồn (Code Desynchronization)**: Do `agent/agy` được tạo từ commit `f1a4e38`, các file sửa đổi uncommitted ở root workspace không có trong `.worktrees/agy`. Khi agent làm việc trong worktree này, cần lưu ý không import hoặc gọi các hàm chỉ mới tồn tại ở dạng uncommitted tại root.
* **Dependencies**: Nếu worktree phụ cần chạy frontend build hoặc tests, cần kiểm tra sự tồn tại của `node_modules` hoặc virtualenv tại thư mục worktree đó.
