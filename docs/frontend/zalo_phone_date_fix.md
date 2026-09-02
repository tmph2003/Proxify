# Tài Liệu Cập Nhật: Sửa định dạng SĐT và Cột Cập Nhật Zalo

## Tóm tắt thay đổi
- Chỉnh sửa `frontend/src/pages/Zalo.tsx`:
  - Lọc bỏ dấu `+` ở đầu số điện thoại bằng regex `m.phone.replace(/^\+/, '')`.
  - Fix lỗi "Invalid Date" ở cột Cập nhật bằng cách bỏ phép nhân `* 1000` với chuỗi ngày tháng ISO.

## Mục đích & Ý nghĩa
- **Làm sạch dữ liệu:** Zalo đôi khi trả về SĐT có chứa mã quốc gia dạng `+84`, đôi khi chỉ là `84`. Việc loại bỏ dấu `+` giúp toàn bộ danh sách được căn chỉnh đồng nhất và đẹp mắt hơn.
- **Sửa lỗi hiển thị:** Chuỗi ngày tháng ISO được parse trực tiếp bởi `new Date()`, không cần nhân 1000 (chỉ áp dụng cho Unix timestamp).

## Mối liên hệ
- Lấy trực tiếp dữ liệu từ Context. Backend API không thay đổi.

## Rủi ro (Risks & Edge Cases)
- Dữ liệu nguyên thủy trong database không bị thay đổi, chỉ có ở phía giao diện (Frontend) số điện thoại được làm sạch (loại bỏ `+`) trước khi in ra bảng.
