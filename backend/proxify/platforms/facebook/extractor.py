"""
Facebook Group Data Extractor
==============================
Trích xuất bài viết, bình luận, tác giả, tệp đính kèm và tương tác từ dữ liệu Facebook GraphQL đã bắt.
Sử dụng Strategy Pattern để dễ dàng mở rộng các loại bóc tách.
"""

import json
import logging
import urllib.parse
from collections import deque
from typing import Any, Optional, Dict, List

from proxify.platforms.facebook.database import fb_db

import sys, io
if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger("fb_extractor")


class DataHelper:
    """Utility class cho các thao tác tìm kiếm trên cây JSON (BFS — không đệ quy)."""
    @staticmethod
    def find_key(data: Any, target_key: str) -> List[Any]:
        results = []
        queue = deque([data])
        while queue:
            obj = queue.popleft()
            if isinstance(obj, dict):
                if target_key in obj:
                    results.append(obj[target_key])
                queue.extend(obj.values())
            elif isinstance(obj, list):
                queue.extend(obj)
        return results

    @staticmethod
    def extract_nodes(data: Any, target_typename: str) -> List[dict]:
        results = []
        queue = deque([data])
        while queue:
            obj = queue.popleft()
            if isinstance(obj, dict):
                if obj.get('__typename') == target_typename:
                    results.append(obj)
                queue.extend(obj.values())
            elif isinstance(obj, list):
                queue.extend(obj)
        return results

    @staticmethod
    def decode_b64(s: str) -> str:
        if not s: return ""
        try:
            import base64
            return base64.b64decode(s).decode()
        except:
            return s


class RequestParser:
    """Phân tích raw request string để lấy variables (dùng cho phân trang/lấy parent_id)."""
    @staticmethod
    def parse_variables(req_body: str) -> dict:
        vars_dict = {}
        if not req_body: return vars_dict
        req_body = req_body.strip()
        
        if req_body.startswith('{'):
            try:
                payload = json.loads(req_body)
                if 'variables' in payload:
                    vars_dict = payload['variables']
                    if isinstance(vars_dict, str):
                        vars_dict = json.loads(vars_dict)
            except:
                pass
        else:
            params = urllib.parse.parse_qs(req_body)
            if 'variables' in params and params['variables']:
                try:
                    vars_dict = json.loads(params['variables'][0])
                except:
                    pass
        return vars_dict or {}


class AuthorExtractor:
    @staticmethod
    def extract(obj: Optional[dict]) -> Optional[dict]:
        if not isinstance(obj, dict):
            return None
        
        author_id = obj.get("id")
        if not author_id:
            return None
            
        name = obj.get("name", "")
        url = obj.get("url")
        typename = obj.get("__typename", "")
        
        avatar_url = None
        for pic_key in ("profile_picture_depth_0", "profile_picture_depth_1", "profile_picture"):
            pic = obj.get(pic_key)
            if isinstance(pic, dict) and pic.get("uri"):
                avatar_url = pic["uri"]
                break
                
        if not url and typename != "GroupAnonAuthorProfile":
            url = f"https://www.facebook.com/profile.php?id={author_id}"
            
        return {
            "id": str(author_id),
            "name": name,
            "profile_url": url,
            "avatar_url": avatar_url,
            "typename": typename,
        }


class CommentExtractor:
    def extract(self, node: dict, vars_dict: dict = None) -> Optional[dict]:
        if not isinstance(node, dict) or not node.get('id'):
            return None
            
        comment = {
            "comment_id": node.get("id"),
            "parent_id": None,
            "parent_feedback_id": None,
            "author": None,
            "body_text": "",
            "creation_time": node.get("created_time"),
            "reaction_count": 0,
            "reply_count": 0,
            "feedback_id": node.get("feedback", {}).get("id") if isinstance(node.get("feedback"), dict) else None
        }

        # Author
        author = node.get("author")
        if author:
            comment["author"] = AuthorExtractor.extract(author)

        # Body
        body = node.get("body")
        if isinstance(body, dict):
            comment["body_text"] = body.get("text", "")
            
        if not comment["body_text"] and not comment["author"]:
            return None

        # Parent IDs linking from node structure
        parent = node.get('comment_direct_parent', {})
        if isinstance(parent, dict) and parent.get('id'):
            comment['parent_id'] = parent.get('id')

        # Heuristics from request variables (if paginated)
        vars_dict = vars_dict or {}
        if vars_dict:
            if 'comment_id' in vars_dict and not comment.get('parent_id'):
                comment['parent_id'] = vars_dict['comment_id']
            elif 'id' in vars_dict and not comment.get('parent_id'):
                comment['parent_feedback_id'] = vars_dict['id']
            elif 'feedback_id' in vars_dict and not comment.get('parent_id'):
                comment['parent_feedback_id'] = vars_dict['feedback_id']
            elif 'comments_target_id' in vars_dict and not comment.get('parent_id'):
                comment['parent_feedback_id'] = vars_dict['comments_target_id']

        return comment


class PostExtractor:
    def extract(self, node: dict, request_id: int) -> Optional[dict]:
        post_id = str(node.get('id') or node.get('post_id') or "")
        if not post_id:
            return None
            
        if len(post_id) > 2000:
            post_id = post_id[:2000]
            
        # Loại bỏ các bài viết quảng cáo / Sponsored / Gợi ý
        if node.get("category") == "SPONSORED" or node.get("sponsored_data") or DataHelper.find_key(node, "sponsored_data"):
            return None
            
        target_id = None
        target_type = None
        to = node.get('to')
        if isinstance(to, list) and to:
            first_target = to[0]
            if isinstance(first_target, dict):
                target_id = first_target.get('id')
                target_type = first_target.get('__typename')
        elif isinstance(node.get('owning_profile'), dict):
            target_id = node.get('owning_profile').get('id')
            target_type = node.get('owning_profile').get('__typename')

        post = {
            "post_id": post_id,
            "group_id": None,
            "group_name": None,
            "author": None,
            "message_text": "",
            "permalink_url": node.get('url') or node.get('permalink_url'),
            "creation_time": node.get("creation_time"),
            "attachments": [],
            "seo_title": None,
            "is_text_only": 1,
            "reaction_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "feedback_id": None,
            "request_id": request_id,
            "_target_id": target_id,
            "_target_type": target_type
        }

        # Author (Robust extraction from fb_scraper.py)
        actors = node.get('actors')
        if not actors:
            comet_layout = node.get('comet_sections', {}).get('context_layout', {})
            actors_names = DataHelper.find_key(comet_layout, 'name')
            if actors_names:
                post['author'] = {"id": "", "name": actors_names[0], "profile_url": "", "avatar_url": "", "typename": ""}
        if isinstance(actors, list) and actors:
            post["author"] = AuthorExtractor.extract(actors[0])
            
        # Text Message
        msg_node = node.get('message')
        if isinstance(msg_node, dict):
            texts = DataHelper.find_key(msg_node, 'text')
            if texts: post["message_text"] = "\n".join(set(texts))
            
        if not post["message_text"]:
            texts = DataHelper.find_key(node, 'text')
            valid = [t for t in texts if isinstance(t, str) and len(t) > 10 and not t.startswith('http')]
            if valid:
                post["message_text"] = "\n".join(set(valid))

        if not post["message_text"] and not post["author"]:
            return None

        # Feedback & Metrics
        fb = node.get('feedback')
        if isinstance(fb, dict) and fb.get('id'):
            post["feedback_id"] = fb.get('id')
        else:
            fb_nodes = DataHelper.find_key(node, 'feedback')
            for fb_node in fb_nodes:
                if isinstance(fb_node, dict) and fb_node.get('id'):
                    post["feedback_id"] = fb_node.get('id')
                    break
            
        reaction_counts = DataHelper.find_key(node, 'reaction_count')
        if reaction_counts:
            # filter to int
            counts = [c.get('count', 0) if isinstance(c, dict) else c for c in reaction_counts if c]
            post["reaction_count"] = max((c for c in counts if isinstance(c, int)), default=0)
            
        share_counts = DataHelper.find_key(node, 'share_count')
        if share_counts:
            counts = [c.get('count', 0) if isinstance(c, dict) else c for c in share_counts if c]
            post["share_count"] = max((c for c in counts if isinstance(c, int)), default=0)
            
        total_comments = DataHelper.find_key(node, 'total_comment_count') + DataHelper.find_key(node, 'total_count')
        if total_comments:
                counts = [c.get('count', 0) if isinstance(c, dict) else c for c in total_comments if c]
                post["comment_count"] = max((c for c in counts if isinstance(c, int)), default=0)

        # Attachments
        post["is_text_only"] = 0 if node.get('attachments') else 1

        # Group Name — extracted from multiple possible locations in the Story node
        group_name = self._extract_group_name(node)
        if group_name:
            post["group_name"] = group_name

        return post

    @staticmethod
    def _extract_group_name(node: dict) -> Optional[str]:
        """Extract group name from a Story node.

        Facebook stores group name in several locations:
        1. ``to[0].name`` — direct target group
        2. ``owning_profile.name`` — owning group profile
        3. Any nested ``Group`` node with a ``name`` field
        """
        # 1. "to" field (most common in group feed)
        to = node.get('to')
        if isinstance(to, list) and to:
            first_target = to[0]
            if isinstance(first_target, dict):
                name = first_target.get('name')
                if name and first_target.get('__typename') == 'Group':
                    return name

        # 2. owning_profile (alternative location)
        owning = node.get('owning_profile')
        if isinstance(owning, dict) and owning.get('__typename') == 'Group':
            name = owning.get('name')
            if name:
                return name

        # 3. Search for Group nodes anywhere in the story
        groups = DataHelper.extract_nodes(node, 'Group')
        for g in groups:
            name = g.get('name')
            if name and isinstance(name, str):
                return name

        return None


class DocumentLinker:
    """Strategy to link disconnected Comments to their Parents/Posts based on feedback_id/parent_id."""
    @staticmethod
    def link_and_upsert(posts: list, comments: list):
        # Indexing for O(1) lookups
        posts_by_fbid = {p['feedback_id']: p for p in posts if p.get('feedback_id')}
        comments_by_id = {c['comment_id']: c for c in comments}
        
        # We need to map comments to their parents before upserting.
        for c in comments:
            parent_id = c.get('parent_id')
            parent_fbid = c.get('parent_feedback_id')
            
            # If we know the exact parent_id (it's a reply)
            if parent_id and parent_id in comments_by_id:
                # Already mapped correctly
                pass
            elif parent_fbid:
                # Need to match this comment to a Post
                c_fbid_dec = DataHelper.decode_b64(parent_fbid)
                for p_fbid, p in posts_by_fbid.items():
                    p_fbid_dec = DataHelper.decode_b64(p_fbid)
                    if p_fbid_dec and c_fbid_dec.startswith(p_fbid_dec):
                        c['post_id'] = p['post_id'] # Tie it to the post directly, making it top-level
                        break

        # Now UPSERT in correct order: Authors -> Posts -> Comments
        new_posts, new_comments = 0, 0
        
        try:
            with fb_db.pool.cursor() as cur:
                # Find existing posts
                post_ids = [p["post_id"] for p in posts if p.get("post_id")]
                existing_posts = set()
                if post_ids:
                    cur.execute("SELECT post_id FROM facebook.posts WHERE post_id = ANY(%s)", (post_ids,))
                    existing_posts = {row[0] for row in cur.fetchall()}
                
                # Find existing comments
                comment_ids = [c["comment_id"] for c in comments if c.get("comment_id")]
                existing_comments = set()
                if comment_ids:
                    cur.execute("SELECT comment_id FROM facebook.comments WHERE comment_id = ANY(%s)", (comment_ids,))
                    existing_comments = {row[0] for row in cur.fetchall()}

                seen_posts_in_batch = set()
                for p in posts:
                    if p.get("author"):
                        fb_db.authors.upsert(p["author"], cursor=cur)
                    fb_db.posts.upsert(p, cursor=cur)
                    
                    pid = p.get("post_id")
                    if pid and pid not in existing_posts and pid not in seen_posts_in_batch:
                        new_posts += 1
                        seen_posts_in_batch.add(pid)
                    
                seen_comments_in_batch = set()
                for c in comments:
                    if c.get("author"):
                        fb_db.authors.upsert(c["author"], cursor=cur)
                    # Fallback post_id if not found via Linking
                    post_id_val = c.get('post_id')
                    
                    db_comment = {
                        "comment_id": c["comment_id"],
                        "parent_comment_id": c["parent_id"],
                        "author": c["author"],
                        "body_text": c["body_text"],
                        "creation_time": c["creation_time"],
                        "reaction_count": c["reaction_count"],
                        "reply_count": c["reply_count"]
                    }
                    
                    fb_db.comments.upsert(db_comment, post_id_val, cursor=cur)
                    
                    cid = c.get("comment_id")
                    if cid and cid not in existing_comments and cid not in seen_comments_in_batch:
                        new_comments += 1
                        seen_comments_in_batch.add(cid)
        except Exception as e:
            logger.error(f"Error during link_and_upsert: {e}")
            
        return new_posts, new_comments


# ─── Pipeline chạy trích xuất ──────────────────────────────────────────────

def extract_from_responses(responses: list[str], vars_dict: dict, group_id: str = None, group_name: str = None, start_ts: int = None, end_ts: int = None, post_id: str = None, group_numeric_id: str = None) -> tuple[int, int, str | None]:
    """Extract posts and comments from GraphQL responses.

    Returns:
        Tuple of (post_count, comment_count, detected_group_name).
        The caller should cache detected_group_name and pass it back
        on subsequent calls to avoid redundant Group node searches.
    """
    post_extractor = PostExtractor()
    comment_extractor = CommentExtractor()
    
    extracted_posts = []
    extracted_comments = []
    _detected_group_name = group_name  # Already cached by caller — skip detection if set
    
    for resp_text in responses:
        for line in resp_text.split("\n"):
            line = line.strip()
            if not line: continue
            try:
                data = json.loads(line)
                
                # 0. Auto-detect group_name ONCE from Group nodes in response
                #    Only runs when caller hasn't provided a cached name.
                if not _detected_group_name and group_id:
                    group_nodes = DataHelper.extract_nodes(data, "Group")
                    for gn in group_nodes:
                        if gn.get("id") == group_id and gn.get("name"):
                            _detected_group_name = gn["name"]
                            logger.info(f"Auto-detected group_name: {_detected_group_name}")
                            break
                
                # 1. Trích xuất Posts
                raw_posts = DataHelper.extract_nodes(data, "Story")
                for rp in raw_posts:
                    post = post_extractor.extract(rp, 0)
                    if post:
                        target_id = post.pop("_target_id", None)
                        target_type = post.pop("_target_type", None)
                        
                        # Loại bỏ bài viết thuộc Page/User hoặc Group khác (nếu đang quét Group cụ thể)
                        if group_id:
                            if target_type and target_type != 'Group':
                                logger.info(f"Bỏ qua bài viết {post['post_id']} - thuộc về {target_type}, không phải Group")
                                continue
                            if group_numeric_id and str(group_numeric_id).isdigit():
                                if target_id and str(target_id) != str(group_numeric_id):
                                    logger.info(f"Bỏ qua bài viết {post['post_id']} - thuộc Group khác (ID: {target_id}) thay vì Group đang quét ({group_numeric_id})")
                                    continue

                        # Filter by date range if provided
                        ctime = post.get("creation_time")
                        if ctime:
                            try:
                                ctime = int(ctime)
                                if start_ts and ctime < start_ts:
                                    continue
                                if end_ts and ctime > end_ts:
                                    continue
                            except (ValueError, TypeError):
                                pass

                        if group_id:
                            post["group_id"] = group_id
                        if group_numeric_id:
                            post["group_numeric_id"] = group_numeric_id
                        
                        # Apply group_name (from post extraction or auto-detected)
                        if not _detected_group_name and post.get("group_name"):
                            _detected_group_name = post["group_name"]
                        
                        if _detected_group_name and not post.get("group_name"):
                            post["group_name"] = _detected_group_name
                        
                        extracted_posts.append(post)
                        
                # 2. Trích xuất Comments
                raw_comments = DataHelper.extract_nodes(data, "Comment")
                for rc in raw_comments:
                    comment = comment_extractor.extract(rc, vars_dict)
                    if comment:
                        if post_id and not comment.get("post_id"):
                            comment["post_id"] = post_id
                        extracted_comments.append(comment)
                        
            except json.JSONDecodeError:
                continue

    # Link and Upsert
    p_count, c_count = DocumentLinker.link_and_upsert(extracted_posts, extracted_comments)
    return p_count, c_count, _detected_group_name

