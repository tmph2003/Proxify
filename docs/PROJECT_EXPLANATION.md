# TÀI LIỆU TOÀN DIỆN VỀ KIẾN TRÚC VÀ HOẠT ĐỘNG DỰ ÁN PROXIFY

> **Tác giả:** Antigravity AI Engineering Team  
> **Cập nhật lần cuối:** 2026-09-03  
> **Phiên bản:** Proxify v2.0 (High-Performance Async & In-Tab Execution Engine)  
> **Trạng thái:** Production Ready  

---

## MỤC LỤC

1. [TỔNG QUAN DỰ ÁN (PROJECT OVERVIEW)](#1-tong-quan)
2. [SƠ ĐỒ KIẾN TRÚC HỆ THỐNG (SYSTEM ARCHITECTURE)](#2-kien-truc)
3. [CHI TIẾT CÁC HỆ THỐNG CON (CORE SUBSYSTEMS)](#3-he-thong-con)
   - [3.1. Lõi Proxy & Điều Hướng (Core Proxy & Router Engine)](#31-core-proxy)
   - [3.2. Hệ Thống EventBus & Background Worker](#32-eventbus)
   - [3.3. Động Cơ Tàng Hình & Giả Lập TLS (Stealth Engine & TLS Spoofer)](#33-stealth)
   - [3.4. Hệ Thống Thu Thập Facebook (Facebook Ingestion Subsystem)](#34-facebook)
   - [3.5. Chrome Extension (Proxify Cookie Helper & Bridge)](#35-extension)
   - [3.6. Module Zalo & YouTube Ads Blocker](#36-zalo-youtube)
   - [3.7. Kho Lưu Trữ & Cơ Sở Dữ Liệu PostgreSQL](#37-database)
   - [3.8. Giao Diện Người Dùng (React Dashboard Frontend)](#38-frontend)
4. [CÁC LUỒNG DỮ LIỆU ĐẦU-CUỐI (END-TO-END DATA FLOWS)](#4-luong-du-lieu)
   - [4.1. Luồng Bắt Gói Tin & Phân Tích Mạng Qua Proxy Cổng 8080](#41-luong-proxy)
   - [4.2. Luồng Đồng Bộ Hóa Cookie & Token 1-Chạm](#42-luong-cookie)
   - [4.3. Luồng Cào Bài Viết Facebook Thông Qua In-Tab Execution](#43-luong-facebook)
   - [4.4. Luồng Giả Lập TLS Vượt Tường Lửa (TikTok / ByteDance)](#44-luong-tls)
5. [CƠ CHẾ BẢO MẬT & PHÒNG THỦ ANTI-BOT (ANTI-DETECTION MECHANICS)](#5-anti-bot)
6. [HƯỚNG DẪN CẤU HÌNH & VẬN HÀNH (OPERATIONS & DEPLOYMENT)](#6-van-hanh)
7. [BẢN ĐỒ CẤU TRÚC THƯ MỤC MÃ NGUỒN (CODEBASE DIRECTORY MAP)](#7-cau-truc-ma-nguon)

---

<a id="1-tong-quan"></a>
# 1. TỔNG QUAN DỰ ÁN (PROJECT OVERVIEW)

### 1.1. Proxify là gì?
**Proxify** là một nền tảng lai (hybrid platform) kết hợp giữa:
1. **Man-In-The-Middle (MITM) Proxy Server**: Đánh chặn, giải mã TLS, phân tích và lưu trữ toàn bộ lưu lượng HTTP/HTTPS/WebSocket đi qua máy trạm trong thời gian thực.
2. **Multi-Platform Intelligence Extractor**: Hệ thống thu thập, phân tích và bóc tách dữ liệu có cấu trúc từ các nền tảng mạng xã hội đóng (Facebook Groups, Zalo Web, TikTok).
3. **Advanced Anti-Bot & Stealth Engine**: Bộ giải pháp vượt rào cản phòng thủ bot (WAF, Akamai, Cloudflare, JA3/JA4 TLS Fingerprint, Meta Comet Security) bằng cơ chế kết hợp giữa giả lập TLS cấp thấp (`curl_cffi`) và thực thi trực tiếp trong ngữ cảnh trình duyệt thật (Chrome Extension In-Tab Execution).

### 1.2. Các bài toán then chốt Proxify giải quyết
* **Vượt rào cản mã hóa & Token động**: Facebook và Zalo sử dụng các API mã hóa nội bộ hoặc token phiên thay đổi liên tục (`fb_dtsg`, `lsd`, `jazoest`, `__spin_t`). Proxify tự động học mẫu template khi người dùng lướt web hoặc trích xuất trực tiếp từ RAM của trình duyệt.
* **Chống bị khóa tài khoản & Logout (Session Revocation Bypass)**: Khắc phục triệt để điểm yếu của các bot cào truyền thống bằng việc chuyển toàn bộ lệnh mạng sang chạy trong Tab Chrome thật của người dùng.
* **Không làm suy giảm trải nghiệm mạng (Zero-Latency Interception)**: Ứng dụng mô hình Radix Trie Router và CQRS (tách biệt Read-Only Observers chạy nền và Mutating Interceptors chạy chặn) để bảo toàn băng thông đường truyền.

---

<a id="2-kien-truc"></a>
# 2. SƠ ĐỒ KIẾN TRÚC HỆ THỐNG (SYSTEM ARCHITECTURE)

Hệ thống Proxify hoạt động dưới dạng cụm vi dịch vụ Docker kết hợp với trình duyệt của người dùng:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                    CLIENT                                       │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                            GOOGLE CHROME                                  │  │
│  │                                                                           │  │
│  │   ┌────────────────────────┐         ┌─────────────────────────────────┐  │  │
│  │   │      Tab Facebook      │         │     Proxify Chrome Extension    │  │  │
│  │   │  (MAIN World Runtime)  │◄────────┤    - background.js (Worker)     │  │  │
│  │   │  - Trích xuất LIVE dtsg│ execute │    - popup.js (Quét CHIPS/Cookie│  │  │
│  │   │  - Gọi fetch() nội bộ  │ Script  │    - content.js (Keep-Alive 10s)│  │  │
│  │   └───────────┬────────────┘         └────────────────▲────────────────┘  │  │
│  │               │ HTTP/HTTPS                            │                   │  │
│  │               │ (Proxy 8080)                          │ Poll Jobs /       │  │
│  └───────────────┼───────────────────────────────────────┼───────────────────┘  │
└──────────────────┼───────────────────────────────────────┼──────────────────────┘
                   │                                       │
═══════════════════╪═══════════════════════════════════════╪═══════════════════════
                   │                                       │ HTTP REST
                   ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          CONTAINER: proxify_app                                 │
│                                                                                 │
│  ┌─────────────────────────┐               ┌─────────────────────────────────┐  │
│  │   mitmproxy (Port 8080) │               │   aiohttp Server (Port 8888)    │  │
│  │   - StealthUpstreamAddon│               │   - Dashboard API (/api/stats)  │  │
│  │   - ProxyAddon (Router) │               │   - Facebook API (/api/facebook)│  │
│  └────────────┬────────────┘               │   - Extension Bridge API        │  │
│               │                            └────────────────▲────────────────┘  │
│               ▼                                             │                   │
│  ┌─────────────────────────┐               ┌────────────────┴────────────────┐  │
│  │   Radix Trie Router     │               │        FacebookCrawler          │  │
│  │   - IObserver (Async)   ├──────────────►│   - Phân trang Cursor           │  │
│  │   - IMutator (Sync)     │   EventBus    │   - Điều phối Bridge Job Queue  │  │
│  └─────────────────────────┘               └────────────────┬────────────────┘  │
│                                                             │                   │
│  ┌─────────────────────────┐               ┌────────────────▼────────────────┐  │
│  │   BackgroundWorker      │               │   Extractor & Canonical PostID  │  │
│  │   - Ghi core.requests   │               │   - DataHelper giải mã ID       │  │
│  │   - Parse bài viết ngầm │               │   - PostRepository (Upsert)     │  │
│  └────────────┬────────────┘               └────────────────┬────────────────┘  │
└───────────────┼─────────────────────────────────────────────┼───────────────────┘
                │                                             │
                ▼                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          CONTAINER: proxify_db                                  │
│                                                                                 │
│   PostgreSQL 15 (Port 5432)                                                     │
│   ├─ Schema core:      requests, raw_payloads                                   │
│   ├─ Schema facebook:  posts, comments, groups, crawl_stats                     │
│   └─ Schema zalo:      members, groups, messages                                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

<a id="3-he-thong-con"></a>
# 3. CHI TIẾT CÁC HỆ THỐNG CON (CORE SUBSYSTEMS)

---

<a id="31-core-proxy"></a>
### 3.1. Lõi Proxy & Điều Hướng (Core Proxy & Router Engine)
* **Thư mục:** [backend/proxify/core/](../backend/proxify/core/), [backend/proxify/server.py](../backend/proxify/server.py)
* **Cơ chế hoạt động:**
  * Khởi chạy `mitmproxy.tools.dump.DumpMaster` trên cổng `8080` (hỗ trợ giải mã SSL/TLS qua chứng chỉ CA tự sinh của Proxify).
  * **Radix Trie Router ([router.py](../backend/proxify/core/router.py))**: Thay vì duyệt danh sách plugin tuần tự với độ phức tạp $O(N)$, router phân rã domain ngược từ TLD (ví dụ `['com', 'facebook', 'api']`) để tra cứu cây tiền tố với độ phức tạp $O(\text{depth})$.
  * **Kiến trúc CQRS cho Proxy**:
    * `IObserverInterceptor`: Các tác vụ chỉ đọc (Ghi log lưu lượng, bắt gói tin GraphQL). Được đẩy vào `asyncio.create_task` chạy ngầm, không làm tăng latency của người dùng.
    * `IMutatorInterceptor`: Các tác vụ sửa đổi gói tin (Thay đổi Header, tiêm mã JavaScript). Được xử lý tuần tự qua `await`.

---

<a id="32-eventbus"></a>
### 3.2. Hệ Thống EventBus & Background Worker
* **Thư mục:** [backend/proxify/core/eventbus.py](../backend/proxify/core/eventbus.py), [backend/proxify/core/worker.py](../backend/proxify/core/worker.py)
* **Nhiệm vụ:**
  * `AsyncEventBus`: Đóng vai trò là Message Broker nội bộ trong bộ nhớ. Khi Interceptor bắt được dữ liệu, nó publish sự kiện lên EventBus.
  * EventBus hỗ trợ ghi nhận các sự kiện quan trọng vào bảng `core.raw_payloads` của PostgreSQL để đảm bảo không mất dữ liệu ngay cả khi hệ thống chịu tải đột biến.
  * `BackgroundWorker`: Lấy payload từ hàng đợi ra để xử lý ngầm (ví dụ: bóc tách mẫu template GraphQL mới, phát hiện trạng thái bài viết bị ẩn).

---

<a id="33-stealth"></a>
### 3.3. Động Cơ Tàng Hình & Giả Lập TLS (Stealth Engine & TLS Spoofer)
* **Thư mục:** [backend/proxify/utils/stealth.py](../backend/proxify/utils/stealth.py), [backend/proxify/plugins/tls_spoofer.py](../backend/proxify/plugins/tls_spoofer.py), [backend/proxify/stealth_addon.py](../backend/proxify/stealth_addon.py)
* **Nhiệm vụ & Công nghệ:**
  * Dựa trên thư viện **`curl_cffi`**, cho phép giả lập chữ ký mã hóa TLS (JA3 / JA4 Fingerprint), thứ tự Cipher Suites, thông số TCP Window và HTTP/2 Settings giống hệt trình duyệt Google Chrome thật.
  * **TLS Spoofer Addon**: Tự động can thiệp vào các yêu cầu gửi đến các domain được chỉ định (như `tiktok.com`, `byteoversea.com`, `zalo.me`), loại bỏ các header nhạy cảm của proxy và gửi lại request qua `curl_cffi` để vượt qua tường lửa WAF của Akamai và ByteDance.

---

<a id="34-facebook"></a>
### 3.4. Hệ Thống Thu Thập Facebook (Facebook Ingestion Subsystem)
* **Thư mục:** [backend/proxify/platforms/facebook/](../backend/proxify/platforms/facebook/)
* **Các thành phần cốt lõi (Đã quy hoạch theo 7 Domain Modules):**
  1. **`crawler.py` (FacebookCrawler)**: Bộ não cào dữ liệu theo khoảng thời gian, điều phối phân trang cursor và In-Tab execution.
  2. **`bridge.py` (ExtensionBridge)**: Cầu nối hai chiều điều phối Job giữa Backend Docker và Chrome Extension trên máy thật.
  3. **`extractor.py` (PostExtractor & DataHelper)**: Bóc tách dữ liệu GraphQL Relay Modern và chuẩn hóa Canonical Post ID.
  4. **`database.py` (FacebookDatabase & Repositories)**: Tầng lưu trữ PostgreSQL schema `facebook` hoàn chỉnh (kèm DDL và DAO upsert chống trùng lặp).
  5. **`stealth.py` (Stealth & Anti-bot Engine)**: Hợp nhất toàn bộ logic chống bot (Độ trễ Gaussian `delay.py`, đột biến form token `session_state.py`, và rate limiter Borg `network.py`).
  6. **`workflow.py` (Task Orchestration Engine)**: Hợp nhất toàn bộ điều phối tác vụ (Command Pattern `commands.py`, Observer Pattern `observer.py`, và hàng đợi SQLite `queue_manager.py`).
  7. **`auth.py` (Auth & In-Memory Token Manager)**: Hợp nhất quản lý template/cookie thuần RAM `token_store.py` và bộ kiểm tra Checkpoint `auth_fetcher.py`.
  8. **`api.py` (FacebookAPI)**: Cung cấp đầy đủ các endpoint REST API cho Dashboard giao diện.
  9. **`interceptor.py` & `platform.py`**: Observer bắt gói tin Mitmproxy thụ động và Plugin Slice tích hợp lõi Proxify.
  10. **`template_fetcher.py`**: Bộ công cụ tự động lấy template GraphQL bằng Headless Playwright.

---

<a id="35-extension"></a>
### 3.5. Chrome Extension (Proxify Cookie Helper & Bridge)
* **Thư mục:** [backend/chrome_extension/](../backend/chrome_extension/)
* **Kiến trúc Manifest V3:**
  * **`popup.js`**: Khi bấm nút, tự động quét sạch toàn bộ Cookie của Facebook từ Cookie API, hỗ trợ cả cookie tiêu chuẩn và Partitioned Cookies (CHIPS trên Chrome 118+), đồng thời trích xuất token live từ tab.
  * **`background.js`**: 
    * Duy trì kết nối thăm dò tới Backend (`/api/facebook/bridge/jobs`).
    * Khi nhận job, sử dụng `chrome.scripting.executeScript` trong ngữ cảnh `MAIN` của tab Facebook thật để thực thi lệnh `fetch()` nội bộ.
    * Tự động điều hướng tab tới nhóm mục tiêu nếu tab chưa mở đúng nhóm.
    * Tích hợp **DOM Scraper Fallback** để trích xuất bài viết từ HTML DOM nếu GraphQL bị lỗi phân quyền.
  * **`content.js`**: Pinging `KEEPALIVE` mỗi 10 giây để chống Chrome Service Worker tự ngắt.

---

<a id="36-zalo-youtube"></a>
### 3.6. Module Zalo & YouTube Ads Blocker
* **Zalo Platform ([platforms/zalo/](../backend/proxify/platforms/zalo/))**:
  * Tự động bóc tách danh bạ, danh sách thành viên nhóm Zalo và tin nhắn trò chuyện.
  * Chứa các bộ giải mã mã hóa `crypto_subtle.js` và hook `json_parse.js` để can thiệp vào tầng giải mã dữ liệu của Zalo Web.
* **YouTube Plugin ([plugins/youtube.py](../backend/proxify/plugins/youtube.py))**:
  * Đánh chặn các yêu cầu phân phối quảng cáo YouTube và chèn script tự động bỏ qua (skip ad) và tự động tiếp tục phát video (auto-resume).

---

<a id="37-database"></a>
### 3.7. Kho Lưu Trữ & Cơ Sở Dữ Liệu PostgreSQL
* **Schema `core`**:
  * `core.requests`: Lưu trữ chi tiết từng request đi qua proxy (Method, URL, Status, Request/Response Headers, Request/Response Body, Thời gian xử lý, Kích thước).
  * `core.raw_payloads`: Bộ đệm sự kiện cho EventBus.
* **Schema `facebook`**:
  * `facebook.posts`: Lưu trữ bài viết đã chuẩn hóa (Canonical `post_id`, `group_id`, `author`, `message`, `reaction_count`, `comment_count`, `share_count`, `created_at`, `permalink_url`).
  * `facebook.groups`: Lưu trữ danh sách nhóm, ánh xạ giữa `slug` và `numeric_id`.
  * `facebook.comments`: Lưu trữ bình luận theo từng bài viết.
* **Schema `zalo`**:
  * `zalo.members`: Danh sách thành viên bóc tách từ các nhóm Zalo (Tên, SĐT nếu có, Vai trò).

---

<a id="38-frontend"></a>
### 3.8. Giao Diện Người Dùng (React Dashboard Frontend)
* **Thư mục:** [frontend/src/](../frontend/src/)
* **Công nghệ:** React 18, Vite, TypeScript, Lucide Icons, Nginx reverse proxy.
* **Các trang chức năng:**
  1. **Dashboard ([Dashboard.tsx](../frontend/src/pages/Dashboard.tsx))**:
     * Giám sát toàn bộ gói tin đi qua proxy theo thời gian thực (Real-time Stream qua WebSocket).
     * Bộ lọc theo Tên miền, Method, trạng thái GraphQL.
     * Nút bật/tắt ghi dữ liệu vào cơ sở dữ liệu (`🟢 Ghi DB: BẬT`).
     * Xuất dữ liệu lưu lượng ra định dạng HAR, JSON, CSV.
  2. **Facebook Analytics ([Facebook.tsx](../frontend/src/pages/Facebook.tsx))**:
     * Chọn nhóm từ danh sách hoặc nhập ID/URL nhóm mới.
     * Bộ chọn khoảng thời gian (Hôm nay, Hôm qua, 7 ngày qua, Tùy chọn).
     * Bảng danh sách bài viết trực quan với avatar tác giả, huy hiệu tương tác (Like, Comment, Share).
     * Xuất danh sách bài viết ra Excel/JSON phục vụ báo cáo.
  3. **Zalo Extractor ([Zalo.tsx](../frontend/src/pages/Zalo.tsx))**:
     * Quản lý tiến trình quét danh sách thành viên nhóm Zalo.

---

<a id="4-luong-du-lieu"></a>
# 4. CÁC LUỒNG DỮ LIỆU ĐẦU-CUỐI (END-TO-END DATA FLOWS)

---

<a id="41-luong-proxy"></a>
### 4.1. Luồng Bắt Gói Tin & Phân Tích Mạng Qua Proxy Cổng 8080
```
[Client App / Browser]
         │ (HTTP/HTTPS Request)
         ▼
[mitmproxy:8080 (ProxyAddon)]
         │
         ▼
[Radix Trie Router] ──► Match Domain
         ├─► [IObserver: FacebookGraphQLObserver] ──► EventBus ──► Học Template GraphQL
         └─► [RequestStorage] ──► PostgreSQL (core.requests) ──► WebSocket Broadcast ──► Dashboard UI
```

---

<a id="42-luong-cookie"></a>
### 4.2. Luồng Đồng Bộ Hóa Cookie & Token 1-Chạm
1. Người dùng mở tab Facebook trên Chrome và bấm biểu tượng Extension Proxify.
2. `popup.js` kích hoạt:
   * Quét Cookie API đa miền (`.facebook.com`, `m.facebook.com`, CHIPS partition).
   * Scripting inject vào tab đọc `window.require("DTSGInitialData").token` và `CurrentUserInitialData.USER_ID`.
3. Extension gửi payload POST đến `http://localhost:8888/api/facebook/cookie`.
4. Backend lưu tạm thời vào `IN_MEMORY_COOKIES` trong RAM (tuyệt đối không ghi ra file đĩa hay database).

---

<a id="43-luong-facebook"></a>
### 4.3. Luồng Cào Bài Viết Facebook Thông Qua In-Tab Execution
```
[Người dùng bấm "Bắt đầu thu thập" trên Dashboard]
                       │
                       ▼
            [API: POST /api/facebook/crawl]
                       │
                       ▼
             [FacebookCrawler Engine]
                       │
                       ▼ Tạo Job cào
            [ExtensionBridge.pending_jobs]
                       ▲
                       │ Poll Job mỗi 1s
            [Chrome Extension background.js]
                       │
                       ▼ chrome.scripting.executeScript(world: "MAIN")
          [Tab Facebook Thật Trên Trình Duyệt]
                       │
                       ├─ 1. Đọc Token bảo mật LIVE (fb_dtsg) từ RAM
                       ├─ 2. Gửi fetch(GraphQL_URL, credentials: "include")
                       │     (Dùng 100% IP thật, TLS thật, Cookie nội bộ)
                       │
                       ├─► [Thành công] ──► Trả về JSON GraphQL
                       └─► [Lỗi 1357001] ──► DOM Scraper Fallback (Cào từ thẻ div[role="article"])
                       │
                       ▼ Gửi kết quả
            [API: POST /api/facebook/bridge/result]
                       │
                       ▼
           [PostExtractor & DataHelper]
                       │ (Chuẩn hóa Canonical Numeric Post ID)
                       ▼
         [PostRepository (facebook.posts)]
                       │ (ON CONFLICT DO UPDATE)
                       ▼
     [Hiển thị bài viết tức thì lên Dashboard UI]
```

---

<a id="44-luong-tls"></a>
### 4.4. Luồng Giả Lập TLS Vượt Tường Lửa (TikTok / ByteDance)
1. Ứng dụng client gửi yêu cầu đến `tiktok.com` thông qua proxy Proxify.
2. `TLSSpooferPlugin` phát hiện domain nằm trong danh sách `SPOOF_DOMAINS`.
3. Plugin chuyển tiếp payload qua `StealthSessionManager`.
4. `curl_cffi` thiết lập phiên kết nối TLS trực tiếp với máy chủ TikTok với chữ ký JA3 giống hệt Google Chrome thật.
5. Máy chủ TikTok phản hồi gói tin hợp lệ và proxy trả dữ liệu về cho client.

---

<a id="5-anti-bot"></a>
# 5. CƠ CHẾ BẢO MẬT & PHÒNG THỦ ANTI-BOT (ANTI-DETECTION MECHANICS)

Hệ thống Proxify được thiết kế để đối phó với **2 tầng giám sát** của các nền tảng lớn:

| Tầng Giám Sát | Mục Tiêu Giám Sát | Cách Proxify Vượt Qua |
| :--- | :--- | :--- |
| **Tầng 1: Hạ tầng & Danh tính (Transport & Identity Layer)** | • Địa chỉ IP (Datacenter vs Dân cư)<br>• Chữ ký TLS (JA3/JA4)<br>• HTTP/2 Frames & Settings<br>• Cookie bảo mật HttpOnly (`xs`, `c_user`) | **In-Tab Execution**: Toàn bộ thao tác mạng được ủy quyền cho chính trình duyệt Chrome thật của người dùng thông qua Extension. Trình duyệt tự gửi request từ chính IP của máy, dùng TLS thật và tự đính kèm cookie nội bộ. Loại bỏ 100% nguy cơ bị Facebook Logout. |
| **Tầng 2: Hành vi & Tần suất (Behavioral Layer)** | • Tần suất request (Rate limit/Burst)<br>• Sự kiện chuột/cuộn (`mousemove`, `scroll`)<br>• Trạng thái tab ẩn/hiện (`document.hidden`) | **Human-like Jitter Delay**: Crawler cài đặt độ trễ ngẫu nhiên từ **3 đến 6 giây** giữa mỗi lần phân trang.<br>**Tự động kiểm tra quyền nhóm**: Cảnh báo người dùng nếu cào nhóm kín chưa tham gia, tránh gửi request lỗi liên tục. |

---

<a id="6-van-hanh"></a>
# 6. HƯỚNG DẪN CẤU HÌNH & VẬN HÀNH (OPERATIONS & DEPLOYMENT)

### 6.1. Khởi chạy toàn bộ hệ thống bằng Docker Compose
Tại thư mục gốc của dự án, chạy lệnh:
```bash
docker compose up -d --build
```
Kiểm tra trạng thái các container:
```bash
docker ps
```
Hệ thống sẽ vận hành 3 container chính:
* `proxify_ui` (Cổng `8888`): Dashboard điều khiển người dùng.
* `proxify_app` (Cổng `8080` & `8888` nội bộ): Backend Python, Mitmproxy và API server.
* `proxify_db` (Cổng `5432`): Cơ sở dữ liệu PostgreSQL 15.

### 6.2. Cài đặt và Cập nhật Chrome Extension
1. Mở Google Chrome, truy cập: `chrome://extensions/`.
2. Bật công tắc **Chế độ dành cho nhà phát triển (Developer mode)** ở góc trên bên phải.
3. Bấm **Tải tiện ích đã giải nén (Load unpacked)** và chọn thư mục:
   `backend/chrome_extension`
4. *Lưu ý quan trọng:* Mỗi khi có thay đổi trong mã nguồn extension, phải vào lại trang này và bấm nút **🔄 Tải lại (Reload)** trên thẻ của Proxify Cookie Helper.

### 6.3. Bảng biến số môi trường quan trọng (`docker-compose.yml`)
* `DB_DSN`: Chuỗi kết nối PostgreSQL (`postgresql://proxify_user:proxify_pass@db:5432/proxify_db`).
* `DB_INTEGRATION_ENABLED`: Bật/tắt mặc định việc lưu gói tin vào database (`true`/`false`).
* `SPOOF_DOMAINS`: Danh sách các domain áp dụng giả lập TLS tự động.
* `PROXY_PORT`: Cổng lắng nghe của Proxy (`8080`).

---

<a id="7-cau-truc-ma-nguon"></a>
# 7. BẢN ĐỒ CẤU TRÚC THƯ MỤC MÃ NGUỒN (CODEBASE DIRECTORY MAP)

```
Proxify/
├── backend/
│   ├── chrome_extension/          # Tiện ích mở rộng Chrome (Bridge & Token Helper)
│   │   ├── manifest.json          # Cấu hình Manifest V3
│   │   ├── background.js          # Service Worker điều phối tab và In-Tab execution
│   │   ├── content.js             # Content Script giữ kết nối keepalive 24/7
│   │   ├── popup.html             # Giao diện popup 1 chạm
│   │   └── popup.js               # Logic quét cookie và đồng bộ token
│   │
│   ├── proxify/                   # Gói mã nguồn chính của Backend Python
│   │   ├── core/                  # Hạ tầng lõi (Core Engine)
│   │   │   ├── router.py          # Radix Trie Router điều phối lưu lượng
│   │   │   ├── eventbus.py        # AsyncEventBus trung chuyển sự kiện
│   │   │   ├── interfaces.py      # Định nghĩa Abstract Base Classes
│   │   │   └── worker.py          # Background Worker xử lý ngầm
│   │   │
│   │   ├── platforms/             # Các nền tảng tích hợp chuyên sâu
│   │   │   ├── facebook/          # Nền tảng Facebook
│   │   │   │   ├── api.py         # REST API điều khiển (/api/facebook/*)
│   │   │   │   ├── bridge.py      # Cầu nối hai chiều với Chrome Extension
│   │   │   │   ├── crawler.py     # Động cơ cào bài viết theo ngày tháng
│   │   │   │   ├── extractor.py   # Bóc tách GraphQL & Chuẩn hóa Canonical Post ID
│   │   │   │   ├── interceptor.py # Observer bắt mẫu gói tin khi lướt web
│   │   │   │   ├── repository.py  # Thao tác cơ sở dữ liệu PostgreSQL
│   │   │   │   └── token_store.py # Quản lý bộ nhớ đệm phiên và cache đĩa
│   │   │   └── zalo/              # Nền tảng Zalo Web (Bóc tách thành viên, tin nhắn)
│   │   │
│   │   ├── plugins/               # Các plugin mở rộng
│   │   │   ├── tls_spoofer.py     # Giả lập TLS chống chặn cho TikTok / ByteDance
│   │   │   └── youtube.py         # Chặn quảng cáo YouTube tự động
│   │   │
│   │   ├── storage/               # Quản lý kết nối DB và lưu trữ request
│   │   ├── utils/                 # Tiện ích bổ trợ (Stealth engine, Content helper)
│   │   ├── dashboard.py           # REST API & WebSocket cho Traffic Dashboard
│   │   ├── server.py              # Entry Point khởi chạy toàn bộ hệ thống
│   │   └── stealth_addon.py       # Mitmproxy Addon kích hoạt chế độ tàng hình
│   │
│   └── Dockerfile                 # Khởi tạo container backend proxify_app
│
├── frontend/                      # Ứng dụng giao diện người dùng React + Vite
│   ├── src/
│   │   ├── pages/                 # Các màn hình chính (Dashboard, Facebook, Zalo)
│   │   ├── hooks/                 # React Hooks kết nối API backend
│   │   └── index.css              # Hệ thống phong cách giao diện Dark Theme
│   ├── nginx.conf                 # Cấu hình Nginx reverse proxy cổng 8888
│   └── Dockerfile                 # Khởi tạo container frontend proxify_ui
│
├── docs/                          # Kho tài liệu kỹ thuật của dự án
└── docker-compose.yml             # Tệp cấu hình điều phối các dịch vụ Docker
```

---
*Tài liệu này được biên soạn để cung cấp cái nhìn toàn diện, sâu sắc và chuẩn xác nhất về toàn bộ cấu trúc, logic vận hành và cơ chế bảo mật của dự án Proxify.*
