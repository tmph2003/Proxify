# Tài liệu: `json_parse.js` (Thư mục platforms/zalo/js)

## 1. Tóm tắt tổng quan
File `json_parse.js` là một script Client-side cực kỳ mạnh mẽ dùng để tiêm vào trang Zalo Web. Chức năng chính của nó là ghi đè hàm `JSON.parse` nhằm bắt lén dữ liệu luân chuyển, mở khóa các tính năng UI ẩn (như hiển thị danh sách thành viên ẩn) và thâm nhập vào bộ máy Webpack của Zalo để ép buộc ứng dụng gọi các API lấy thông tin (Pagination, User Profiles) mà không cần thao tác thủ công từ người dùng.

## 2. Mục đích & Ý nghĩa
- Cho phép Proxify tự động trích xuất các luồng dữ liệu liên quan đến nhóm chat, hồ sơ cá nhân và danh sách thành viên trong chế độ thời gian thực.
- Vượt qua các rào cản từ giao diện UI của Zalo (như tính năng nhóm tắt xem thành viên, khóa admin) bằng cách sửa đổi trực tiếp dữ liệu JSON Object ngay khi nó được parse trước khi đưa vào luồng Render của React/Vue.
- Sử dụng cơ chế thâm nhập Webpack (`webpackJsonp`) để gọi trực tiếp các API Zalo được định nghĩa sẵn, giúp giảm rủi ro bị khóa (block) do tự ý giả mạo request thủ công.

## 3. Mối liên hệ
- Tương tác với hệ sinh thái Frontend của Zalo (Webpack chunks).
- Đẩy dữ liệu ra ngoài qua endpoint HTTP ảo của máy chủ Proxy (`https://chat.zalo.me/api/capture_dump`).
- Có liên kết với bot nội bộ (`bot.py`) qua các biến được bộc lộ (expose) trên object Window (`window.__proxify_fetchFullGroupInfo`) nhằm nhận lệnh cào (crawl) dữ liệu nhóm một cách triệt để.

## 4. Rủi ro (Risks & Edge Cases)
- **Hiệu năng hệ thống (Performance Overhead):** Hook hàm `JSON.parse` là một thao tác cực kỳ nặng (chi phí O(N) theo số lượng object JSON sinh ra), có thể làm ứng dụng Zalo bị lag nếu quá trình đệ quy `unlockAdmin` chậm trễ.
- **Cập nhật kiến trúc Zalo:** Kỹ thuật chèn ID `probe` vào Webpack sẽ hoàn toàn hỏng nếu Zalo thay thế Webpack bằng một bundler khác (như Vite/Rollup), hoặc họ mã hoá toàn bộ khóa (key) của object (`isGroup`, `groupId` => `a`, `b`).
- **Rate Limit:** Vòng lặp `while(page <= maxPages)` tải hàng loạt danh sách thành viên hoặc hồ sơ có thể kích hoạt hệ thống bảo mật chống DDoS hoặc Spam của Zalo, dẫn đến việc IP bị cấm tạm thời.

## 5. Chi tiết các Class và Hàm
- **`IIFE`**: Chứa cờ `g.__zalo_json_hooked` chặn duplicate hook, lưu các reference gốc là `_origParse` và `_origStringify`.
- **`sendToProxy(data, tag)`**: Đóng gói Object dữ liệu thành chuỗi thông qua `_origStringify`, và gửi lệnh `fetch` POST lên hệ thống proxy để lưu.
- **`normalizeId(val)`**: Loại bỏ các tiền tố không chuẩn từ ID người dùng hoặc nhóm (như `uid:`, `g`, `u`, hoặc các đuôi `_`). 
- **`pickUserId(raw)`**: Trích xuất chuỗi định danh người dùng từ một dictionary bất kỳ (dự phòng trường hợp Zalo đổi tên key như `uidTo`, `memberId`, `user_id`, v.v.).
- **`getWebpackRequire()`**: Bơm một mảng rỗng (`probeId`) vào cấu trúc `webpackJsonp` của giao diện Zalo để đánh cắp hàm loader cốt lõi `__webpack_require__`.
- **`readModuleExport(requireFn, moduleId)`** và **`findWebpackExport(requireFn, predicate)`**: Hàm tiện ích để quét (scan) bộ đệm cache của Webpack nhằm truy xuất những class/service đặc thù của Zalo dựa trên module ID cố định (như `fBUP`) hoặc quét mù (dựa trên tên hàm `getGroupInfoV2`).
- **`resolveGroupRuntime()`**: Tìm kiếm và bọc lại Service liên quan đến xử lý Nhóm (Group Service) và hàm giải mã (Decoder) của nó.
- **`resolveProfileService()`**: Tìm kiếm Module lấy danh sách thông tin tài khoản người dùng từ ID.
- **`unwrapRuntimeResponse(raw, decoder)`**: Đọc luồng dữ liệu trả về từ các hàm API nội bộ của Webpack, giải mã (decrypt) nếu cần thiết, và loại bỏ wrapper báo lỗi của Zalo.
- **`postFromPage(urls, body)`**: Khi Webpack API thất bại, hàm này đóng vai trò Fallback, gọi trực tiếp các API HTTP lấy danh sách nhóm/thành viên (ví dụ `tt-chat2-wpa.chat.zalo.me/api/...`).
- **`fetchFullGroupInfo(groupId)`** *(biến toàn cục `window.__proxify_fetchFullGroupInfo`)*: 
  - Khởi chạy một quy trình phân trang (Pagination) để gọi `getGroupInfoV2` thu thập toàn bộ ID thành viên và hồ sơ.
  - Sau khi kết thúc, nếu thấy hụt số lượng so với `totalMember`, tự động kích hoạt `fetchHiddenMembersHTTP` để bù trừ.
  - Khởi chạy `fetchUserProfiles` cho các ID vừa lấy được.
- **`fetchHiddenMembersHTTP(groupId)`**: Gửi POST request ẩn lấy thành viên của nhóm đang bị vô hiệu hóa tính năng xem danh sách thành viên.
- **`fetchUserProfiles(userIds)`**: Chia hàng nghìn ID người dùng thành các mẻ (batch) 50 ID. Thu thập hồ sơ thông qua 4 cơ chế xếp tầng: (1) Cache Webpack cục bộ, (2) Lấy từ bạn bè qua `getProfileFriendByIds`, (3) Lấy từ người lạ qua API `getprofiles/v2`, (4) Lấy tài khoản doanh nghiệp (OA) qua `get-bizacc`.
- **`isGroupData(obj)`** và **`needsFullFetch(obj)`**: Logic xác định xem Object JSON đang xét có phải là dữ liệu về group hay không và kiểm tra các dấu hiệu thiếu hụt thành viên để kích hoạt cào (fetch) đầy đủ.
- **`JSON.parse(str) (Ghi đè)`**:
  - Gọi hàm parse JSON chuẩn.
  - Sử dụng hàm đệ quy **`unlockAdmin(obj)`** để quét đệ quy mọi cấp bậc object, biến các khóa `hideMembers`, `lockViewMember` thành `0` / `false` và giả lập đặc quyền `isAdmin = true`, giúp UI của Zalo Web vô tình bị đánh lừa và mở khoá các tính năng quản trị và hiển thị danh sách ẩn.
  - Định vị các ID nhóm hiện hành và chuyển tiếp dữ liệu quý giá về máy chủ Proxy. (Ghi chú: Việc tự động fetch profile trong nền lúc lướt web đã bị tắt để tránh gọi API rác).
