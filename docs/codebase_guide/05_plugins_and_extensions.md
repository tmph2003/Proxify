# MODULE 5: CÁC PLUGIN BỔ TRỢ (YOUTUBE & ZALO) VÀ TỔNG KẾT HỆ THỐNG

> [!NOTE]
> Thuộc bộ cẩm nang chi tiết mã nguồn Proxify v2.0 Architecture Deep-Dive.  
> [⬅️ Quay lại Module 4: Chrome Extension](./04_chrome_extension.md) | [Quay lại Cẩm nang tổng quan](../CODEBASE_DETAILED_GUIDE.md)

---

## MỤC LỤC MODULE 5
- [5.1. `backend/proxify/plugins/youtube.py` (Chặn quảng cáo YouTube)](#51-backendproxifypluginsyoutubepy)
- [5.2. `backend/proxify/platforms/zalo/` (Bóc tách dữ liệu Zalo Web)](#52-backendproxifyplatformszalo)
- [TỔNG KẾT MỐI LIÊN KẾT GIỮA CÁC MODULE](#tổng-kết-mối-liên-kết-giữa-các-module)

---

<a id="51-backendproxifypluginsyoutubepy"></a>
## 5.1. `backend/proxify/plugins/youtube.py`
Plugin tự động phát hiện và bỏ qua quảng cáo khi xem video trên YouTube qua Proxy.

* **`async def on_request(self, flow)`**:
  * Nhận diện các domain phân phối quảng cáo YouTube (như `youtube.com/api/stats/ads`, `googlevideo.com/videoplayback?adformat=...`).
  * Chủ động trả về phản hồi rỗng 204 No Content để chặn tải video quảng cáo.
* **`async def on_response(self, flow)`**:
  * Khi người dùng tải trang xem video `youtube.com/watch`, tiêm đoạn script JavaScript tự động tua video quảng cáo đến giây cuối cùng và click nút "Bỏ qua quảng cáo" (Skip Ad) ngay lập tức.

---

<a id="52-backendproxifyplatformszalo"></a>
## 5.2. `backend/proxify/platforms/zalo/`
Module chuyên biệt thu thập thông tin nhóm và thành viên trên Zalo Web (`chat.zalo.me`).

* **Tệp `hooks/json_parse.js` & `crypto_subtle.js`**:
  * Zalo sử dụng mã hóa dữ liệu đầu cuối trên Web. Plugin tiêm hook vào hàm `JSON.parse` và `window.crypto.subtle.decrypt` trong trình duyệt của người dùng để sao chép dữ liệu sau khi đã giải mã xong.
* **Class `ZaloDBManager`**:
  * Lưu trữ danh sách thành viên nhóm (Tên, SĐT hiển thị, Quyền hạn Admin/Member) vào bảng `zalo.members` của PostgreSQL.

---

## TỔNG KẾT MỐI LIÊN KẾT GIỮA CÁC MODULE

```
                  ┌───────────────────────────────┐
                  │    Chrome Extension (v3)      │
                  │   - background.js (In-Tab)    │
                  │   - popup.js (CHIPS Cookie)   │
                  │   - content.js (Keep-Alive)   │
                  └──────────────┬────────────────┘
                                 │ HTTP REST (Jobs & Results)
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     aiohttp API (Cổng 8888)                     │
│  ┌─────────────────────────┐       ┌─────────────────────────┐  │
│  │     ExtensionBridge     │◄──────┤     FacebookCrawler     │  │
│  └─────────────────────────┘       └────────────┬────────────┘  │
│                                                 │               │
│                                                 ▼               │
│  ┌─────────────────────────┐       ┌─────────────────────────┐  │
│  │      PostRepository     │◄──────┤      PostExtractor      │  │
│  │   (ON CONFLICT DO UPD)  │       │   (Canonical Post ID)   │  │
│  └────────────┬────────────┘       └─────────────────────────┘  │
└───────────────┼─────────────────────────────────────────────────┘
                │
                ▼ SQL Insert/Upsert
┌─────────────────────────────────────────────────────────────────┐
│                    PostgreSQL 15 (Cổng 5432)                    │
│   Schema core:     raw_payloads, requests                       │
│   Schema facebook: posts, comments, groups                      │
│   Schema zalo:     members, groups                              │
└─────────────────────────────────────────────────────────────────┘
```

---

> [!TIP]
> [⬅️ Quay lại Module 4: Chrome Extension](./04_chrome_extension.md) | [Quay lại Cẩm nang tổng quan](../CODEBASE_DETAILED_GUIDE.md)
