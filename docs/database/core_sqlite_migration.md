# Database Migration: PostgreSQL → SQLite

## Tóm tắt thay đổi
Migration toàn bộ database layer của Proxify từ PostgreSQL sang SQLite để hỗ trợ đóng gói standalone .exe (không cần external database server).

## Mục đích & Ý nghĩa
- **Standalone deployment**: Loại bỏ dependency vào PostgreSQL server, cho phép Proxify chạy hoàn toàn độc lập.
- **Single-file database**: SQLite tạo file `proxify.db` ngay tại thư mục chạy, không cần setup.
- **Native compilation**: Loại bỏ `psycopg2` (C extension phức tạp) và `asyncpg` (cần libpq), giúp Nuitka build dễ hơn.

## Các file đã thay đổi

### Core Database Layer
| File | Thay đổi |
|---|---|
| `proxify/database/connection.py` | Rewrite hoàn toàn: `psycopg2.ThreadedConnectionPool` → `sqlite3.connect()` + WAL mode; tự động định vị `proxify.db` cạnh `sys.executable` khi biên dịch Nuitka |
| `proxify/database/__init__.py` | Giữ nguyên API singleton, chỉ update import |
| `proxify/core/database.py` | Rewrite hoàn toàn: `asyncpg.create_pool()` → `aiosqlite.connect()` + `_ConnectionWrapper` (sửa `acquire()` thành sync factory trả về async context manager tương thích `compiled_coroutine` của Nuitka) |
| `proxify/core/eventbus.py` | Migrate: `asyncpg.executemany($1, $2)` → `aiosqlite.executemany(?, ?)` |
| `proxify/core/worker.py` | Migrate: `ANY($1::bigint[])` → `IN (...)`, schema prefix removed |

### Traffic Storage Layer
| File | Thay đổi |
|---|---|
| `proxify/core/traffic_storage/repository.py` | Rewrite hoàn toàn: FTS5 thay tsvector, triggers thay plpgsql functions |
| `proxify/core/traffic_storage/workers.py` | Adapt: bỏ `pool.release_connection()` pattern, SQLite single-connection |
| `proxify/core/traffic_storage/__init__.py` | Không thay đổi logic, chỉ inherit từ rewritten components |

### Server & Config
| File | Thay đổi |
|---|---|
| `proxify/server.py` | DSN → file path, bỏ PostgreSQL URL |
| `proxify/sdk/context.py` | Update docstrings, thêm `get_db_manager()` |
| `requirements.txt` | Bỏ `psycopg2-binary`, `asyncpg`; thêm `aiosqlite` |
| `pyproject.toml` | Tương tự requirements.txt |

## Mối liên hệ
- **Extensions tùy chọn (`private/extensions/<ext_id>`)**: Nếu có extension ngoài sử dụng PostgreSQL schema riêng, cần migrate tương tự (bỏ schema prefix sang table prefix)
- **Dashboard** (`dashboard.py`): Dùng `asyncio.to_thread()` wrap sync calls → không cần sửa
- **SDK Context** (`sdk/context.py`): `get_sync_db_pool()` và `get_async_db_pool()` trả về SQLite objects thay vì PostgreSQL

## Chi tiết kỹ thuật quan trọng

### 1. Full-Text Search: tsvector → FTS5
**Trước (PostgreSQL)**:
- Column `search_vector tsvector` trong bảng `requests`
- GIN index trên `search_vector`
- plpgsql trigger function `update_search_vector()` với `setweight()` + `to_tsvector()`
- Query: `search_vector @@ plainto_tsquery('english', %s)`

**Sau (SQLite FTS5)**:
- Virtual table `requests_fts` riêng biệt
- SQLite triggers `requests_ai`, `requests_ad` sync data
- Query: `id IN (SELECT rowid FROM requests_fts WHERE requests_fts MATCH ?)`
- Tokenizer: `porter unicode61` (tương đương `english` dictionary trong PG)

### 2. Connection Model: Pool → Single Connection
**Trước**: `ThreadedConnectionPool(min=1, max=5)` + `asyncpg.create_pool(min=5, max=20)`
**Sau**: Single `sqlite3.connect()` + `threading.Lock` (sync) và `aiosqlite.connect()` + `asyncio.Lock` (async)

**Lý do**: SQLite chỉ hỗ trợ 1 writer tại 1 thời điểm. WAL mode cho phép concurrent reads.

### 3. Schema Namespacing: Removed
**Trước**: `core.raw_payloads` (hoặc `<ext_schema>.<table>`)
**Sau**: `core_raw_payloads` (hoặc `<ext_prefix>_<table>` bằng tiền tố tên bảng)

### 4. Parameter Style Migration
| Driver | Style | Ví dụ |
|---|---|---|
| psycopg2 | `%s` | `WHERE id = %s` |
| asyncpg | `$1, $2` | `WHERE id = $1` |
| sqlite3 | `?` | `WHERE id = ?` |

## Rủi ro (Risks & Edge Cases)

### Rủi ro Cao
- **Concurrent writes under load**: SQLite WAL mode chịu ~50 concurrent writers. Nếu Proxify capture > 100 requests/second liên tục, có thể bị `database is locked` errors. Mitigation: `busy_timeout=5000` + write queue batching.

### Rủi ro Trung bình  
- **FTS5 search quality**: SQLite FTS5 không có weighted search (`setweight`) như PostgreSQL tsvector. Kết quả full-text search có thể khác (ít chính xác hơn cho ranking).
- **No partial indexes**: PostgreSQL `WHERE processed = FALSE` partial index → SQLite tạo full index, tốn thêm disk space.

### Rủi ro Thấp
- **GREATEST() → MAX()**: Semantics giống nhau, không có risk.
- **JSON storage as TEXT**: SQLite 3.38+ có JSON functions, nhưng không có JSONB indexing. Truy vấn JSON sẽ chậm hơn PostgreSQL nếu cần filter by JSON field.
