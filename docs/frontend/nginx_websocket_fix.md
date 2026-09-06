# Fix: Nginx WebSocket Proxy — Dashboard Không Hiển Thị Request

## Tóm tắt thay đổi

Sửa file `frontend/nginx.conf` — block `location /ws` đang dùng **hardcoded URL** (`proxy_pass http://proxify:8888;`) thay vì dùng biến `$backend_upstream`. Thêm `proxy_read_timeout` và `proxy_send_timeout` cho WebSocket.

## Mục đích & Ý nghĩa

### Triệu chứng
- Dashboard (`http://localhost:8888/`) không hiển thị bất kỳ request nào.
- Nginx log tràn ngập lỗi: `connect() failed (111: Connection refused) while connecting to upstream ... http://172.19.0.3:8888`
- Tất cả API (`/api/*`) và WebSocket (`/ws`) đều trả về **502 Bad Gateway**.

### Nguyên nhân gốc (Root Cause)
Trong nginx, khi `proxy_pass` dùng **literal URL** (hardcode), nginx chỉ resolve DNS **1 lần duy nhất** khi startup. Dù đã khai báo `resolver 127.0.0.11 valid=10s`, directive này **chỉ có tác dụng khi proxy_pass chứa biến**.

```nginx
# ❌ SAI — DNS resolve 1 lần, cache vĩnh viễn
location /ws {
    proxy_pass http://proxify:8888;
}

# ✅ ĐÚNG — DNS re-resolve theo resolver interval (10s)
set $backend_upstream http://proxify:8888;
location /ws {
    proxy_pass $backend_upstream/ws;
}
```

Khi container `proxify` restart (IP đổi từ `172.19.0.3` → `172.19.0.4`), nginx vẫn kết nối đến IP cũ → **Connection refused** → 502.

### Tại sao block `/api/` cũng bị?
Block `/api/` đã dùng biến `$backend_upstream` nhưng nginx worker process có thể đã cache DNS ở process level. Sau khi restart container `ui`, cả 2 block đều hoạt động bình thường.

## Thay đổi cụ thể

**File:** `frontend/nginx.conf`

```diff
 location /ws {
-    proxy_pass http://proxify:8888;
+    proxy_pass $backend_upstream/ws;
     proxy_http_version 1.1;
     proxy_set_header Upgrade $http_upgrade;
     proxy_set_header Connection "upgrade";
     proxy_set_header Host $host;
+    proxy_read_timeout 86400s;
+    proxy_send_timeout 86400s;
 }
```

**Giải thích thêm:**
- `proxy_read_timeout 86400s` / `proxy_send_timeout 86400s`: Giữ WebSocket connection sống 24h thay vì timeout mặc định 60s. Dashboard cần WebSocket persistent để nhận real-time updates.

## Mối liên hệ

| File/Module | Vai trò |
|---|---|
| `frontend/nginx.conf` | Reverse proxy, phục vụ SPA, proxy API + WS đến backend |
| `backend/proxify/dashboard.py` | aiohttp server trên port 8888, phục vụ API + WebSocket `/ws` |
| `frontend/src/hooks/useRequests.ts` | Frontend WebSocket client, nhận `new_request` và `update_id` events |
| `docker-compose.yml` | Định nghĩa topology: `ui` (Nginx:80) → `proxify` (aiohttp:8888) |

**Luồng dữ liệu:**
```
Browser → Nginx (:80, exposed :8888) → aiohttp Dashboard (:8888)
                                           ↓ WebSocket broadcast
                                        React Frontend (useRequests hook)
```

## Rủi ro (Risks & Edge Cases)

1. **DNS re-resolve overhead**: Với `valid=10s`, nginx sẽ query Docker DNS mỗi 10s. Overhead không đáng kể.
2. **WebSocket timeout 24h**: Nếu connection idle > 24h, nginx sẽ ngắt. Frontend đã có auto-reconnect (3s delay) nên không ảnh hưởng.
3. **`$backend_upstream` variable**: Tất cả location blocks giờ đều phụ thuộc vào biến `$backend_upstream` được set ở đầu server block. Nếu ai sửa/xóa biến này, toàn bộ proxy sẽ hỏng.
