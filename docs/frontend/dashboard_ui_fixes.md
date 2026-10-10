# Tài Liệu Cập Nhật: Sửa Lỗi Hiển Thị UI Trong Dashboard.tsx

## Tóm tắt thay đổi
- Chỉnh sửa file `frontend/src/pages/Dashboard.tsx`.
- Sửa lỗi hiển thị `id = 0` (đổi từ `{req.id}` thành `{req.id || ''}`).
- Sửa lỗi hiển thị số `0` dư thừa ở khu vực Detail Panel (đổi từ `{selectedData.is_graphql && ...}` thành `{!!selectedData.is_graphql && ...}`).

## Mục đích & Ý nghĩa
- **Mục đích**: Loại bỏ các lỗi hiển thị UI ngớ ngẩn (số 0 dư thừa).
- **Ý nghĩa**:
    - Khi có một request mới (chưa có ID thực trong database vì đang xếp hàng hoặc ID = 0), nó sẽ không hiển thị số 0 ở cột `#` nữa, mà thay vào đó là ô trống cho đến khi nhận được bản cập nhật ID.
    - React có đặc thù khi render biểu thức boolean: nếu giá trị là `0` (số nguyên), React sẽ in thẳng `0` ra màn hình thay vì bỏ qua như `false`. Do `is_graphql` trả về từ SQLite là 0 hoặc 1, việc dùng toán tử `!!` sẽ ép kiểu biến đó về boolean thuần tuý, ngăn chặn React render số 0.

## Mối liên hệ
- Liên quan đến cách React DOM xử lý toán tử lô-gic (`&&`).
- Liên quan đến dữ liệu trả về từ SQLite (`backend/proxify/dashboard.py`).

## Rủi ro (Risks & Edge Cases)
- Việc dùng `|| ''` chỉ là giải pháp che giấu ID=0. Nó có thể làm cho cột `#` trống tạm thời (nhấp nháy) trong vài ms trước khi bản tin WebSocket `update_id` được gửi tới để cập nhật ID thực. Đây là đặc tả của hệ thống chứ không hẳn là bug lớn, nhưng có thể ảnh hưởng nhỏ đến trải nghiệm nếu latency cao.
