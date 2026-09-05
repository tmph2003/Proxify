"""
Comment Crawler — Facebook Comment & Metrics Extraction
=========================================================
Domain crawler for Facebook post comments and reaction metrics.

Pattern: **Delegation (ch36)** — ``CommentCrawler`` HAS-A ``CrawlerEngine``
(injected via Constructor Injection ch35).

Responsibilities:
- Paginated comment crawl (CommentsListComponentsPaginationQuery)
- Reply crawl (Depth1CommentsListPaginationQuery)
- Comment template synthesis
- HTML page scraping fallback for comments
- Post metrics extraction (reaction_count, comment_count)
- Post refresh / metrics update
"""

import asyncio
import base64
import json
import logging
import re
import time
import urllib.parse
from typing import Optional

from proxify.database import pool as shared_pool
from proxify.utils.stealth import StealthRequestError
from proxify.utils.circuit_breaker import crawl_breaker
from proxify.platforms.facebook.stealth import (
    SessionStateManager,
    comment_delay,
)
from proxify.platforms.facebook.auth import (
    extract_templates,
    get_saved_tokens,
    TENANT_COOKIES,
    TENANT_TEMPLATES,
    IN_MEMORY_TEMPLATES,
    IN_MEMORY_COOKIES,
)
from proxify.platforms.facebook.extractor import extract_from_responses, DataHelper

logger = logging.getLogger("proxify.facebook.crawlers.comment")

GRAPHQL_ENDPOINT = "https://www.facebook.com/api/graphql/"
CONCURRENCY_LIMIT = 1


# ─── Recursive Comment ID Finder (Pure Function) ────────────────────

def find_comment_ids(obj) -> list[str]:
    """Recursively find comment IDs in a parsed JSON object."""
    ids: list[str] = []
    if isinstance(obj, dict):
        if "comment_id" in obj and isinstance(obj["comment_id"], str):
            ids.append(obj["comment_id"])
        elif (
            "id" in obj
            and isinstance(obj["id"], str)
            and len(obj["id"]) > 10
            and obj.get("__typename") == "Comment"
        ):
            ids.append(obj["id"])
        for v in obj.values():
            ids.extend(find_comment_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            ids.extend(find_comment_ids(v))
    return ids


# ─── CommentCrawler ─────────────────────────────────────────────────

class CommentCrawler:
    """Facebook comment & metrics crawler — Delegation target (ch36).

    HAS-A ``CrawlerEngine`` (composition, NOT inheritance).
    Injected via Constructor Injection (ch35).

    Responsibilities:
    - Paginated comment crawl via GraphQL
    - Reply fetching
    - HTML page scraping fallback
    - Post metrics extraction and refresh
    - Comment template synthesis
    """

    def __init__(self, engine) -> None:
        self.engine = engine

    # ── Static Helpers ───────────────────────────────────────────────

    @staticmethod
    def extract_feedback_ids(resp_text: str) -> list[str]:
        """Extract unique feedback IDs from stories in the response."""
        ids: list[str] = []
        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                for story in DataHelper.extract_nodes(obj, "Story"):
                    feedback = story.get("feedback")
                    if isinstance(feedback, dict) and feedback.get("id"):
                        ids.append(feedback["id"])
            except Exception:
                pass
        return list(set(ids))

    @staticmethod
    def extract_comment_page_info(
        resp_text: str, current_direction: str = "after"
    ) -> tuple[Optional[str], bool, str]:
        """Extract cursor, has_more, and direction for comment pagination."""
        try:
            for line in resp_text.split("\n"):
                if not line.strip():
                    continue
                data = json.loads(line)
                nodes = DataHelper.extract_nodes(data, "Feedback")
                for fb in nodes:
                    comments_obj = (
                        fb.get("comment_rendering_instance_for_feed_location", {}).get("comments")
                        or fb.get("comments")
                    )
                    if isinstance(comments_obj, dict) and "page_info" in comments_obj:
                        pi = comments_obj["page_info"]
                        if current_direction == "after":
                            if pi.get("has_next_page") and pi.get("end_cursor"):
                                return pi.get("end_cursor"), True, "after"
                            return None, False, "after"
                        elif current_direction == "before":
                            if pi.get("has_previous_page") and pi.get("start_cursor"):
                                return pi.get("start_cursor"), True, "before"
                            return None, False, "before"
                        else:
                            if pi.get("has_next_page") and pi.get("end_cursor"):
                                return pi.get("end_cursor"), True, "after"
                            elif pi.get("has_previous_page") and pi.get("start_cursor"):
                                return pi.get("start_cursor"), True, "before"
        except Exception:
            pass
        return None, False, ""

    @staticmethod
    def parse_comment_ids(resp_text: str) -> list[str]:
        """Parse comment IDs from a GraphQL response."""
        comment_ids: list[str] = []
        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                comment_ids.extend(find_comment_ids(obj))
            except Exception:
                pass
        return comment_ids

    @staticmethod
    def extract_metrics_from_html(
        html: str,
    ) -> tuple[Optional[int], Optional[int], Optional[str], bool, str]:
        """Extract reaction_count, comment_count, feedback_id, is_active from Facebook post HTML.

        Returns:
            (reaction_count, comment_count, feedback_id, is_active, status_reason)
        """
        if not html:
            return None, None, None, True, "empty_response"

        if (
            "Bạn hiện không xem được nội dung này" in html
            or "This content isn't available right now" in html
            or "The link you followed may be broken" in html
        ):
            return None, None, None, False, "unavailable"

        reaction_count = None
        comment_count = None
        feedback_id = None
        is_active = True

        # 1. Parse from embedded JSON <script type="application/json">
        scripts = re.findall(
            r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL
        )
        for s_text in scripts:
            if '"reaction_count"' in s_text or '"comment_rendering_instance"' in s_text:
                try:
                    data = json.loads(s_text)
                    stories = DataHelper.extract_nodes(data, "Story")
                    for s in stories:
                        fb = s.get("feedback")
                        if isinstance(fb, dict) and fb.get("id") and str(fb["id"]).startswith("ZmVlZ"):
                            feedback_id = fb["id"]

                        ufi = DataHelper.find_key(s, "comet_ufi_summary_and_actions_renderer")
                        if ufi and isinstance(ufi[0], dict):
                            ufi_fb = ufi[0].get("feedback", {})
                            if isinstance(ufi_fb, dict):
                                rc = ufi_fb.get("reaction_count")
                                if isinstance(rc, dict) and "count" in rc and isinstance(rc["count"], int):
                                    reaction_count = rc["count"]
                                elif isinstance(rc, int):
                                    reaction_count = rc

                        cri = DataHelper.find_key(s, "comment_rendering_instance")
                        if cri and isinstance(cri[0], dict):
                            tc = cri[0].get("comments", {}).get("total_count")
                            if isinstance(tc, int):
                                comment_count = tc
                except Exception:
                    pass

        # 2. Fallback regex patterns
        if reaction_count is None:
            m_rc = re.findall(r'"reaction_count":\s*\{\s*"count":\s*(\d+)', html)
            if m_rc:
                reaction_count = int(m_rc[0])

        if comment_count is None:
            m_cri = re.findall(r'"comment_rendering_instance":.*?total_count":\s*(\d+)', html)
            if m_cri:
                comment_count = int(m_cri[0])
            else:
                m_tc = re.findall(r'"total_comment_count":\s*(\d+)', html)
                if m_tc:
                    comment_count = int(m_tc[0])

        if not feedback_id:
            m_fb = re.search(r'"feedback"\s*:\s*\{\s*"id"\s*:\s*"(ZmVlZ[^"]+)"', html)
            if not m_fb:
                m_fb = re.search(r'"feedback_id"\s*:\s*"(ZmVlZ[^"]+)"', html)
            if m_fb:
                feedback_id = m_fb.group(1)

        status = "ok" if (reaction_count is not None or comment_count is not None) else "no_metrics"
        return reaction_count, comment_count, feedback_id, is_active, status

    @staticmethod
    def parse_metrics_from_graphql(
        resp_text: str,
    ) -> tuple[Optional[int], Optional[int], Optional[str], bool]:
        """Parse reaction_count, comment_count, feedback_id, is_active from GraphQL response."""
        reaction_count = None
        comment_count = None
        feedback_id = None
        is_active = True

        for line in resp_text.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                errors = obj.get("errors")
                if errors and isinstance(errors, list):
                    for err in errors:
                        msg = str(err.get("message", "")).lower()
                        if "available" in msg or "permission" in msg or "does not exist" in msg or "không xem được" in msg:
                            return None, None, None, False

                data = obj.get("data", {})
                if not data:
                    if errors:
                        return None, None, None, False
                    continue

                if "node" in data and data.get("node") is None and not data.get("node_v2") and not data.get("feedback"):
                    return None, None, None, False

                candidate_roots = []
                for k in ["node", "node_v2", "feedback", "story"]:
                    val = data.get(k)
                    if isinstance(val, dict):
                        candidate_roots.append(val)
                if not candidate_roots:
                    candidate_roots.append(data)

                for root in candidate_roots:
                    # 1. Feedback ID
                    f_id = root.get("id")
                    if f_id and isinstance(f_id, str) and (f_id.startswith("ZmVlZ") or "feedback" in f_id.lower()):
                        feedback_id = f_id
                    else:
                        fb_nodes = DataHelper.find_key(root, "feedback")
                        for fb in fb_nodes:
                            if isinstance(fb, dict) and fb.get("id") and str(fb["id"]).startswith("ZmVlZ"):
                                feedback_id = fb["id"]
                                break

                    # 2. Reaction Count
                    ufi_renderers = DataHelper.find_key(root, "comet_ufi_summary_and_actions_renderer")
                    for ufi in ufi_renderers:
                        if isinstance(ufi, dict):
                            ufi_fb = ufi.get("feedback", {})
                            if isinstance(ufi_fb, dict):
                                rc = ufi_fb.get("reaction_count")
                                if isinstance(rc, dict) and "count" in rc and isinstance(rc["count"], int):
                                    reaction_count = rc["count"]
                                    break
                                elif isinstance(rc, int):
                                    reaction_count = rc
                                    break

                                actions = ufi_fb.get("adaptive_ufi_action_renderers", [])
                                for act in actions:
                                    if isinstance(act, dict):
                                        act_fb = act.get("feedback", {})
                                        rc2 = act_fb.get("reaction_count") if isinstance(act_fb, dict) else None
                                        if isinstance(rc2, dict) and "count" in rc2 and isinstance(rc2["count"], int):
                                            reaction_count = rc2["count"]
                                            break

                    if reaction_count is None:
                        r_counts = DataHelper.find_key(root, "reaction_count")
                        counts = []
                        for c in r_counts:
                            if isinstance(c, dict) and "count" in c and isinstance(c["count"], int):
                                counts.append(c["count"])
                            elif isinstance(c, int):
                                counts.append(c)
                        if counts:
                            reaction_count = max(counts)

                    # 3. Comment Count
                    cri_list = DataHelper.find_key(root, "comment_rendering_instance") or DataHelper.find_key(root, "comment_rendering_instance_for_feed_location")
                    for cri in cri_list:
                        if isinstance(cri, dict):
                            comments_obj = cri.get("comments", {})
                            if isinstance(comments_obj, dict):
                                tc = comments_obj.get("total_count")
                                if isinstance(tc, int):
                                    comment_count = tc
                                    break
                                c_cnt = comments_obj.get("count")
                                if isinstance(c_cnt, int):
                                    comment_count = c_cnt
                                    break

                    if comment_count is None:
                        c_counts = DataHelper.find_key(root, "total_comment_count") + DataHelper.find_key(root, "total_count")
                        valid_counts = [c for c in c_counts if isinstance(c, int)]
                        if valid_counts:
                            comment_count = max(valid_counts)

            except Exception:
                pass

        return reaction_count, comment_count, feedback_id, is_active

    # ── Template Synthesis ───────────────────────────────────────────

    def synthesize_comment_template(
        self,
        feedback_id: str,
        feed_tpl: Optional[dict] = None,
    ) -> dict:
        """Generate a synthetic CommentsListComponentsPaginationQuery template."""
        base_form = (
            feed_tpl.get("form_data", {}).copy()
            if feed_tpl and isinstance(feed_tpl.get("form_data"), dict)
            else {}
        )
        base_headers = (
            feed_tpl.get("headers", {}).copy()
            if feed_tpl and isinstance(feed_tpl.get("headers"), dict)
            else {}
        )

        if not base_form:
            try:
                with shared_pool.cursor() as cur:
                    cur.execute("""
                        SELECT request_body, request_headers::jsonb
                        FROM requests
                        WHERE graphql_operation = 'CommentsListComponentsPaginationQuery'
                          AND status_code = 200 AND length(response_body) > 1000
                        ORDER BY id DESC LIMIT 1
                    """)
                    r_row = cur.fetchone()
                    is_comment_source = bool(r_row)

                    if not r_row:
                        cur.execute("""
                            SELECT request_body, request_headers::jsonb
                            FROM requests
                            WHERE url LIKE '%facebook.com/api/graphql%' AND request_body LIKE '%fb_dtsg=%'
                            ORDER BY id DESC LIMIT 1
                        """)
                        r_row = cur.fetchone()

                    if r_row and r_row[0]:
                        parsed_body = urllib.parse.parse_qs(r_row[0])
                        for k, vals in parsed_body.items():
                            if vals:
                                base_form[k] = vals[0]
                        if r_row[1] and isinstance(r_row[1], dict):
                            base_headers = r_row[1]

                        if not is_comment_source:
                            for noisy_key in ["__dyn", "__csr", "__hsdp", "__hblp", "__sjsp"]:
                                base_form.pop(noisy_key, None)
            except Exception as e:
                logger.debug(f"[CommentCrawler] Error fetching base_form from requests table: {e}")

        comment_form = base_form.copy()
        comment_form["fb_api_req_friendly_name"] = "CommentsListComponentsPaginationQuery"
        comment_form["doc_id"] = "27973447728944010"
        comment_form["fb_api_caller_class"] = "RelayModern"
        comment_form["server_timestamps"] = "true"
        comment_form["__comet_req"] = "15"
        comment_form["__a"] = "1"

        target_fbid = feedback_id
        if not target_fbid.startswith("ZmVlZ") and ":" not in target_fbid:
            target_fbid = base64.b64encode(f"feedback:{feedback_id}".encode()).decode()

        comment_form["variables"] = json.dumps({
            "commentsAfterCount": -1,
            "commentsAfterCursor": None,
            "commentsBeforeCount": None,
            "commentsBeforeCursor": None,
            "commentsIntentToken": "CHRONOLOGICAL_UNFILTERED_INTENT_V1",
            "feedLocation": "POST_PERMALINK_DIALOG",
            "focusCommentID": None,
            "scale": 1,
            "targetDialect": None,
            "useDefaultActor": False,
            "id": target_fbid,
            "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "AUTO_TRANSLATE",
            "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
            "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": True,
            "__relay_internal__pv__IsWorkUserrelayprovider": False,
        }, separators=(",", ":"))

        comment_headers = base_headers.copy()
        comment_headers["Content-Type"] = "application/x-www-form-urlencoded"
        comment_headers["X-FB-Friendly-Name"] = "CommentsListComponentsPaginationQuery"
        return {
            "headers": comment_headers,
            "form_data": comment_form,
        }

    # ── Fetch Comments (GraphQL) ─────────────────────────────────────

    async def fetch_comments(
        self,
        feedback_id: str,
        template: dict,
        comment_session_state: SessionStateManager,
        cursor: Optional[str] = None,
        direction: str = "after",
    ) -> tuple[list[str], str, Optional[str], bool, str]:
        """Fetch comment IDs for a post with bi-directional cursor support."""
        headers = template.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-FB-Friendly-Name"] = "CommentsListComponentsPaginationQuery"
        data = template.get("form_data", {}).copy()
        comment_session_state.update_params(data)

        target_fbid = feedback_id
        if not target_fbid.startswith("ZmVlZ") and ":" not in target_fbid:
            try:
                target_fbid = base64.b64encode(f"feedback:{feedback_id}".encode()).decode()
            except Exception:
                pass

        try:
            variables = json.loads(data.get("variables", "{}"))
            variables["id"] = target_fbid
            if "comments_target_id" in variables:
                variables["comments_target_id"] = target_fbid
            if "feedback_id" in variables:
                variables["feedback_id"] = target_fbid

            variables["commentsIntentToken"] = "CHRONOLOGICAL_UNFILTERED_INTENT_V1"

            if cursor:
                if direction == "before":
                    variables["commentsBeforeCursor"] = cursor
                    variables["commentsBeforeCount"] = -1
                    variables["commentsAfterCursor"] = None
                    variables["commentsAfterCount"] = None
                else:
                    variables["commentsAfterCursor"] = cursor
                    variables["commentsAfterCount"] = -1
                    variables["commentsBeforeCursor"] = None
                    variables["commentsBeforeCount"] = None
            else:
                variables["commentsAfterCursor"] = None
                variables["commentsAfterCount"] = -1
                variables["commentsBeforeCursor"] = None
                variables["commentsBeforeCount"] = None

            data["variables"] = json.dumps(variables, separators=(",", ":"))
        except Exception as e:
            logger.warning(f"[CommentCrawler] Error updating comment variables: {e}")

        try:
            resp = await self.engine.safe_request(
                "POST", GRAPHQL_ENDPOINT,
                headers=headers,
                data=urllib.parse.urlencode(data).encode(),
                is_comment_crawl=True,
            )
            comment_ids = self.parse_comment_ids(resp.text)
            next_cursor, has_more, next_dir = self.extract_comment_page_info(
                resp.text, current_direction=direction
            )
            return comment_ids, resp.text, next_cursor, has_more, next_dir
        except StealthRequestError as e:
            logger.error(f"[CommentCrawler] Comment fetch failed for {feedback_id}: {e}")
            return [], "", None, False, ""

    # ── Fetch Replies ────────────────────────────────────────────────

    async def fetch_replies(
        self,
        comment_id: str,
        template: dict,
        comment_session_state: SessionStateManager,
    ) -> str:
        """Fetch replies for a comment."""
        headers = template.get("headers", {}).copy()
        headers["X-Proxify-Crawler"] = "1"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-FB-Friendly-Name"] = "Depth1CommentsListPaginationQuery"
        data = template.get("form_data", {}).copy()
        comment_session_state.update_params(data)

        try:
            variables = json.loads(data.get("variables", "{}"))
            variables["comment_id"] = comment_id
            variables["id"] = comment_id

            for key in ["commentsAfterCursor", "commentsBeforeCursor", "cursor", "after", "before"]:
                if key in variables:
                    variables[key] = None

            data["variables"] = json.dumps(variables, separators=(",", ":"))
        except Exception:
            pass

        try:
            resp = await self.engine.safe_request(
                "POST", GRAPHQL_ENDPOINT,
                headers=headers,
                data=urllib.parse.urlencode(data).encode(),
                is_comment_crawl=True,
            )
            return resp.text
        except StealthRequestError as e:
            logger.error(f"[CommentCrawler] Reply fetch failed for {comment_id}: {e}")
            return ""

    # ── Update Post Metrics ──────────────────────────────────────────

    def update_post_metrics(self, url: str, html: str) -> None:
        """Extract reaction/comment counts and feedback_id from HTML and update DB."""
        rc, cc, feedback_id, is_active, status = self.extract_metrics_from_html(html)

        if not is_active:
            try:
                with shared_pool.cursor() as cur:
                    cur.execute(
                        "UPDATE facebook.posts SET is_active = FALSE, updated_at = NOW() WHERE permalink_url = %s",
                        (url,)
                    )
                logger.info(f"[CommentCrawler] Marked post {url} as inactive/deleted")
            except Exception as e:
                logger.error(f"[CommentCrawler] DB update failed for {url}: {e}")
            return

        if rc is None and cc is None:
            logger.warning(f"[CommentCrawler] No metrics found for {url}, but marking as active")

        logger.info(f"[CommentCrawler] Metrics for {url}: {rc} reactions, {cc} comments, feedback_id: {feedback_id}")
        try:
            with shared_pool.cursor() as cur:
                updates, params = [], []
                if rc is not None:
                    updates.append("reaction_count = %s")
                    params.append(rc)
                if cc is not None:
                    updates.append("comment_count = %s")
                    params.append(cc)
                if feedback_id is not None:
                    updates.append("feedback_id = %s")
                    params.append(feedback_id)

                updates.append("is_active = TRUE")
                updates.append("updated_at = NOW()")
                params.append(url)

                cur.execute(
                    f"UPDATE facebook.posts SET {', '.join(updates)} WHERE permalink_url = %s",
                    params,
                )
        except Exception as e:
            logger.error(f"[CommentCrawler] DB update failed for {url}: {e}")
