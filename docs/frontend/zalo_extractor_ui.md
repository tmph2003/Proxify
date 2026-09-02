# Tài Liệu Cập Nhật: Phục hồi UI Zalo Extractor

## Tóm tắt thay đổi
- Thực hiện thiết kế lại toàn bộ mã JSX trong file `frontend/src/pages/Zalo.tsx`.
- Đồng bộ cấu trúc DOM HTML và gán các class CSS (được nạp từ `zalo.css` sang `index.css`) vào đúng vị trí tương ứng.
- Viết thêm logic lọc danh sách thành viên cục bộ (`memberSearch`, `filteredMembers`).

## Mục đích & Ý nghĩa
- **Khôi phục nguyên trạng (Pixel-Perfect):** Giao diện của công cụ Zalo Extractor ở phiên bản React tạm thời chỉ được dựng khung bằng inline CSS sơ sài. Lần cập nhật này khôi phục toàn bộ tính năng và giao diện đẹp như bản HTML cũ.
- **Tái tích hợp tính năng:** Nút "Lấy toàn bộ thành viên", xuất "CSV/JSON", và giao diện danh sách tiến trình quét (jobs) đã hiển thị rõ ràng thông qua CSS có sẵn.

## Mối liên hệ
- Hoạt động phụ thuộc vào CSS của `index.css` (đã gộp từ `zalo.css`).
- Tái sử dụng mượt mà state từ `useZalo.ts` hook.

## Rủi ro (Risks & Edge Cases)
- Logic render Avatar yêu cầu Data URL hoặc SVG fallback; nếu Data URL của avatar bị lỗi CORS, SVG mặc định với chữ cái đầu tiên sẽ được hiển thị đúng như nguyên mẫu.
