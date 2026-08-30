# Tài liệu: Sửa lỗi xung đột luồng (Cross-Thread Asyncio) khiến UI không cập nhật được trạng thái LIVE

## Tóm tắt thay đổi
- Sửa hàm `_deferred_broadcast` trong `proxify/server_v2.py`. Thay vì luôn gọi `asyncio.create_task(coro)`, hệ thống giờ đây đã chụp lại `event loop` chính ở thời điểm khởi tạo (`loop = asyncio.get_running_loop()`). 
- Khi có bất kỳ sự kiện nào cần gửi lên Dashboard, hàm sẽ tự kiểm tra xem mình có đang chạy trong `event loop` hay không. Nếu không (nghĩa là đang bị gọi từ một luồng background như `AsyncWriterWorker` của Database), nó sẽ dùng `asyncio.run_coroutine_threadsafe(coro, loop)` để đưa lệnh về luồng chính một cách an toàn.

## Mục đích & Ý nghĩa
- Khắc phục triệt để lỗi "LIVE" bị kẹt vĩnh viễn trên UI. Mặc dù ở bản vá trước chúng ta đã đăng ký lắng nghe sự kiện `db_row_created`, nhưng sự kiện này lại được bắn ra (publish) từ một luồng ngầm (Background Thread) thực hiện ghi vào PostgreSQL.
- Khi luồng ngầm này gọi `asyncio.create_task()`, Python đã âm thầm ném ra lỗi `RuntimeError: no running event loop` và lỗi này bị EventBus "nuốt" mất. Giải pháp mới giúp việc gọi websocket broadcast từ luồng ghi DB trở nên hoàn toàn thread-safe (an toàn luồng).

## Mối liên hệ
- Liên quan đến module `server_v2.py`, hệ thống `EventBus` (`proxify/core/events.py`) và `AsyncWriterWorker` (`proxify/storage/workers.py`).

## Rủi ro (Risks & Edge Cases)
- Code đã được thiết kế để `fallback` an toàn: Cố gắng dùng `create_task` trước, nếu bắt được ngoại lệ (Exception) thì mới đổi sang phương thức thread-safe, nên rủi ro hiệu năng hay gián đoạn là không có.
