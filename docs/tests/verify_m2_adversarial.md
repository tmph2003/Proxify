# Tài liệu Kiểm thử Đối kháng Milestone 2: Vectorized DB Batch Flush & Zero-Copy Streaming

## 1. Tóm tắt thay đổi
Tạo bộ kiểm thử đối kháng thực nghiệm `scripts/verify_m2_adversarial.py` nhằm xác thực độc lập và nghiêm ngặt hai trụ cột cốt lõi của Milestone 2 theo chỉ đạo trong `DISPATCH.md`:
1. Vectorized Database Multi-Row INSERT vào PostgreSQL dưới tải cao và nhiều kích thước lô (batch sizes) khác nhau.
2. Kiểm tra tính toàn vẹn và không sao chép bộ nhớ (zero-copy) của luồng payload nhị phân đa megabyte (lên tới 25 MB).

## 2. Mục đích & Ý nghĩa
- **Kiểm thử Database Vectorization**: Mã nguồn `storage.rs` đã chuyển từ việc chèn từng bản ghi đơn lẻ sang câu lệnh SQL đa dòng động `INSERT INTO public.requests (...) VALUES ($1, ...), ($18, ...)`. Bộ kiểm thử này trực tiếp kiểm tra việc chèn các lô có kích thước bất kỳ (1, 7, 10, 33, 50, 99, 100, 200 dòng), kiểm tra giới hạn tham số, và đối chiếu 100% từng trường dữ liệu được lưu trong PostgreSQL (18 trường dữ liệu/bản ghi) với giá trị ban đầu.
- **Kiểm thử Zero-Copy Binary Streaming**: Kiểm tra việc phân mảnh buffer nhị phân lên đến 25MB và truyền phát qua nhiều luồng đồng thời mà không làm biến dạng dữ liệu (kiểm chứng bằng băm mật mã SHA-256).

## 3. Mối liên hệ
- Liên kết trực tiếp với tầng Infrastructure `crates/proxify-core/src/storage.rs` (PostgreSQL batch flusher).
- Liên kết với tầng Domain `crates/proxify-sdk/src/lib.rs` (`FlowRequest`/`FlowResponse` zero-copy payload).
- Tương tác với dịch vụ cơ sở dữ liệu `proxify_db` (PostgreSQL 15) trên cổng 5432.

## 4. Rủi ro (Risks & Edge Cases)
- **Giới hạn số lượng tham số trong PostgreSQL**: PostgreSQL giới hạn tối đa 65,535 tham số trong một câu truy vấn có tham số. Với mỗi bản ghi gồm 18 tham số, kích thước lô tối đa cho phép là $\lfloor 65535 / 18 \rfloor = 3640$ bản ghi. Kích thước mặc định của hệ thống là 100 ($1800$ tham số), hoàn toàn an toàn và nằm sâu dưới ngưỡng ranh giới này.
- **Xung đột khóa và tranh chấp kết nối dưới tải đồng thời**: Cần đảm bảo connection pool của PostgreSQL có đủ số lượng kết nối cho các worker threads khi flush đồng thời mà không bị cạn kiệt (pool exhaustion).
