# Kiến Trúc Open-Core Plugin SDK & Gitignored Extensions Cho Proxify

## 1. Tóm tắt thay đổi

Chúng ta vừa hoàn thành việc tái cấu trúc toàn diện mã nguồn Proxify từ kiến trúc Monolith sang mô hình **Open-Core Plugin Extension**:

1. **Tách biệt Core và Private Extensions**:
   - Thư mục lõi (`backend/proxify/`) chỉ chứa công cụ MITM Proxy mạng, EventBus, WebSocket Dashboard, và bộ **Plugin SDK** (`proxify.sdk`).
   - Toàn bộ các module trích xuất dữ liệu, crawler riêng tư (Facebook GraphQL Extractor/Crawler/Bridge, Zalo Web Extractor/Decryption/Bot, YouTube Adblock/Anti-AFK) được chuyển vào thư mục riêng `backend/extensions/`.
   - Toàn bộ các trang và hook giao diện riêng tư (`frontend/src/pages/Facebook.tsx`, `frontend/src/pages/Zalo.tsx`, `frontend/src/hooks/useFacebook.ts`, `frontend/src/hooks/useZalo.ts`) cùng các script phụ trợ (`old_crawler.py`, `old_stealth.py`, `backend/CloakBrowser`) đã được đưa vào `.gitignore` và hủy theo dõi khỏi Git (`git rm --cached`).

2. **Xây dựng Proxify Plugin SDK (`backend/proxify/sdk/`)**:
   - `BaseExtension`: Lớp cơ sở trừu tượng định nghĩa vòng đời plugin (`initialize`, `shutdown`).
   - `ExtensionContext`: Capability gateway cấp quyền cho plugin đăng ký HTTP API routes (aiohttp), Observer/Mutator interceptors, Streaming domains, Ignored hosts, Polling endpoints, CQRS topic handlers, Database schema initializers và UI metadata.
   - `ExtensionLoader`: Tự động quét (discover), nạp động (dynamic import) và cô lập lỗi (fault isolation) từ thư mục `backend/extensions/`.

3. **Khử hoàn toàn Hardcoded Dependencies trong Server Lõi (`server.py`)**:
   - Loại bỏ toàn bộ `import FacebookPlatform`, `import ZaloPlugin`, `import YouTubePlugin`.
   - `server.py` chỉ phụ thuộc vào `ExtensionLoader`. `discover_and_load` được kích hoạt trước khi `runner.setup()` để tuân thủ quy tắc đóng băng route của `aiohttp`.

4. **Dynamic Frontend Decoupling (`App.tsx` & `MainLayout.tsx`)**:
   - `App.tsx` sử dụng Vite `import.meta.glob` để phát hiện và nạp động các trang extension khi có mặt trên máy, không còn bất kỳ dòng `import` tĩnh nào tới Zalo/Facebook. Nếu clone repo public, bản build React vẫn hoàn tất 100% không lỗi.
   - `MainLayout.tsx` truy vấn endpoint `GET /api/extensions` để hiển thị động các tab điều hướng (Zalo Extractor, Facebook Extractor).

5. **Tách biệt Test Suite**:
   - Core tests (`backend/tests/`): 40 bài test kiểm thử lõi Proxy, Retention, Stealth headers, Plugin Registry và Extension SDK.
   - Extension tests (`backend/extensions/*/tests/`): 32 bài test kiểm thử crawler, bridge, multitenant, date range và YouTube utils được bảo vệ trong thư mục gitignored.
   - Tổng cộng: **72/72 tests passed** (100%).

---

## 2. Mục đích & Ý nghĩa

- **Bảo mật sở hữu trí tuệ (IP Protection) khi Public Repo**:
  Dự án Proxify có thể được push public lên GitHub như một open-source MITM Network Logger engine mạnh mẽ, sạch sẽ, chuẩn Clean Architecture mà không bị lộ bất kỳ thuật toán cào dữ liệu, bypass bot hay payload decrypt nào của Facebook và Zalo.
- **Tiện lợi quản lý Monorepo cho người phát triển**:
  Người dùng phát triển trực tiếp trong một project duy nhất (`Proxify`), không cần chia tách thành nhiều git repo rời rạc hay tạo nhiều worktree phức tạp. Mọi extension nằm ở `backend/extensions/` vẫn được hệ thống tự động phát hiện và chạy đầy đủ mọi tính năng.
- **Tuân thủ nguyên lý SOLID & Clean Architecture**:
  - **DIP (Dependency Inversion Principle)**: Module cấp cao (`server.py`) không phụ thuộc vào các module cấp thấp (`FacebookPlatform`, `ZaloPlugin`). Cả hai đều phụ thuộc vào abstraction (`BaseExtension`, `ExtensionContext`).
  - **OCP (Open-Closed Principle)**: Khi muốn phát triển thêm nền tảng mới (e.g. TikTok, Telegram, Shopee), chỉ cần tạo thư mục trong `backend/extensions/` mà không phải sửa một dòng code nào trong `server.py` hay router lõi.
  - **SRP (Single Responsibility Principle)**: Core chỉ làm nhiệm vụ proxy và quản trị luồng; các extension tự quản trị API, Database schema và Interceptor của riêng mình.

---

## 3. Mối liên hệ

- **`backend/proxify/sdk/loader.py`**:
  Quản lý việc nạp các module từ thư mục cấu hình `EXTENSIONS_DIR` (mặc định: `backend/extensions` trên host hoặc `/app/extensions` trong Docker).
- **`backend/proxify/server.py`**:
  Khởi tạo `ExtensionLoader`, truyền các context tài nguyên lõi (Router, Dashboard aiohttp App, PostgreSQL connection pools, Worker, Polling filter) vào từng extension.
- **`backend/proxify/platforms/__init__.py` & `plugins/__init__.py`**:
  Tự động bổ sung `extensions/` vào `__path__` của package để duy trì tính tương thích ngược hoàn toàn cho các import submodule cũ nếu có.
- **`frontend/src/App.tsx` & `frontend/src/layouts/MainLayout.tsx`**:
  Liên kết trực tiếp với endpoint `GET /api/extensions` từ backend để render giao diện động.
- **Docker Compose (`docker-compose.yml`)**:
  Mount toàn bộ `./backend` vào `/app`, giúp `backend/extensions` tự động nằm tại `/app/extensions` mà không cần sửa đổi volume mapping.

---

## 4. Rủi ro (Risks & Edge Cases)

1. **Rủi ro về Relative Imports khi Nạp Động**:
   - *Vấn đề*: Khi dùng `importlib.util.spec_from_file_location` trên file lẻ, Python mặc định không gán `__package__`, dẫn đến lỗi `attempted relative import with no known parent package`.
   - *Giải pháp đã xử lý*: `ExtensionLoader` tự động tạo `types.ModuleType(dir_name)` đưa vào `sys.modules`, gán `__package__ = dir_name` trước khi thực thi module con.
2. **Rủi ro về aiohttp Route Freezing**:
   - *Vấn đề*: `aiohttp.web.Application` sẽ khóa (freeze) toàn bộ router sau khi gọi `runner.setup()`. Nếu extension đăng ký route sau thời điểm này, server sẽ throw `RuntimeError`.
   - *Giải pháp đã xử lý*: Toàn bộ chu trình `discover_and_load` được thực thi trước khi `runner.setup()` được gọi trong `server.py`.
3. **Môi trường Clean Clone thiếu file Frontend**:
   - *Vấn đề*: Nếu ai đó clone repo mà không có `Facebook.tsx` hay `Zalo.tsx`, việc dùng `import ... from './pages/Facebook'` sẽ làm gãy lệnh `npm run build`.
   - *Giải pháp đã xử lý*: Chuyển sang `import.meta.glob` giúp Vite chỉ tìm nạp các module thực sự tồn tại trên ổ đĩa. Clean clone sẽ tự động build thành công chỉ với trang `DashboardPage`.
