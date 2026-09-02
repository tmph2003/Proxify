# Sửa lỗi Không tải được đoạn chat Facebook khi bật Proxify

## Tóm tắt thay đổi
- Bỏ qua các domain liên quan đến chat và real-time của Facebook (như `edge-chat` và `mqtt`) trong `StealthUpstreamAddon`.

## Mục đích & Ý nghĩa
- Khi bật chế độ Stealth, `curl_cffi` được sử dụng để giả lập TLS fingerprint. Tuy nhiên `curl_cffi` có cơ chế buffer (gom) toàn bộ response rồi mới trả về. Các kết nối chat của Facebook sử dụng HTTP long-polling (giữ kết nối mở liên tục để nhận dữ liệu thời gian thực), nên việc buffer sẽ làm kết nối bị treo và gây ra lỗi "Không tải được đoạn chat" trên giao diện Facebook.
- Việc bỏ qua các domain này giúp luồng dữ liệu chat đi thẳng qua proxy mà không bị Stealth Engine can thiệp, đảm bảo chat hoạt động bình thường.

## Mối liên hệ
- File `backend/proxify/stealth_addon.py`: Sửa logic filter domain trong `request()`.

## Rủi ro (Risks & Edge Cases)
- Các kết nối đến `edge-chat` sẽ không được giả lập TLS fingerprint. Tuy nhiên, các anti-bot thường kiểm tra fingerprint ở các request tải trang tĩnh hoặc request GraphQL API (đã được giả lập), còn các domain phụ trợ như chat ít bị rà soát khắt khe hơn.
