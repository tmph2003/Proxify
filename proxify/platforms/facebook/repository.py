import logging
from typing import Optional
import json
from datetime import datetime, timezone, timedelta

from proxify.database import DatabasePool

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
            post["post_id"],
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
                        post_id = COALESCE({SCHEMA}.comments.post_id, EXCLUDED.post_id),
                        parent_comment_id = COALESCE({SCHEMA}.comments.parent_comment_id, EXCLUDED.parent_comment_id),
                        body_text = EXCLUDED.body_text,
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
