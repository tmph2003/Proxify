# Tóm tắt thay đổi

1. Gỡ bỏ hoàn toàn logic tạo `syntheticTemplate` tĩnh (chứa `doc_id` cố định `8856247924484083`) trong file `chrome_extension/popup.js`.
2. Hủy bỏ việc gửi payload giả lập này về `/api/facebook/cookie` khi người dùng bấm nút "Save Cookie" trên Extension.

# Mục đích & Ý nghĩa

- Facebook thường xuyên thay đổi chuỗi hash `doc_id` của GraphQL (ví dụ: `8856247924484083` hiện đã bị khai tử và trả về lỗi "was not found"). Việc nhúng cứng `doc_id` trong Extension khiến Crawler luôn dùng hash cũ nát này nếu người dùng không tự tay mở Facebook để Extension (background.js) bắt gói tin mới.
- Bằng cách gỡ bỏ mã giả lập này, Crawler trên Backend giờ đây bắt buộc phải nhận diện đúng `feed_template = null` trong trường hợp người dùng chưa lướt Facebook. Từ đó Crawler sẽ chặn tiến trình ngay từ đầu và hiển thị thông báo hướng dẫn người dùng rất rõ ràng: "Vui lòng mở Facebook, vào 1 nhóm bất kỳ, lướt để bắt gói tin...", thay vì cố tình chạy rồi crash ngầm do lỗi GraphQL từ Facebook.

# Mối liên hệ

- File `chrome_extension/popup.js`
- Extension giao tiếp với `proxify/platforms/facebook/api.py` qua `/api/facebook/cookie`

# Rủi ro (Risks & Edge Cases)

- **UX thay đổi**: Người dùng KHÔNG THỂ chỉ bấm mỗi nút "Sync Cookie" trên Extension để chạy Crawler nữa. Họ BẮT BUỘC phải mở 1 Group Facebook và cuộn chuột xuống vài post để `background.js` âm thầm bắt gói tin chuẩn nhất từ Facebook rồi tự động gửi về Backend. Tuy nhiên, đây là hành vi BẮT BUỘC phải làm để vượt qua cơ chế bảo mật của GraphQL mới.
