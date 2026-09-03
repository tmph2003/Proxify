# Khắc Phục Lỗi Mất State Cào Khi Refresh Trang (F5)

## 1. Tóm tắt thay đổi
* **Hook `useFacebook.ts` (`frontend/src/hooks/useFacebook.ts`)**:
  * **Đồng bộ hai chiều trạng thái `crawling`**: Trong hàm `checkStatus()`, khi API `/facebook/crawl_status` trả về `groupObj.status === 'running'` hoặc `'fetching_template'`, hệ thống lập tức gọi `setCrawling(true)` và lưu cờ `fb_is_crawling = true` vào `sessionStorage`. Ngược lại, khi trạng thái là `idle`, `error`, hoặc `blocked`, cờ này được gỡ bỏ.
  * **Khởi tạo State không giật (Zero-flicker State Init)**:
    * `crawling` khởi tạo từ `sessionStorage.getItem('fb_is_crawling') === 'true'`.
    * `statusText` và `statusColor` khởi tạo từ `sessionStorage`.
  * **Tự động kích hoạt lại Polling & Auto-reload**: Khi `crawling` được khôi phục thành `true` sau khi F5, các `useEffect` tự động kích hoạt lại chu kỳ thăm dò trạng thái mỗi 1 giây và tự động tải dữ liệu bài viết mới mỗi 5 giây (`loadData()`).
* **Trang `Facebook.tsx` (`frontend/src/pages/Facebook.tsx`)**:
  * Tự động lưu `groupId` vào `localStorage` ngay khi người dùng gõ phím (`onChange`), đảm bảo không bị trống Group ID khi tải lại trang.
  * Nút hành động hiển thị chuẩn xác: nếu `crawling === true` hiển thị nút màu đỏ **"🛑 Dừng thu thập"**, thay vì bị quay về nút xanh "Bắt đầu thu thập".
* **Đóng gói & Triển khai**:
  * Đã chạy `npm run build` thành công và copy bundle mới vào thư mục tĩnh của container Nginx `proxify_ui`.

---

## 2. Mục đích & Ý nghĩa
* **Nguyên nhân gốc rễ (Root Cause)**:
  * Trước đây, `crawling` state chỉ là một React local state khởi tạo bằng `false`.
  * Khi người dùng nhấn F5 (refresh trình duyệt), React unmount và mount lại $\rightarrow$ `crawling` trở về `false`.
  * Trong `checkStatus()`, code cũ chỉ có logic ngắt cào: `if (groupObj.status === 'idle' || groupObj.status === 'error') setCrawling(false);`, nhưng **hoàn toàn thiếu logic bật lại `setCrawling(true)`** khi backend đang chạy (`running`).
  * Hệ quả: Dù backend đang cào đến trang 5, giao diện vẫn hiển thị nút xanh "Bắt đầu thu thập", cơ chế auto-reload bảng dữ liệu mỗi 5s bị tắt, khiến người dùng lầm tưởng tiến trình cào đã bị mất hoặc bị hủy.
* **Ý nghĩa**: Giúp trải nghiệm liền mạch 100%. Dù người dùng đóng tab, mở lại hoặc refresh liên tục, giao diện vẫn bám sát tiến độ của backend theo thời gian thực.

---

## 3. Mối liên hệ
* `frontend/src/hooks/useFacebook.ts`: Quản lý toàn bộ vòng đời polling trạng thái từ Backend API.
* `frontend/src/pages/Facebook.tsx`: Hiển thị nút điều khiển và hộp thông báo trạng thái.
* `backend/proxify/platforms/facebook/api.py`: Endpoint `/facebook/crawl_status` cung cấp `group_crawl_state`.

---

## 4. Rủi ro (Risks & Edge Cases)
* **Session Storage phân mảnh giữa các Tab**: `sessionStorage` gắn liền với từng tab duyệt web. Nếu người dùng mở một tab mới tinh và vào `http://localhost:8888/facebook`, tab mới sẽ đọc `crawling = false` ban đầu, nhưng ngay sau 100ms khi `checkStatus()` gọi API backend thành công, nó sẽ tự động nhận diện backend đang `running` và bật `setCrawling(true)` ngay lập tức.
