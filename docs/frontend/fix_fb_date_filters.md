# Cập nhật: Sửa lỗi bộ lọc "Từ ngày" & "Đến ngày" không hoạt động ở giao diện Facebook

## Tóm tắt thay đổi
- Chỉnh sửa `frontend/src/hooks/useFacebook.ts`: Thêm `startDateFilter` và `endDateFilter` vào danh sách biến export của hook `useFacebook`. Đồng thời khởi tạo giá trị mặc định của chúng từ `localStorage` để giữ nguyên trạng thái khi reload.
- Chỉnh sửa `frontend/src/pages/Facebook.tsx`:
  - Loại bỏ các state `startDate`, `endDate` cục bộ không cần thiết.
  - Thay thế trực tiếp giá trị của 2 input "Từ ngày" và "Đến ngày" bằng `startDateFilter` và `endDateFilter` lấy từ hook `useFacebook`.
  - Sửa lại hàm `onChange` của 2 thẻ `<input type="date">` để trực tiếp gọi `setStartDateFilter` / `setEndDateFilter` và lưu vào `localStorage`.

## Mục đích & Ý nghĩa
- **Vấn đề:** Khi người dùng chọn "Từ ngày" hoặc "Đến ngày" ở giao diện Facebook Extractor, bảng dữ liệu bên phải không được lọc theo ngày.
- **Nguyên nhân:** Trong lần viết lại giao diện React trước, bộ lọc ngày (`startDateFilter`, `endDateFilter`) của API table fetcher đã bị tách rời khỏi state `startDate`, `endDate` của các input (vốn chỉ được dùng khi bấm nút "Bắt đầu thu thập"). Do vậy việc thay đổi input không làm thay đổi biến filter để trigger tính năng tự động tải lại bảng.
- **Cách khắc phục:** Đồng nhất 2 state này làm một. Khi input ngày thay đổi, nó sẽ thay đổi `startDateFilter` / `endDateFilter`. Vì 2 biến này nằm trong mảng dependency (deps) của `useCallback(loadData, [...])`, hàm load dữ liệu sẽ tự động được fetch lại, lọc bảng ngay lập tức giống như UI HTML gốc.

## Mối liên hệ
- Ảnh hưởng đến việc lọc dữ liệu trên Facebook Dashboard và việc lưu trữ cấu hình crawl cuối cùng.

## Rủi ro (Risks & Edge Cases)
- Hàm `onChange` có thể fetch API liên tục nếu người dùng gõ ngày tháng (thay vì bấm lịch chọn). Tuy nhiên thẻ `<input type="date">` mặc định hạn chế việc gõ tay nhiều, chủ yếu thao tác chọn lịch nên tác động về hiệu năng (API debounce) không đáng kể.
