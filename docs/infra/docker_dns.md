# Docker DNS cho `proxify_app`

## Tóm tắt thay đổi
Bỏ hoàn toàn khối `dns:` cố định trong `docker-compose.yml` (trước đó: `172.16.100.5`, `172.16.100.4`, `8.8.8.8`, `1.1.1.1`). Container dùng resolver mặc định của Docker Desktop (`192.168.65.7`, qua embedded DNS `127.0.0.11`).

Lịch sử: lần sửa 1 chỉ đổi thứ tự (đưa `8.8.8.8` lên đầu) → giảm từ ~8s xuống ~1-2s/lookup nhưng vẫn lag, kèm lỗi `Temporary failure in name resolution`.

## Mục đích & Ý nghĩa
Số liệu đo thực tế (2026-10-17, máy dùng Wi-Fi, ngoài mạng công ty):

| Resolver | Từ host | Từ container |
|---|---|---|
| `8.8.8.8` | ~30ms | 1.5–2.5s, có timeout |
| `172.16.100.x` | timeout | timeout |
| Mặc định Docker Desktop `192.168.65.7` | — | **9–59ms** |

UDP DNS đi thẳng qua NAT của VM Docker Desktop rất chậm. Resolver mặc định thì proxy qua resolver của Windows nên nhanh. Log mitmproxy trước khi sửa: p90 thời gian "client connect → server connect" = 5.67s, max 18s → Chrome lướt web rất lag.

## Mối liên hệ
- Ảnh hưởng mọi upstream connection của mitmproxy trong `proxify_app` (router, plugins, `stealth_addon`).
- Host nội bộ `*.sunhouse.com.vn` vẫn ghim qua `extra_hosts`. Khi ở mạng công ty, Windows resolver tự dùng DNS nội bộ → container cũng hưởng theo.

## Rủi ro (Risks & Edge Cases)
- Phụ thuộc Docker Desktop. Nếu chạy trên Linux engine thuần, resolver mặc định lấy từ `/etc/resolv.conf` của host — thường vẫn ổn.
- Không được thêm lại `dns:` cố định nếu không đo trước; đây là nguyên nhân gây lag.
- Nếu VPN/DNS của Windows lỗi thì container cũng lỗi theo (cùng nguồn phân giải).
