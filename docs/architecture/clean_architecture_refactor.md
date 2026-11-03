# Tài liệu Kiến trúc: Tái cấu trúc Clean Architecture & Decoupling (Milestone 3)

## 1. Tóm tắt thay đổi

Trong Milestone 3, Proxify đã được tái cấu trúc triệt để theo các nguyên lý Clean Architecture và SOLID (đặc biệt là Open/Closed Principle - OCP và Single Responsibility Principle - SRP):

1. **Decouple Vendor Stream Rules khỏi Core Proxy**:
   - Loại bỏ hoàn toàn các chuỗi hardcode đặc thù của nhà cung cấp trong `crates/proxify-core/src/proxy.rs::should_stream_request`, bao gồm ngoại lệ Zalo `zalo.me` ("trusted-device-bridge") và 18 đường dẫn API/streaming của YouTube (`/live_chat`, `/videoplayback`, `/youtubei/v1/log_event`, v.v.).
   - Mở rộng `ProxyRouter` (`crates/proxify-core/src/router.rs`) với cơ chế đăng ký quy tắc động:
     - `register_stream_path_rule(domain_pattern, path_prefix)`: Đăng ký tiền tố đường dẫn cần stream nhanh theo domain.
     - `register_stream_exclusion(domain_pattern, pattern)`: Đăng ký ngoại lệ không stream trực tiếp (để đảm bảo gói tin đi qua chuỗi MutatorInterceptor).
     - `is_stream_excluded(host, path)` & `should_stream_path(host, path)`: Kiểm tra chính xác, tối ưu hóa zero-allocation matching.
   - Chuyển giao trách nhiệm đăng ký về đúng tầng Application Extension:
     - `ext-youtube` tự đăng ký 18 stream path rules trong `on_init`.
     - `ext-zalo` tự đăng ký exclusion rule cho `trusted-device-bridge` trong `on_init`.

2. **Generic hóa GraphQL Parser & Stealth Error Signatures**:
   - `crates/proxify-core/src/graphql.rs`: Loại bỏ việc hardcode `fb_api_req_friendly_name` và `doc_id`. Bổ sung registry alias động cho GraphQL operation name (`operationName`, `operation_name`, `query_name`, `op`) và query aliases (`query`, `query_id`, `document_id`). Cung cấp API `GraphQLParser::register_operation_alias` và `GraphQLParser::register_query_alias`. Đồng thời hỗ trợ giải quyết dynamic alias trong cả định dạng `application/json` và `application/x-www-form-urlencoded`.
   - `crates/proxify-core/src/stealth.rs`: Tách rời các mã lỗi Facebook Graph API checkpoint (`"error":1357001`, `"is_checkpoint":true`, v.v.) khỏi core `CORE_SOFT_BLOCK_SIGNATURES`. Triển khai `register_soft_block_signature` thread-safe.
   - `ext-facebook`: Tự đăng ký các alias Facebook GraphQL và các checkpoint signatures của Facebook trong `on_init`.

3. **Encapsulate SDK Infrastructure Types & Chuẩn hóa Naming**:
   - `crates/proxify-sdk/src/lib.rs`: Đổi tên trait method `on_Init` thành snake_case chuẩn Rust `on_init`. Cung cấp cơ chế ủy quyền vòng đời hai chiều an toàn đệ quy (bidirectional recursion-safe lifecycle delegation) giữa `on_init` và `on_Init` thông qua bộ đếm `lifecycle_depth` trong `ExtensionContext`.
   - Bổ sung các phương thức bao đóng (accessor methods) trên `ExtensionContext`: `db_pool()`, `event_bus()`, `register_stream_path_rule()`, `register_stream_exclusion()`, `register_soft_block_signature()`, `sub_routers()`, v.v., đồng thời giữ nguyên các public fields hiện tại nhằm duy trì tương thích 100% cho mã nguồn hiện hữu.

---

## 2. Mục đích & Ý nghĩa

- **Tuân thủ Open/Closed Principle (OCP)**: Core proxy engine (`proxify-core`) đóng với các sửa đổi trực tiếp khi có dịch vụ mới, nhưng mở với các mở rộng thông qua dynamic registries. Khi cần hỗ trợ nền tảng mới (TikTok, Telegram, v.v.), chỉ cần tạo extension mới mà không cần chạm vào `proxy.rs` hay `graphql.rs`.
- **Single Responsibility Principle (SRP)**:
  - `proxify-core` tập trung duy nhất vào nhiệm vụ vận chuyển mạng (MITM TLS, HTTP/WebSocket framing, trie routing, batch storage).
  - Nghiệp vụ của từng nền tảng (cắt quảng cáo YouTube, giải mã Zalo Web, crawl dữ liệu Facebook) được cô lập trọn vẹn trong crate tương ứng (`ext-youtube`, `ext-zalo`, `ext-facebook`).
- **Dependency Inversion Principle (DIP)**: Core không phụ thuộc vào chi tiết cụ thể của extension. Extension đăng ký khả năng của mình vào context trừu tượng.
- **Xóa bỏ Nợ kỹ thuật (Technical Debt)**: Loại bỏ các tên hàm mang phong cách legacy Python (`on_Init`), chuẩn hóa API Rust idiomatic.

---

## 3. Mối liên hệ Kiến trúc

```
┌────────────────────────────────────────────────────────┐
│                   Presentation Layer                   │
│   crates/proxify-server (main.rs, dashboard.rs)        │
│   - Nối ext_ctx rules -> router & stealth registry     │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                    Application Layer                   │
│   ext-youtube: đăng ký 18 streaming path rules         │
│   ext-zalo: đăng ký exclusion trusted-device-bridge    │
│   ext-facebook: đăng ký GraphQL aliases & soft blocks  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                       Domain Layer                     │
│   crates/proxify-sdk:                                  │
│   - BaseExtension: on_init <-> on_Init delegation      │
│   - ExtensionContext: accessors & registration hooks   │
│   - lifecycle_depth: chống tràn stack khi ủy quyền     │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                  Infrastructure Layer                  │
│   crates/proxify-core:                                 │
│   - proxy.rs: vendor-agnostic fast-path & upstream     │
│   - router.rs: StreamPathRule, StreamExclusionRule     │
│   - graphql.rs: dynamic operation & query aliases      │
│   - stealth.rs: dynamic soft block signature registry  │
└────────────────────────────────────────────────────────┘
```

---

## 4. Chi tiết Khắc phục Lỗ hổng & Hoàn thiện (Remediation Actions)

Theo các báo cáo đánh giá đối kháng (Reviewer 1, Challenger 1, Challenger 2), 5 lỗi nghiêm trọng đã được khắc phục hoàn toàn:

### 4.1. An toàn Cắt chuỗi UTF-8 Char Boundary trong `stealth.rs`
- **Vấn đề**: Cắt chuỗi bằng chỉ số byte thô `&body[..2000]` gây crash thread unhandled (`panic: end byte index 2000 is not a char boundary; it is inside '...' of string`) khi byte thứ 2000 rơi vào giữa ký tự UTF-8 đa byte (tiếng Việt có dấu, emoji, CJK).
- **Khắc phục**: Sử dụng `char_indices` để định vị biên ký tự UTF-8 hợp lệ cuối cùng nhỏ hơn hoặc bằng 2000 byte:
  ```rust
  let check_chunk = if body.len() > 2000 {
      let end = body
          .char_indices()
          .take_while(|(idx, _)| *idx <= 2000)
          .last()
          .map(|(idx, _)| idx)
          .unwrap_or(0);
      &body[..end]
  } else {
      body
  };
  ```
- **Kết quả**: Triệt tiêu 100% rủi ro DoS / thread panic đối với mọi phản hồi HTTP chứa văn bản đa ngôn ngữ và emoji.

### 4.2. Sửa lỗi Shadowing Chữ ký Soft-Block trong `CORE_SOFT_BLOCK_SIGNATURES`
- **Vấn đề**: `"Temporarily Blocked"` đứng trước `"You\u{2019}re Temporarily Blocked"` khiến chuỗi dài hơn bị che khuất vĩnh viễn (dead code) do tìm kiếm chuỗi con luôn khớp signature đầu tiên.
- **Khắc phục**: Sắp xếp lại mảng chữ ký theo nguyên tắc: chữ ký đặc thù, cụ thể hơn đứng trước chữ ký tổng quát:
  ```rust
  const CORE_SOFT_BLOCK_SIGNATURES: &[&str] = &[
      "You\u{2019}re Temporarily Blocked",
      "Temporarily Blocked",
      "security check",
  ];
  ```

### 4.3. Ngăn chặn Stream Bypass đối với Mutator trong `forward_upstream`
- **Vấn đề**: Trong `proxy.rs::forward_upstream`, phản hồi có `Content-Type: application/javascript` bị tự động chuyển đổi thành luồng phản hồi streaming (`should_stream_response_headers`), bỏ qua việc kiểm tra `is_stream_excluded`. Hệ quả là file `trusted-device-bridge.js` của Zalo bị stream trực tiếp về client mà không đi qua `ZaloHookMutator::mutate_response`.
- **Khắc phục**: Bổ sung điều kiện kiểm tra `!self.router.is_stream_excluded(&req.host, &req.path)` trước khi quyết định stream phản hồi từ headers:
  ```rust
  if !self.router.is_stream_excluded(&req.host, &req.path)
      && Self::should_stream_response_headers(ct, cl)
  {
      return Err(Box::new(Self::convert_reqwest_to_stream_response(
          resp, false,
      )));
  }
  ```
- Đồng thời cập nhật `ProxyRouter::should_record` sử dụng `self.should_stream_request(host, path)` để tôn trọng stream exclusions.

### 4.4. Ủy quyền Vòng đời Hai chiều An toàn trong `BaseExtension`
- **Vấn đề**: Nếu một plugin bên ngoài chỉ triển khai `on_Init(&self, ctx)` (interface cũ), máy chủ gọi `ext.on_init(&mut ext_ctx)` sẽ chỉ chạy default no-op `Ok(())` và bỏ qua logic khởi tạo của plugin.
- **Khắc phục**: Triển khai cơ chế ủy quyền hai chiều có kiểm soát đệ quy bằng `lifecycle_depth`:
  ```rust
  #[async_trait]
  pub trait BaseExtension: Send + Sync {
      fn name(&self) -> &str;

      async fn on_init(&self, context: &mut ExtensionContext) -> Result<(), String> {
          if context.lifecycle_depth > 0 {
              return Ok(());
          }
          context.lifecycle_depth += 1;
          #[allow(deprecated)]
          let res = self.on_Init(context).await;
          context.lifecycle_depth -= 1;
          res
      }

      #[allow(non_snake_case)]
      #[deprecated(note = "Use on_init instead")]
      async fn on_Init(&self, context: &mut ExtensionContext) -> Result<(), String> {
          if context.lifecycle_depth > 0 {
              return Ok(());
          }
          context.lifecycle_depth += 1;
          let res = self.on_init(context).await;
          context.lifecycle_depth -= 1;
          res
      }
  }
  ```
- **Kết quả**: Hỗ trợ 100% mọi trường hợp: plugin override `on_init`, plugin override `on_Init`, plugin override cả hai, hoặc không override phương thức nào mà không gây tràn bộ nhớ stack.

### 4.5. Hoàn thiện Dynamic GraphQL Alias Resolution cho JSON Body
- **Vấn đề**: `GraphQLParser::parse` chỉ giải quyết dynamic alias trong GET query parameters và form-urlencoded body, nhưng lại hardcode `"operationName"` và `"query"` khi parse `application/json`.
- **Khắc phục**: Mở rộng parser JSON quét qua `is_operation_key`, `is_query_key`, và `is_variables_key` bằng các combinators tối ưu:
  ```rust
  let op = map.iter().find(|(k, _)| Self::is_operation_key(k)).and_then(|(_, v)| v.as_str()).map(|s| s.to_string());
  let q = map.iter().find(|(k, _)| Self::is_query_key(k)).and_then(|(_, v)| {
      v.as_str().map(|s| s.to_string())
          .or_else(|| v.as_i64().map(|n| n.to_string()))
          .or_else(|| v.as_u64().map(|u| u.to_string()))
  });
  ```

---

## 5. Rủi ro (Risks & Edge Cases) & Biện pháp Xử lý

| Rủi ro tiềm ẩn | Mức độ | Biện pháp kỹ thuật triệt để |
|---|---|---|
| **Bypass nhầm Mutator Response**: Nếu file JS được stream trực tiếp theo MIME type hoặc extension, mutator không thể can thiệp payload. | Nghiêm trọng | Kiểm tra `is_stream_excluded` ở cả 2 chốt chặn: fast-path trước khi gửi request (`proxy.rs:508`) và sau khi nhận response headers từ upstream (`proxy.rs:887`). |
| **Đệ quy vô hạn trong Lifecycle Delegation**: Hai default methods gọi lẫn nhau (`on_init` gọi `on_Init` và ngược lại) có thể gây tràn stack nếu struct không override cả 2. | Nghiêm trọng | Kiểm soát bằng biến trạng thái `lifecycle_depth` trong `ExtensionContext`. Khi `lifecycle_depth > 0`, hàm ngay lập tức trả về `Ok(())`, cắt đứt chu kỳ đệ quy. |
| **Cắt chuỗi UTF-8 làm sập luồng worker**: Phản hồi HTTP chứa ký tự UTF-8 đa byte ở ngưỡng 2000 byte làm sập worker Tokio. | Nghiêm trọng | Duyệt ngược các chỉ số ký tự hợp lệ thông qua `char_indices()` và `take_while`, đảm bảo điểm cắt luôn là đầu một code point UTF-8. |
| **Che khuất Chữ ký (Signature Shadowing)**: Chữ ký ngắn hơn đứng trước làm che khuất chữ ký đặc thù. | Trung bình | Sắp xếp mảng chữ ký ưu tiên chuỗi dài/chính xác hơn lên đầu danh sách duyệt. |
| **Tranh chấp khóa (Lock Contention) trên Alias / Signature Registry**: Kiểm tra alias trên mỗi request có thể gây nghẽn nếu dùng khóa thô. | Thấp | Dùng `parking_lot::RwLock` theo mô hình Read-Heavy, nhiều worker đọc đồng thời không gây tranh chấp. |
