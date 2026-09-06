# Fix: Static Asset Streaming — Proxy Làm Mạng Chậm

## Tóm tắt thay đổi

Thêm logic streaming cho static assets (images, fonts, source maps) vào `ProxyRouter.route_responseheaders()`. Trước đây router V2 chỉ stream `video/*`, `audio/*` và file > 5MB — tất cả file tĩnh khác (`.png`, `.jpg`, `.woff2`, `.svg`, ...) bị buffer toàn bộ trước khi forward cho browser.

## Mục đích & Ý nghĩa

### Vấn đề
Khi bật proxy, mạng bị chậm rõ rệt vì mitmproxy hoạt động theo mô hình **store-and-forward**:
1. Browser gửi request qua proxy
2. Proxy tải **TOÀN BỘ response body** về RAM
3. Sau khi tải xong, proxy mới forward cho browser

Với **streaming** (`flow.response.stream = True`), proxy forward từng chunk ngay khi nhận được → latency gần bằng không.

**Ước tính tác động:** Một trang web điển hình tải ~50 static files (images, fonts, CSS, JS). Mỗi file thêm ~50-200ms latency khi buffer → tổng cộng thêm **2-5 giây** cho page load.

### Lịch sử
Code V1 (`capture_addon.py`) **đã có** streaming cho `DEFAULT_IGNORE_EXTENSIONS` nhưng khi migrate sang V2 Router architecture, logic này bị **mất** do không được port sang.

### Quyết định thiết kế

| Extension | Stream? | Lý do |
|---|---|---|
| `.png`, `.jpg`, `.webp`, `.svg`, `.gif`, `.ico`, `.avif` | ✅ Có | Không plugin nào modify ảnh |
| `.woff`, `.woff2`, `.ttf`, `.eot`, `.otf` | ✅ Có | Không plugin nào modify font |
| `.mp4`, `.mp3`, `.wav`, `.webm`, `.ogg` | ✅ Có | Đã có check content-type, thêm extension check làm fallback |
| `.map` | ✅ Có | Source maps, browser dev tools only |
| `.css` | ❌ Không | Plugin có thể cần modify CSS trong tương lai |
| `.js` | ❌ Không | **ZaloPlugin** cần `modify_zalo_response()` để inject JS hooks vào `.js` files của Zalo |

Ngoài extension, còn check **content-type**: `image/*`, `font/*`, `application/font-*` cũng được stream.

## Thay đổi cụ thể

**File:** `backend/proxify/core/router.py`

1. Thêm constants:
   - `_STREAM_EXTENSIONS`: tuple các extension an toàn để stream
   - `_STREAM_CONTENT_TYPES`: tuple các content-type prefix an toàn để stream

2. Sửa `route_responseheaders()`: Thêm 2 check mới (step 3 và 4) trước khi delegate cho observers/mutators:
   - Step 3: Stream theo content-type (images, fonts)
   - Step 4: Stream theo URL extension

## Mối liên hệ

| File/Module | Ảnh hưởng |
|---|---|
| `backend/proxify/core/router.py` | File được sửa — thêm streaming logic |
| `backend/proxify/capture_addon.py` | Code V1 gốc — logic streaming đã có ở đây nhưng dead code trong V2 |
| `backend/proxify/plugins/zalo.py` | ZaloPlugin — **KHÔNG bị ảnh hưởng** vì `.js` không được stream |
| `backend/proxify/core/listeners.py` | `DashboardBroadcaster` — request streamed sẽ có `response_size = 0` trên dashboard (behavior đã có từ V1) |

## Rủi ro (Risks & Edge Cases)

1. **Dashboard response_size = 0 cho streamed files**: Khi stream, mitmproxy không buffer body → `flow.response.content` = `b""` → `response_size = 0` trên dashboard. Đây là trade-off chấp nhận được vì dashboard chỉ cần hiển thị API/XHR requests.

2. **Plugin mới modify static assets**: Nếu tương lai có plugin cần modify response body của image/font, phải thêm extension vào exclusion list. Hiện tại không có plugin nào cần điều này.

3. **`.css` và `.js` vẫn bị buffer**: Đây là quyết định an toàn cho ZaloPlugin. Nếu muốn tối ưu thêm, có thể stream `.css`/`.js` CHỈ cho domains không có mutator đăng ký.

4. **HTTP/2 vẫn tắt** (`http2=False` trong `server.py`): Đây là bottleneck thứ hai nhưng không sửa ở đây vì có thể gây compatibility issues với một số websites. Cần test kỹ trước khi bật.
