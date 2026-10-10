# Tài Liệu Kỹ Thuật: Khắc Phục Lỗi Mất Thanh Tìm Kiếm YouTube Do Xung Đột Từ Khóa "masthead"

## 1. Tóm tắt thay đổi

- **File sửa đổi 1:** `backend/proxify/utils/youtube_utils.py`
  - Loại bỏ từ khóa generic `"masthead"` khỏi `AD_CONFIG_KEYS`.
  - Thay thế bằng từ khóa quảng cáo chuẩn của YouTube: `"primetimeMastheadRenderer"`.
- **File sửa đổi 2:** `backend/tests/test_youtube_utils.py`
  - Cập nhật test case `test_strip_youtube_ads` để xác minh khử `"primetimeMastheadRenderer"`.
  - Bổ sung kiểm thử hồi quy (regression test): Đảm bảo các phần tử giao diện người dùng quan trọng như `<ytd-masthead id="masthead" slot="masthead">` và thanh tìm kiếm `#search-input` tuyệt đối không bị Proxy can thiệp hay sửa đổi.

---

## 2. Mục đích & Ý nghĩa

### Triệu chứng
Người dùng báo cáo: *"Mất nút tìm kiếm ở YouTube rồi"* và gửi kèm ảnh chụp màn hình cho thấy toàn bộ thanh điều hướng trên cùng (Top Navigation Bar) của YouTube bao gồm: Logo YouTube, Ô tìm kiếm, Nút tìm kiếm bằng giọng nói, Nút tạo video, Chuông thông báo và Avatar tài khoản hoàn toàn biến mất (vùng màu đen trống rỗng).

### Nguyên nhân gốc rễ (Root Cause)
1. **Trùng tên thành phần UI cốt lõi:**
   - Trong kiến trúc Web Components / Polymer của YouTube, toàn bộ thanh header phía trên cùng là một Custom Element được định nghĩa trong mã HTML:
     ```html
     <ytd-masthead id="masthead" logo-type="YOUTUBE_LOGO" slot="masthead" class="shell">
         <div id="search-container" class="ytd-searchbox-spt" slot="search-container"></div>
         <div id="search-input" class="ytd-searchbox-spt" slot="search-input">...</div>
     </ytd-masthead>
     ```
   - Shadow DOM của `<ytd-app>` sử dụng thẻ `<slot name="masthead"></slot>` để đón nhận và hiển thị thanh header này lên màn hình.
2. **Hậu quả của việc dùng từ khóa quá rộng:**
   - Trong bản cập nhật trước, từ khóa `"masthead"` được đưa vào danh mục `AD_CONFIG_KEYS` với mục đích chặn các banner quảng cáo đầu trang (Masthead Ads).
   - Hàm `strip_youtube_ads` thực hiện thay thế chuỗi `"masthead"` thành `"masthead_BLOCKED"`.
   - Điều này vô tình biến `id="masthead"` thành `id="masthead_BLOCKED"` và `slot="masthead"` thành `slot="masthead_BLOCKED"`.
   - Kết quả: Thẻ `<slot name="masthead">` của Shadow DOM không còn khớp với `slot="masthead_BLOCKED"`. Trình duyệt lập tức loại bỏ toàn bộ khối header ra khỏi cây hiển thị render, làm mất thanh tìm kiếm và toàn bộ nút điều hướng!

### Giải pháp kiến trúc
- Phân định rạch ròi giữa **Thành phần giao diện (UI Component)** và **Quảng cáo (Ad Renderer)**.
- Từ khóa quảng cáo đầu trang thực sự của YouTube trong API và JSON là `primetimeMastheadRenderer` hoặc `statementBannerRenderer`, **tuyệt đối không phải chuỗi generic `masthead`**.
- Loại bỏ triệt để `"masthead"` khỏi danh mục chặn giúp thanh tìm kiếm và thanh điều hướng phục hồi 100% vị trí và chức năng.

---

## 3. Mối liên hệ

| Module / File | Vai trò liên kết |
|---|---|
| `backend/proxify/utils/youtube_utils.py` | Quản lý danh mục `AD_CONFIG_KEYS`, loại bỏ token gây xung đột |
| `backend/proxify/plugins/youtube.py` | Gọi `strip_youtube_ads` trên luồng HTML trang chủ `/` và trang `/watch` |
| `backend/tests/test_youtube_utils.py` | Chứa regression test bảo vệ cấu trúc `<ytd-masthead>` |

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Quảng cáo banner đầu trang (Masthead Ad) có quay trở lại không?**
   - Không. Các chiến dịch quảng cáo Masthead của YouTube (như banner giới thiệu phim, game, điện thoại) được phân phối qua các renderer chuyên dụng: `primetimeMastheadRenderer`, `adSlotRenderer`, và `statementBannerRenderer`.
   - Tất cả các renderer này vẫn nằm đầy đủ trong `AD_CONFIG_KEYS` và tiếp tục bị chặn triệt để.
2. **Xung đột từ khóa trong tương lai:**
   - *Nguyên tắc bảo vệ:* Không bao giờ thêm các danh từ đơn (generic nouns như `header`, `nav`, `masthead`, `bar`) vào danh sách thay thế chuỗi toàn cục. Chỉ sử dụng các định danh chuyên biệt có hậu tố `Renderer`, `Config`, `Params` hoặc các khóa đặc thù như `adPlacements`, `adSlots`.
