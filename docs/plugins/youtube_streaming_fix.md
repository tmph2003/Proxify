# Fix: YouTube Load Mãi Không Xong

## Tóm tắt thay đổi

1. **`backend/proxify/server.py`**: Tách YouTube plugin registration — `googlevideo.com` và `doubleclick.net` đăng ký là **observer** (chỉ block ad requests), không phải **mutator** (modify response body).
2. **`backend/proxify/core/router.py`**: Thêm `_STREAM_DOMAINS` constant và step 5 trong `route_responseheaders` để stream unconditionally cho `googlevideo.com`.

## Mục đích & Ý nghĩa

### Triệu chứng
YouTube video load mãi, buffer liên tục, không phát được.

### Nguyên nhân gốc (Root Cause)

**2 lỗi kết hợp gây ra 1 hiệu ứng chết người:**

#### Lỗi 1: `googlevideo.com` đăng ký sai role
Trong `server.py`, YouTubePlugin được register as **mutator** cho TẤT CẢ `target_domains` — bao gồm `googlevideo.com` (YouTube video CDN).

```python
# ❌ SAI — googlevideo.com là CDN video, không cần modify response
for domain in yt_plugin.target_domains:
    router._insert(domain, yt_plugin, True)  # is_mutator=True
```

Trong Router V2, mutators được **await tuần tự** trong `route_response`. Mitmproxy PHẢI buffer toàn bộ response body trước khi gọi `response()` hook cho flows không có `stream=True`.

#### Lỗi 2: YouTube video bypass tất cả streaming rules
YouTube video từ `googlevideo.com` dùng:
- Content-type: `application/octet-stream` (KHÔNG phải `video/*`) → **miss step 1**
- Chunked transfer encoding: **KHÔNG có `content-length` header** → `int("0")` = 0 → **miss step 2** (>5MB check)
- Không phải image/font → **miss step 3**
- URL path: `/videoplayback` (không phải static extension) → **miss step 4**

**Kết quả:** Mitmproxy cố buffer toàn bộ video stream (có thể 100+ MB) vào RAM → timeout/hang → YouTube không load được.

### Fix

```python
# ✅ ĐÚNG — tách role theo mục đích thực tế
_yt_mutator_domains = {"youtube.com", "youtubei"}  # cần modify body
_yt_observer_domains = {"googlevideo.com", "doubleclick.net"}  # chỉ cần block requests

for domain in _yt_mutator_domains:
    router._insert(domain, yt_plugin, True)   # mutator
for domain in _yt_observer_domains:
    router._insert(domain, yt_plugin, False)   # observer only
```

Và thêm domain-based streaming:
```python
_STREAM_DOMAINS = ("googlevideo.com",)

# Step 5 trong route_responseheaders
host = flow.request.pretty_host
if any(d in host for d in _STREAM_DOMAINS):
    flow.response.stream = True
    return
```

## Mối liên hệ

| File/Module | Ảnh hưởng |
|---|---|
| `backend/proxify/server.py` | Sửa YouTube plugin registration |
| `backend/proxify/core/router.py` | Thêm `_STREAM_DOMAINS` và step 5 |
| `backend/proxify/plugins/youtube.py` | Không sửa — `on_response` đã có fast-skip cho non-API urls |
| `backend/proxify/utils/youtube_utils.py` | Không sửa — `is_youtube_ad_request` vẫn hoạt động cho ad blocking |

## Rủi ro (Risks & Edge Cases)

1. **Ad request blocking vẫn hoạt động**: `on_request` vẫn được gọi cho `googlevideo.com` (observer) → `is_youtube_ad_request` → `flow.kill()` vẫn block ads.

2. **`strip_youtube_ads` không ảnh hưởng**: Function này chỉ modify body khi `is_api` hoặc `is_watch_page` → chỉ match `youtube.com`, không match `googlevideo.com`.

3. **Nếu YouTube thay đổi CDN domain**: Cần cập nhật `_STREAM_DOMAINS`. Tuy nhiên `googlevideo.com` đã ổn định từ nhiều năm.

4. **`doubleclick.net` cũng chuyển sang observer**: Trước đây là mutator nhưng YouTubePlugin không modify response từ domain này — chỉ block requests. Chuyển sang observer là hợp lý hơn.
