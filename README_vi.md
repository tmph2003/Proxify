<h1 align="center">
    <br>
    <img alt="Proxify Logo" src="assets/logo.png" width="150" style="border-radius: 20px;">
    <br>
    Proxify
    <br>
    <small>The Ultimate Request Capture & Proxy Framework</small>
</h1>

<p align="center">
    <a href="README.md">English</a> | <strong>Tiếng Việt</strong>
</p>

<p align="center">
    <a href="https://python.org" alt="Python version">
        <img alt="Python version" src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python"></a>
    <a href="https://mitmproxy.org/" alt="Mitmproxy">
        <img alt="Mitmproxy version" src="https://img.shields.io/badge/Mitmproxy-10.1%2B-red?style=flat-square"></a>
    <a href="https://postgresql.org" alt="PostgreSQL">
        <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-Ready-336791?style=flat-square&logo=postgresql"></a>
    <a href="#" alt="License">
        <img alt="License" src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square"></a>
</p>

<p align="center">
    <a href="#core-features"><strong>Tính năng chính</strong></a>
    &middot;
    <a href="#quick-start"><strong>Bắt đầu nhanh</strong></a>
    &middot;
    <a href="#platforms"><strong>Nền tảng hỗ trợ</strong></a>
    &middot;
    <a href="#dashboard"><strong>Dashboard</strong></a>
    &middot;
    <a href="#cli"><strong>CLI</strong></a>
</p>

**Proxify** là một framework mạnh mẽ chuyên dùng để đánh chặn (intercept) và phân tích các luồng yêu cầu HTTP/HTTPS, được xây dựng dựa trên `mitmproxy`.

Được thiết kế để chạy nền tĩnh lặng, tự động thu thập, phân tích và lưu trữ các request từ nhiều nền tảng (Zalo, Facebook, Shopee, v.v.) vào cơ sở dữ liệu PostgreSQL để phục vụ mục đích Data Extraction, Analytics hoặc Reverse Engineering. 

Hệ thống hoạt động đa luồng, tối ưu bộ nhớ, tích hợp sẵn Dashboard thời gian thực và đảm bảo không bỏ sót bất kỳ request nào.

```python
# Tích hợp sâu nhiều Platform sẵn có
from proxify.platforms.zalo import zalo_db

# Tự động lưu vào PostgreSQL
zalo_db.groups.upsert(
    group_id="12345", 
    name="Nhóm Bóc Tách", 
    members=150
)
```

Hoặc chạy chế độ CLI mạnh mẽ:

```bash
# Khởi động hệ thống proxy trên cổng 9090 và theo dõi facebook.com
python -m proxify --port 9090 --dashboard-port 9999 --domain facebook.com
```

---

## 🚀 Bắt Đầu Nhanh

Khởi động dự án cực kỳ dễ dàng.

```bash
# 1. Cài đặt các thư viện cần thiết
pip install -r requirements.txt

# 2. Cấu hình biến môi trường
cp .env.example .env
# Sửa file .env với thông tin DB_DSN, PROXY_PORT,... của riêng bạn

# 3. Chạy hệ thống
python -m proxify
```
> ⚠️ **Quan trọng**: Sau khi hệ thống chạy, bạn **phải cấu hình Proxy thủ công** trên trình duyệt hoặc điện thoại của mình:
> - **Host (Máy chủ proxy):** `127.0.0.1` (nếu chạy trên cùng máy) hoặc IP mạng LAN của máy bạn (nếu dùng điện thoại).
> - **Port (Cổng):** `8080`
> 
> Cuối cùng, truy cập trang `http://mitm.it` trên trình duyệt đó để tải và cài đặt chứng chỉ HTTPS.

## 🛡️ Tính Năng Nổi Bật

- **Bóc tách Tàng hình**: Lắng nghe và trích xuất dữ liệu từ các luồng traffic qua proxy mà không can thiệp, không làm chậm quá trình duyệt web của người dùng.
- **Hỗ trợ HTTP/2**: Sẵn sàng đón nhận các luồng dữ liệu HTTP/2 cực nhanh, hoặc ép hạ cấp (force downgrade) xuống HTTP/1.1 (tránh lỗi 502 với các nền tảng quét proxy khắt khe).
- **PostgreSQL Connection Pool**: Sử dụng `ThreadedConnectionPool` chuẩn công nghiệp để lưu trữ dữ liệu đồng thời, an toàn tuyệt đối ở môi trường đa luồng.
- **Dashboard thời gian thực**: Theo dõi luồng dữ liệu, điều chỉnh cấu hình và xem log ngay trên trình duyệt, không cần nhìn chằm chằm vào console.
- **Khả năng mở rộng**: Tận dụng kiến trúc Addon của Mitmproxy, bạn có thể dễ dàng viết thêm các đoạn script parse logic riêng cho các domain cụ thể (Platforms).

## 📂 Cấu Trúc Thư Mục (Kiến trúc)

Codebase tuân thủ nghiêm ngặt các nguyên tắc **SOLID**, ứng dụng **Dependency Injection**, **Event-Driven Architecture (Pub/Sub)**, và **Repository Pattern** để đảm bảo khả năng mở rộng, hiệu suất cao và dễ dàng bảo trì.

```text
proxify/
├── __main__.py             # CLI Entry point
├── server.py               # Khởi chạy mitmproxy và đăng ký các Event Listeners
├── capture_addon.py        # Lõi Proxy Interceptor. Phát sóng các sự kiện `response_captured`
├── storage.py              # Background worker xử lý Bulk Insert vào Database
├── core/                   # 🧠 Lõi Điều phối Sự kiện (Event-Driven Engine)
│   ├── events.py           # EventBus (Logic của Publisher/Subscriber)
│   ├── interfaces.py       # Typing Protocols (VD: EventListener)
│   └── listeners.py        # Subscribers (DashboardBroadcaster, DatabaseWriter)
├── database/               # 💾 Quản lý Database
│   ├── connection.py       # Singleton PostgreSQL ThreadedConnectionPool dùng chung
│   └── setup.py            # Cài đặt cấu trúc bảng (schema) ban đầu
├── platforms/              # 🌐 Các bộ Trích xuất dữ liệu theo từng nền tảng
│   ├── facebook/           
│   │   ├── database.py     # Facebook Database Facade
│   │   ├── repository.py   # Repository Pattern cho Tác giả, Bài viết, Bình luận
│   │   └── extractor.py    # Script chạy ngầm để bóc tách request thô thành dữ liệu chuẩn
│   └── zalo/               # (Cấu trúc Repository tương tự như Facebook)
├── plugins/                # 🔌 Các plugin cắm nóng để mở rộng tính năng proxy
└── utils/                  # 🛠️ Các hàm hỗ trợ (VD: phân tích GraphQL)
```

### 🔌 Kiến Trúc Plugin (Nguyên tắc Open/Closed)

Proxify tận dụng tối đa Kiến trúc Plugin động (Dynamic Plugin Architecture) để đảm bảo file lõi (`capture_addon.py`) luôn cực kỳ nhẹ gọn và không bị dính chặt (decoupled) vào các logic của từng trang web cụ thể.

- **Open (Mở để mở rộng):** Để cào dữ liệu từ một nền tảng mới (VD: TikTok, Shopee), bạn chỉ cần tạo một file mới thả vào thư mục `plugins/` và thêm decorator `@register_plugin("name")` ở đầu file.
- **Closed (Đóng để sửa đổi):** Bạn không bao giờ cần phải đụng vào file `capture_addon.py` để thêm tính năng mới. Hệ thống sẽ tự động quét và phân luồng mạng (network flows) thẳng tới Plugin của bạn nếu nó khớp với biến `target_domains`.

Đặc biệt, các Plugins còn có khả năng tự chèn (inject) các API routes và UI tabs riêng của nó vào thẳng bảng điều khiển Web (Dashboard)!

## 🆘 Khắc Phục Sự Cố

### Lỗi trên Docker Desktop Windows: "Only one usage of each socket address"

Nếu bạn gặp tình trạng proxy bị lặp vô hạn (infinite loop) báo lỗi `connectex: Only one usage of each socket address`, khả năng rất cao là Docker Desktop đang kế thừa cài đặt Proxy của Windows, khiến cho proxy tự đẩy request về lại chính nó.

**Cách khắc phục:**
1. Mở **Docker Desktop**.
2. Chọn **Settings** (hình bánh răng) -> **Resources** -> **Proxies**.
3. Tại phần **Containers proxy**, đổi thiết lập từ `Same as host proxy` thành **`No proxy`**.
4. Nhấn **Apply & Restart**.

Sau khi Docker khởi động lại, container có thể kết nối ra internet bình thường mà không bị lặp.
