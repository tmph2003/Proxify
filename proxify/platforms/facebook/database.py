"""
FacebookDatabase — Facade class cho tất cả Facebook database operations.

Tự động tạo schema `facebook` và tất cả bảng khi khởi tạo.
"""
import logging

from proxify.database import pool as shared_pool
from .repository import (
    AuthorRepository,
    PostRepository,
    CommentRepository,
    ConfigRepository,
    SCHEMA,
)

logger = logging.getLogger("proxify.facebook")


class FacebookDatabase:
    """Facade cho Facebook database.
    
    Sử dụng schema `facebook` trong PostgreSQL.
    Tự động tạo schema + tables khi khởi tạo.
    """

    def __init__(self):
        self._pool = shared_pool

        # Repositories
        self.authors = AuthorRepository(self._pool)
        self.posts = PostRepository(self._pool)
        self.comments = CommentRepository(self._pool)
        self.config = ConfigRepository(self._pool)

        # Auto-init will be called manually to avoid blocking imports
        # self._init_schema()
        # self._init_tables()
        self._init_done = False

    def init_db(self):
        if not self._init_done:
            self._init_schema()
            self._init_tables()
            self._init_done = True

    def _init_schema(self) -> None:
        """Tạo schema `facebook` nếu chưa tồn tại."""
        self._pool.ensure_schema(SCHEMA)

    def _init_tables(self) -> None:
        """Tạo tất cả bảng trong schema `facebook`."""
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.authors (
                        id TEXT PRIMARY KEY,
                        name TEXT,
                        profile_url TEXT,
                        avatar_url TEXT,
                        typename TEXT,
                        first_seen TEXT,
                        last_seen TEXT
                    );
                """)
                
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.posts (
                        post_id TEXT PRIMARY KEY,
                        group_id TEXT,
                        group_name TEXT,
                        author_id TEXT,
                        author_name TEXT,
                        message_text TEXT,
                        permalink_url TEXT,
                        creation_time DOUBLE PRECISION,
                        creation_datetime TEXT,
                        attachments TEXT,
                        seo_title TEXT,
                        is_text_only INTEGER DEFAULT 0,
                        reaction_count INTEGER DEFAULT 0,
                        comment_count INTEGER DEFAULT 0,
                        share_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        raw_source_request_id INTEGER,
                        feedback_id TEXT,
                        is_active BOOLEAN DEFAULT NULL,
                        FOREIGN KEY (author_id) REFERENCES {SCHEMA}.authors(id)
                    );
                """)

                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.comments (
                        comment_id TEXT PRIMARY KEY,
                        post_id TEXT,
                        parent_comment_id TEXT,
                        author_id TEXT,
                        author_name TEXT,
                        body_text TEXT,
                        creation_time DOUBLE PRECISION,
                        creation_datetime TEXT,
                        reaction_count INTEGER DEFAULT 0,
                        reply_count INTEGER DEFAULT 0,
                        FOREIGN KEY (post_id) REFERENCES {SCHEMA}.posts(post_id),
                        FOREIGN KEY (author_id) REFERENCES {SCHEMA}.authors(id)
                    );
                """)

                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.attachments (
                        id SERIAL PRIMARY KEY,
                        post_id TEXT,
                        comment_id TEXT,
                        type TEXT,
                        url TEXT,
                        title TEXT,
                        description TEXT,
                        FOREIGN KEY (post_id) REFERENCES {SCHEMA}.posts(post_id)
                    );
                """)

                # Chỉ mục tăng tốc độ truy vấn
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_posts_group ON {SCHEMA}.posts(group_id);")
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_posts_author ON {SCHEMA}.posts(author_id);")
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_posts_created ON {SCHEMA}.posts(creation_time);")
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_comments_post ON {SCHEMA}.comments(post_id);")
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_comments_author ON {SCHEMA}.comments(author_id);")
                
                # Full-text search
                cur.execute(f"ALTER TABLE {SCHEMA}.posts ADD COLUMN IF NOT EXISTS search_vector tsvector;")
                cur.execute(f"ALTER TABLE {SCHEMA}.comments ADD COLUMN IF NOT EXISTS search_vector tsvector;")
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_posts_search ON {SCHEMA}.posts USING GIN(search_vector);")
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_comments_search ON {SCHEMA}.comments USING GIN(search_vector);")

                # Triggers for FTS
                cur.execute(f"""
                    CREATE OR REPLACE FUNCTION {SCHEMA}.update_posts_search_vector() RETURNS trigger AS $$
                    BEGIN
                        NEW.search_vector := 
                            setweight(to_tsvector('english', coalesce(NEW.message_text, '')), 'A') ||
                            setweight(to_tsvector('english', coalesce(NEW.author_name, '')), 'B') ||
                            setweight(to_tsvector('english', coalesce(NEW.seo_title, '')), 'C');
                        RETURN NEW;
                    END
                    $$ LANGUAGE plpgsql;
                """)
                
                cur.execute(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'posts_tsvectorupdate') THEN
                            CREATE TRIGGER posts_tsvectorupdate BEFORE INSERT OR UPDATE
                            ON {SCHEMA}.posts FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.update_posts_search_vector();
                        END IF;
                    END
                    $$;
                """)

                cur.execute(f"""
                    CREATE OR REPLACE FUNCTION {SCHEMA}.update_comments_search_vector() RETURNS trigger AS $$
                    BEGIN
                        NEW.search_vector := 
                            setweight(to_tsvector('english', coalesce(NEW.body_text, '')), 'A') ||
                            setweight(to_tsvector('english', coalesce(NEW.author_name, '')), 'B');
                        RETURN NEW;
                    END
                    $$ LANGUAGE plpgsql;
                """)
                
                cur.execute(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'comments_tsvectorupdate') THEN
                            CREATE TRIGGER comments_tsvectorupdate BEFORE INSERT OR UPDATE
                            ON {SCHEMA}.comments FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.update_comments_search_vector();
                        END IF;
                    END
                    $$;
                """)

                # Config table for user-provided settings (e.g. cookies)
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SCHEMA}.config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                logger.info(f"[FB] Tables initialized in schema '{SCHEMA}'.")
        except Exception as e:
            logger.error(f"[FB] Error initializing tables: {e}")

    def get_config(self, key: str, default: str = "") -> str:
        """Get a config value by key."""
        try:
            with self._pool.cursor(dict_cursor=True) as cur:
                cur.execute(
                    f"SELECT value FROM {SCHEMA}.config WHERE key = %s",
                    (key,),
                )
                row = cur.fetchone()
                return row["value"] if row else default
        except Exception as e:
            logger.error(f"[FB] Error reading config '{key}': {e}")
            return default

    def set_config(self, key: str, value: str) -> None:
        """Upsert a config value."""
        try:
            with self._pool.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.config (key, value, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, value),
                )
        except Exception as e:
            logger.error(f"[FB] Error saving config '{key}': {e}")

    @property
    def pool(self):
        """Access shared pool for advanced queries."""
        return self._pool

fb_db = FacebookDatabase()
