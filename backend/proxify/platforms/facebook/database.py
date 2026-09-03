"""
FacebookDatabase & Repositories — Hợp nhất Data Access Layer cho nền tảng Facebook.

Bao gồm:
- SCHEMA: "facebook"
- AuthorRepository, PostRepository, CommentRepository, ConfigRepository
- FacebookDatabase: Facade class kết nối pool và tự động tạo bảng DDL.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from proxify.database import pool as shared_pool, DatabasePool

logger = logging.getLogger("proxify.facebook")

SCHEMA = "facebook"


class AuthorRepository:
    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def upsert(self, author: dict, cursor=None) -> None:
        if not author or not author.get("id"):
            return
        try:
            if cursor:
                self._do_upsert(cursor, author)
            else:
                with self._pool.cursor() as cur:
                    self._do_upsert(cur, author)
        except Exception as e:
            logger.error(f"[FB] Error upserting author {author.get('id')}: {e}")

    def _do_upsert(self, cur, author: dict):
        cur.execute(f"""
                    INSERT INTO {SCHEMA}.authors (id, name, profile_url, avatar_url, typename, first_seen, last_seen)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        name = COALESCE(NULLIF(EXCLUDED.name, ''), {SCHEMA}.authors.name),
                        profile_url = COALESCE(NULLIF(EXCLUDED.profile_url, ''), {SCHEMA}.authors.profile_url),
                        avatar_url = COALESCE(NULLIF(EXCLUDED.avatar_url, ''), {SCHEMA}.authors.avatar_url),
                        last_seen = CURRENT_TIMESTAMP
                """, (
                    author["id"],
                    author.get("name"),
                    author.get("profile_url"),
                    author.get("avatar_url"),
                    author.get("typename")
                ))


class PostRepository:
    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def upsert(self, post: dict, cursor=None) -> None:
        if not post or not post.get("post_id"):
            return
        try:
            if cursor:
                self._do_upsert(cursor, post)
            else:
                with self._pool.cursor() as cur:
                    self._do_upsert(cur, post)
        except Exception as e:
            logger.error(f"[FB] Error upserting post {post.get('post_id')}: {e}")

    def _do_upsert(self, cur, post: dict):
        raw_pid = post.get("post_id", "")
        fbid = post.get("feedback_id")
        permalink = post.get("permalink_url")

        from proxify.platforms.facebook.extractor import DataHelper
        canonical_pid = DataHelper.extract_canonical_post_id(raw_pid, feedback_id=fbid, permalink=permalink) or raw_pid

        author_id = post.get("author", {}).get("id") if post.get("author") else None
        author_name = post.get("author", {}).get("name") if post.get("author") else None
        
        creation_dt = None
        if post.get("creation_time"):
            try:
                creation_dt = datetime.fromtimestamp(int(post["creation_time"]), timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError, OSError):
                pass

        attachments = json.dumps(post.get("attachments", []), ensure_ascii=False) if post.get("attachments") else None

        cur.execute(f"""
            INSERT INTO {SCHEMA}.posts (
                post_id, group_id, group_numeric_id, group_name, author_id, author_name,
                message_text, permalink_url, creation_time, creation_datetime,
                attachments, seo_title, is_text_only,
                reaction_count, comment_count, share_count,
                raw_source_request_id, feedback_id, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (post_id) DO UPDATE SET
                message_text = EXCLUDED.message_text,
                permalink_url = COALESCE(EXCLUDED.permalink_url, {SCHEMA}.posts.permalink_url),
                creation_time = COALESCE(EXCLUDED.creation_time, {SCHEMA}.posts.creation_time),
                creation_datetime = COALESCE(EXCLUDED.creation_datetime, {SCHEMA}.posts.creation_datetime),
                feedback_id = COALESCE(EXCLUDED.feedback_id, {SCHEMA}.posts.feedback_id),
                reaction_count = GREATEST({SCHEMA}.posts.reaction_count, EXCLUDED.reaction_count),
                comment_count = GREATEST({SCHEMA}.posts.comment_count, EXCLUDED.comment_count),
                share_count = GREATEST({SCHEMA}.posts.share_count, EXCLUDED.share_count),
                is_active = TRUE,
                updated_at = CURRENT_TIMESTAMP
            WHERE
                {SCHEMA}.posts.message_text IS DISTINCT FROM EXCLUDED.message_text
                OR {SCHEMA}.posts.reaction_count < EXCLUDED.reaction_count
                OR {SCHEMA}.posts.comment_count < EXCLUDED.comment_count
                OR {SCHEMA}.posts.share_count < EXCLUDED.share_count
                OR {SCHEMA}.posts.feedback_id IS NULL AND EXCLUDED.feedback_id IS NOT NULL
                OR {SCHEMA}.posts.is_active IS DISTINCT FROM TRUE
        """, (
            canonical_pid,
            post.get("group_id"),
            post.get("group_numeric_id"),
            post.get("group_name"),
            author_id,
            author_name,
            post["message_text"],
            post.get("permalink_url"),
            post.get("creation_time"),
            creation_dt,
            attachments,
            post.get("seo_title"),
            int(post.get("is_text_only", 0)),
            post.get("reaction_count", 0),
            post.get("comment_count", 0),
            post.get("share_count", 0),
            post.get("request_id"),
            post.get("feedback_id"),
        ))


class CommentRepository:
    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def upsert(self, comment: dict, post_id: str, cursor=None) -> None:
        if not comment or not comment.get("comment_id"):
            return
        try:
            if cursor:
                self._do_upsert(cursor, comment, post_id)
            else:
                with self._pool.cursor() as cur:
                    self._do_upsert(cur, comment, post_id)
        except Exception as e:
            logger.error(f"[FB] Error upserting comment {comment.get('comment_id')}: {e}")

    def _do_upsert(self, cur, comment: dict, post_id: str):
        author_id = comment.get("author", {}).get("id") if comment.get("author") else None
        author_name = comment.get("author", {}).get("name") if comment.get("author") else None
        
        creation_dt = None
        if comment.get("creation_time"):
            try:
                creation_dt = datetime.fromtimestamp(int(comment["creation_time"]), timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError, OSError):
                pass

        cur.execute(f"""
                    INSERT INTO {SCHEMA}.comments (
                        comment_id, post_id, parent_comment_id,
                        author_id, author_name, body_text,
                        creation_time, creation_datetime,
                        reaction_count, reply_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (comment_id) DO UPDATE SET
                        post_id = COALESCE(EXCLUDED.post_id, {SCHEMA}.comments.post_id),
                        parent_comment_id = COALESCE(EXCLUDED.parent_comment_id, {SCHEMA}.comments.parent_comment_id),
                        body_text = COALESCE(NULLIF(EXCLUDED.body_text, ''), {SCHEMA}.comments.body_text),
                        reaction_count = GREATEST({SCHEMA}.comments.reaction_count, EXCLUDED.reaction_count),
                        reply_count = GREATEST({SCHEMA}.comments.reply_count, EXCLUDED.reply_count)
                """, (
                    comment["comment_id"],
                    post_id,
                    comment.get("parent_comment_id"),
                    author_id,
                    author_name,
                    comment["body_text"],
                    comment.get("creation_time"),
                    creation_dt,
                    comment.get("reaction_count", 0),
                    comment.get("reply_count", 0)
                ))


class ConfigRepository:
    def __init__(self, pool: DatabasePool):
        self._pool = pool

    def set(self, key: str, value: str) -> None:
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.config (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """, (key, value))
        except Exception as e:
            logger.error(f"[FB] Error setting config {key}: {e}")

    def get(self, key: str) -> Optional[str]:
        try:
            with self._pool.cursor() as cur:
                cur.execute(f"SELECT value FROM {SCHEMA}.config WHERE key = %s", (key,))
                row = cur.fetchone()
                if row:
                    return row[0]
        except Exception as e:
            logger.error(f"[FB] Error getting config {key}: {e}")
        return None


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
                
                # Auto-heal NULL post_id in comments
                try:
                    cur.execute(f"""
                        UPDATE {SCHEMA}.comments
                        SET post_id = substring(convert_from(decode(comment_id, 'base64'), 'UTF-8') from 'comment:([0-9]+)_')
                        WHERE post_id IS NULL AND comment_id IS NOT NULL;
                    """)
                except Exception as e:
                    logger.debug(f"[FB] Auto-heal comments skipped: {e}")
                
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
