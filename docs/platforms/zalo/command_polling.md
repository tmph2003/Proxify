# Hệ thống Command Polling cho Zalo JS Hooks

## Tóm tắt thay đổi
Thêm hệ thống "pending commands" cho phép dashboard gửi lệnh đến JS hooks đang chạy trên trình duyệt Chrome của người dùng thông qua proxy, không cần Bot hay DevTools.

## Mục đích & Ý nghĩa
- Trước đây, để lấy toàn bộ thành viên nhóm Zalo, người dùng phải:
  - Chạy Bot Playwright (phải quét QR lại, cửa sổ có thể không hiện trên RDP)
  - Hoặc gõ lệnh thủ công trong DevTools (`__proxify_fetchFullGroupInfo('groupId')`)
- Với hệ thống mới, người dùng chỉ cần:
  1. Mở `chat.zalo.me` trên Chrome đang proxy (đã đăng nhập sẵn)
  2. Bấm nút "Lấy toàn bộ thành viên" trên dashboard `/zalo`
  3. JS hooks tự động nhận lệnh và thực thi

## Kiến trúc
```
Dashboard (/zalo)                 Proxy (mitmproxy)              Chrome (chat.zalo.me)
     │                                  │                              │
     │  POST /api/zalo/commands/        │                              │
     │  fetch_members {group_id}        │                              │
     │──────────────────────────────>   │                              │
     │                                  │  (lưu vào _pending_commands) │
     │                                  │                              │
     │                                  │  GET /api/zalo/commands/     │
     │                                  │  pending (mỗi 5s)           │
     │                                  │<─────────────────────────────│
     │                                  │                              │
     │                                  │  [{action: fetch_members,    │
     │                                  │    group_id: "..."}]         │
     │                                  │─────────────────────────────>│
     │                                  │                              │
     │                                  │  JS hooks gọi               │
     │                                  │  fetchFullGroupInfo(groupId) │
     │                                  │                              │
     │                                  │  POST /api/capture_dump      │
     │                                  │<─────────────────────────────│
     │                                  │  (dữ liệu chảy về DB)       │
```

## Mối liên hệ
- **`proxify/plugins/zalo.py`**: Thêm `_pending_commands` list, 2 API endpoints (`/api/zalo/commands/pending`, `/api/zalo/commands/fetch_members`)
- **`proxify/platforms/zalo/extractor.py`**: Thêm intercept cho `/api/zalo/commands/pending` trong `handle_capture_dump()` — forward request từ `chat.zalo.me` về dashboard
- **`proxify/platforms/zalo/js/json_parse.js`**: Thêm command polling loop (5s interval) — poll lệnh chờ và thực thi `fetchFullGroupInfo`
- **`proxify/ui/static/js/zalo.js`**: Đổi `rescanGroup()` để gọi `/api/zalo/commands/fetch_members` thay vì `/api/zalo/scan`

## Rủi ro (Risks & Edge Cases)
- **Race condition**: Nếu nhiều tab `chat.zalo.me` cùng poll, chỉ tab đầu tiên nhận lệnh (commands bị clear sau khi poll). Đây là hành vi mong muốn.
- **Latency**: Có độ trễ tối đa 5 giây giữa khi bấm nút và khi lệnh được thực thi. Chấp nhận được.
- **Security**: API `/api/zalo/commands/pending` không có authentication. Trong môi trường local, đây không phải vấn đề.
- **Proxy dependency**: JS hooks poll qua `https://chat.zalo.me/api/zalo/commands/pending` — request này được mitmproxy intercept và forward về dashboard. Nếu proxy không chạy, polling sẽ fail silently.
