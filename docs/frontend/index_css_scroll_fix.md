# Tài liệu thay đổi: `frontend/src/index.css` (Fix lỗi Scroll bảng Request)

## 1. Tóm tắt thay đổi
- Khôi phục selector CSS `.list-body` tại `frontend/src/index.css` (trước đó bị lỗi gộp chuỗi thành `.list-#root { ... } body { ... }`).
- Bổ sung thuộc tính `min-height: 0;` kết hợp với `flex: 1;` và `overflow-y: auto;` cho `.list-body`.

## 2. Mục đích & Ý nghĩa
- **Giải quyết lỗi không cuộn (scroll) được danh sách Request:** Khi `.list-body` bị mất selector do lỗi cú pháp trước đó, container chứa các dòng request không có `overflow-y: auto` và `flex: 1`, dẫn đến việc bị cắt phần tràn bởi `.request-list { overflow: hidden }` mà không sinh ra thanh cuộn dọc.
- Đảm bảo chuẩn Flexbox nesting (`min-height: 0`) giúp container con co giãn đúng trong khung nhìn `100vh`.

## 3. Mối liên hệ
- **Liên kết trực tiếp:** Component [`DashboardPage`](file:///c:/Users/Administrator/Desktop/MyAim/Proxify/frontend/src/pages/Dashboard.tsx) sử dụng `<div className="list-body" ref={listBodyRef}>` để hiển thị danh sách request thu thập qua WebSocket và thực hiện auto-scroll.
- **Ảnh hưởng:** Khôi phục khả năng cuộn chuột và thanh scrollbar tuỳ chỉnh (`.list-body::-webkit-scrollbar`) trên trang Dashboard chính, đồng thời xóa bỏ rule `body` bị ghi đè ngoài ý muốn ở dòng 749.

## 4. Rủi ro (Risks & Edge Cases)
- **Auto-scroll UX:** Trong `Dashboard.tsx`, khi nút `⬇ Auto-scroll` đang bật (`autoScroll = true`), mỗi khi có gói tin WebSocket mới bắn về (`filteredRequests` thay đổi), `useEffect` sẽ kéo `listBodyRef.current.scrollTop = 0`. Nếu lưu lượng mạng liên tục đổ về với tần suất cao mà người dùng muốn cuộn xuống xem các gói tin cũ hơn, họ cần bấm tắt nút **Auto-scroll** trên thanh công cụ để không bị kéo ngược lên đầu bảng.
