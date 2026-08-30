# Tài liệu: `proxify/platforms/zalo/__init__.py`

## 1. Tóm tắt tổng quan
File `__init__.py` nằm trong thư mục `zalo` là file khởi tạo cho Python sub-package `zalo` thuộc package `platforms`. Nó chuyên xử lý và xuất (export) một instance Singleton của `ZaloDatabase` ra ngoài toàn bộ package.

## 2. Mục đích & Ý nghĩa
- **Mục đích**: Chuyển đổi thư mục `zalo` thành một Python module, đồng thời cung cấp điểm truy cập database một cách dễ dàng và đồng nhất cho toàn hệ thống.
- **Ý nghĩa**: Các module khác khi cần thao tác với cơ sở dữ liệu Zalo chỉ cần import biến `zalo_db` từ `proxify.platforms.zalo`. Việc sử dụng mẫu thiết kế Singleton bằng file `__init__.py` đảm bảo chỉ có một instance kết nối DB duy nhất được tạo ra, giảm thiểu kết nối lãng phí tới PostgreSQL.

## 3. Mối liên hệ
- Nó import class `ZaloDatabase` từ module nội bộ `.database`.
- Mọi module cào dữ liệu, giao diện web UI hay worker của zalo (như `zalo/bot.py`) sẽ gọi trực tiếp đến `zalo_db` qua `from proxify.platforms.zalo import zalo_db`.

## 4. Rủi ro (Risks & Edge Cases)
- **Import Vòng (Circular Import)**: Vì file này khởi tạo instance `zalo_db`, nếu các module khác được nạp và import ngược lại `zalo_db` trong quá trình khởi tạo ứng dụng, dễ gây lỗi vòng lặp import.
- Không có mã logic xử lý nên không có rủi ro về hiệu suất hệ thống.

## 5. Chi tiết các Class và Hàm
- File này không định nghĩa class hay hàm nào mới.
- Nó chỉ bao gồm việc khai báo Singleton instance:
  - `zalo_db = ZaloDatabase()`
- Khai báo danh sách các đối tượng được export một cách rõ ràng:
  - `__all__ = ["zalo_db", "ZaloDatabase"]`
