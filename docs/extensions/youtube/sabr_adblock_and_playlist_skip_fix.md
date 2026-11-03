# YouTube SABR AdBlock & Playlist Skip Fix — v7 (Watchdog JS Cleanup)

## Tóm tắt thay đổi

**v7** hoàn tất chiến lược "zero-touch server-side" bằng cách **xóa toàn bộ monkey-patches** khỏi `YOUTUBE_WATCHDOG_JS`. Giữ lại chỉ:

1. **Anti-AFK Shield** (visibility override, LACT freshness, mousemove dispatch)
2. **Ad fast-forward** (`.ad-showing` → `video.currentTime = video.duration`)
3. **AFK dialog dismiss** (youThereRenderer, enforcement dialogs)
4. **ServiceWorker unregistration** (prevent stale cache)
5. **`google_ad_status=1` spoof** (anti-adblock detection bypass)

### Đã xóa (monkey-patches gây lỗi):
- ❌ `HTMLDivElement.prototype.addEventListener` override
- ❌ `Promise.prototype.then` proxy (filter `onAbnormalityDetected`)
- ❌ `JSON.stringify` proxy (inject `params: "8AUB"`, `"YAHI"`, `adType`, `clientScreen`)
- ❌ `Map.prototype.has` proxy (trigger `markSabrStall()`)
- ❌ `Array.prototype.push` proxy (trigger `markSabrStall()` on Uint8Array)
- ❌ `reconcileSabrPlayback()` function + `MutationObserver`
- ❌ `loadVideoById()` calls
- ❌ `getPlayerStateSnapshot()`, `isZeroBufferStall()`, `markSabrStall()`
- ❌ Toàn bộ biến `sabrStrategies`, `sabrQueue`, `activeSabrMode`, `sabrReloadFlag`, `lastSabrVid`, `sabrAttempts`

## Mục đích & Ý nghĩa

### Root cause analysis

Lỗi 282054944 và auto-skip playlist do **monkey-patches client-side** gây ra:

1. **`JSON.stringify` proxy** thay đổi nội dung player API requests gửi đến YouTube:
   - Inject `params: "8AUB"` / `"YAHI"` → YouTube server detect bất thường
   - Inject `adType: "AD_TYPE_INSTREAM"` → SABR consistency check fail
   - Inject `clientScreen: "CHANNEL"` → Player config mismatch
   - Append `#reloadxhr` vào referer → Server detect proxy/tampering

2. **`Promise.prototype.then` proxy** filter callback `onAbnormalityDetected`:
   - Khi server-side đã zero-touch (giữ nguyên ad data), việc filter callback này không cần thiết
   - Nhưng proxy hàm native gây side-effects không lường trước cho hàng trăm promises khác

3. **`reconcileSabrPlayback()` + `MutationObserver`**:
   - Chạy trên MỌI DOM mutation
   - Gọi `loadVideoById()` → reload video → YouTube API call mới → có thể trigger error

4. **`Map.prototype.has` + `Array.prototype.push` proxies**:
   - Ảnh hưởng TOÀN BỘ Map/Array operations trong browser
   - Trigger `markSabrStall()` sai lúc → cascade reload

### Tại sao user phải tắt Chrome

YouTube là SPA (Single Page Application). Monkey-patches persist trong memory suốt session. Khi code mới được deploy nhưng user chưa tắt Chrome, các patches cũ vẫn active → vẫn lỗi.

### Chiến lược đúng

| Layer | Strategy | What |
|-------|----------|------|
| Server - Player API | `neutralize_afk_only()` | Chỉ xóa AFK keys |
| Server - Other APIs | `neutralize_afk_only()` | Chỉ xóa AFK keys |
| Server - HTML `ytInitialPlayerResponse` | `neutralize_afk_only()` | Chỉ xóa AFK keys |
| Server - HTML `ytInitialData` | `clean_youtube_json_data()` | Xóa in-feed ads (homepage) |
| Server - Ad network requests | **Allow through** | Không block 204 |
| Client - Watchdog JS | **Minimal** | Anti-AFK + ad fast-forward only |
| Client - DoubleClick bait | Active | `google_ad_status=1` + `/pagead/id` XSSI |

## Mối liên hệ

- **`crates/ext-youtube/src/lib.rs`**: File chính chứa `YOUTUBE_WATCHDOG_JS` const (lines 86-162)
- **`mutate_response()`**: Server-side response processing
- **`strip_youtube_ads()`**: HTML ad processing
- **`is_youtube_ad_request()`**: Always returns `false` (disabled)
- **Tests**: `tests/e2e_extension_tests.rs`, unit tests trong `lib.rs`

## Rủi ro (Risks & Edge Cases)

1. **Ads sẽ hiển thị**: Vì server-side không strip ad data và network requests không bị block, ads sẽ load bình thường. Watchdog JS chỉ fast-forward khi `.ad-showing` class xuất hiện. Nếu YouTube thay đổi class name → ads sẽ play đầy đủ.

2. **Anti-adblock detection**: `google_ad_status=1` spoof có thể bị YouTube detect trong tương lai. Nếu vậy, cần strategy mới.

3. **AFK dialog text changes**: Dialog dismiss dựa vào text matching ("tạm dừng", "paused", etc.). Nếu YouTube đổi text → không auto-dismiss.

4. **Performance**: Watchdog JS giờ rất nhẹ — chỉ có `setInterval` 400ms cho `checkAdsAndAfk` và 5000ms cho `keepLactFresh`. Không có heavy proxying hay MutationObserver.

## v7.1 — Fix search dropdown không đóng được

### Vấn đề
`window.addEventListener("blur", ...)` với `e.stopImmediatePropagation()` chặn TẤT CẢ blur events ở capture phase — bao gồm cả blur của search input box. YouTube dùng blur event để đóng search dropdown → dropdown không đóng khi click ra ngoài.

### Fix
Chỉ chặn blur khi target là `window` hoặc `document` (tab-level blur cho AFK), cho phép element-level blur pass through:
```js
window.addEventListener("blur", function(e){
    if(e.target === window || e.target === document) {
        e.stopImmediatePropagation();
    }
}, true);
```
