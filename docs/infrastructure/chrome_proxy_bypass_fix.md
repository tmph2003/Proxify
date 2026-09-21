# Fix Chrome Không Gửi Traffic Qua Proxy (Facebook Loading Stuck)

## Tóm tắt thay đổi

Sửa lỗi Chrome không gửi traffic qua proxy `127.0.0.1:8080` dẫn đến Facebook (và các trang khác) bị stuck ở loading screen.

### Thay đổi hệ thống:
1. **Disable WPAD Auto-Detect** — tắt `AutoDetect` trong Internet Settings
2. **Sync WinHTTP proxy** — import proxy config từ WinINet sang WinHTTP
3. **Disable Chrome QUIC** — registry policy `QuicAllowed=0`
4. **Chrome `--proxy-server` flag** — force Chrome sử dụng proxy trực tiếp
5. **Desktop shortcut** — "Chrome (Proxify)" trên Public Desktop

## Mục đích & Ý nghĩa

### Vấn đề
Chrome hiển thị Facebook loading screen (logo + "from Meta") nhưng không tải nội dung. Proxy logs cho thấy **zero traffic** từ Chrome cho Facebook — Chrome bypass proxy hoàn toàn.

### Nguyên nhân gốc (Root Cause)
Windows có nhiều lớp proxy configuration mà Chrome có thể sử dụng:

| Layer | Config | Trạng thái trước fix |
|---|---|---|
| **WinINet** (Internet Settings) | `ProxyEnable=1, ProxyServer=127.0.0.1:8080` | ✅ Đúng |
| **WinHTTP** (`netsh winhttp`) | `Direct access (no proxy server)` | ❌ Không set |
| **DefaultConnectionSettings** | Byte 9 = `0B` (bit 3 bật = WPAD auto-detect) | ❌ WPAD override proxy |
| **Chrome QUIC** (HTTP/3 UDP) | Không disable | ❌ Bypass TCP proxy |

Chrome ưu tiên:
1. WPAD/PAC auto-detect (nếu bit 3 bật trong DefaultConnectionSettings)
2. QUIC (HTTP/3 over UDP) — bypass TCP proxy hoàn toàn
3. System proxy (WinINet/WinHTTP)

Khi WPAD active + QUIC enabled, Chrome có thể kết nối trực tiếp mà không đi qua mitmproxy.

### Giải pháp
- Tắt WPAD auto-detect → Chrome không tìm PAC file
- Disable QUIC → Chrome buộc dùng TCP (qua proxy)
- `--proxy-server` flag → override mọi settings khác, đảm bảo 100% traffic qua proxy

## Mối liên hệ

- **`docker-compose.yml`** — Container `proxify_app` expose port 8080
- **`backend/proxify/server.py`** — mitmproxy listen trên 0.0.0.0:8080
- **Windows Registry** — `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`
- **Chrome Policy** — `HKLM\SOFTWARE\Policies\Google\Chrome\QuicAllowed`

## Rủi ro (Risks & Edge Cases)

### Rủi ro Thấp
- **QUIC disabled** ảnh hưởng performance nhẹ — HTTP/3 nhanh hơn HTTP/2 cho một số site. Nhưng đây là trade-off cần thiết vì mitmproxy không support QUIC.
- **`--proxy-server` flag** override system proxy — nếu proxy down, Chrome sẽ không load được trang nào.

### Không có rủi ro:
- Tắt WPAD không ảnh hưởng vì mạng công ty Sunhouse không sử dụng PAC file.
- Desktop shortcut không thay đổi Chrome installation gốc.

## Commands đã chạy

```powershell
# 1. Disable WPAD auto-detect
Set-ItemProperty -Path "HKCU:\...\Internet Settings" -Name AutoDetect -Value 0

# 2. Sync WinHTTP from WinINet
netsh winhttp import proxy source=ie

# 3. Disable Chrome QUIC
reg add "HKLM\SOFTWARE\Policies\Google\Chrome" /v QuicAllowed /t REG_DWORD /d 0 /f

# 4. Create Chrome shortcut with --proxy-server flag
# -> "Chrome (Proxify).lnk" on Public Desktop
```
