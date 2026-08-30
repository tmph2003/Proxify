"""
Zalo Data Extractor — Trích xuất dữ liệu đã giải mã từ Zalo Web.

Hoạt động bằng cách:
  1. Inject JS hooks vào các file JS của Zalo qua MITM proxy
  2. Hooks bắt dữ liệu sau khi Zalo tự giải mã (crypto.subtle + CryptoJS AES)
  3. Dữ liệu được gửi về proxy qua endpoint giả /api/capture_dump
  4. Proxy lưu vào thư mục dumps/ và phân loại tự động

Sử dụng:
  from proxify.platforms.zalo.extractor import ZaloExtractor
  extractor = ZaloExtractor("dumps")
  groups = extractor.get_groups()
  messages = extractor.get_messages()
"""

import gzip
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from mitmproxy import http

logger = logging.getLogger("proxify")

# ─── Dump directory ───────────────────────────────────────────────────────────

DEFAULT_DUMP_DIR = "dumps"


# ─── JS Hooks (injected into Zalo's JS files via MITM) ───────────────────────

# Hook 1 & 2: Loaded dynamically from js/ folder
def load_js_hook(filename: str) -> str:
    path = Path(__file__).parent / "js" / filename
    return path.read_text(encoding="utf-8") if path.exists() else ""

CRYPTO_SUBTLE_HOOK = load_js_hook("crypto_subtle.js")
JSON_PARSE_HOOK = load_js_hook("json_parse.js")

# Hook 3: trusted-device-bridge WASM hooks (encrypt/decrypt bytes & strings)
WASM_HOOKS = {
    "decryptBytes(e,t){return e.decryptBytes(t).slice()}": """
        decryptBytes(e,t){
            let res = e.decryptBytes(t).slice();
            try { console.log('[ZALO] decryptBytes', new TextDecoder().decode(res)); } catch(_) {}
            return res;
        }""",
    "encryptBytes(e,t){return e.encryptBytes(t).slice()}": """
        encryptBytes(e,t){
            try { console.log('[ZALO] encryptBytes', new TextDecoder().decode(t)); } catch(_) {}
            return e.encryptBytes(t).slice();
        }"""
}

# ─── JS injection (called from ZaloHookBlocker.modify_response) ──────────────

def inject_hooks(url: str, body: str) -> Optional[str]:
    """
    Inject JS hooks into a Zalo JS file.
    Returns modified body, or None if no changes were made.
    """
    original = body

    # ── trusted-device-bridge.js: WASM-level encrypt/decrypt hooks ──
    if "trusted-device-bridge" in url:
        for target, replacement in WASM_HOOKS.items():
            body = body.replace(target, replacement)
        return body if body != original else None

    # ── All other Zalo JS files ──
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if not (parsed.path.lower().endswith(".js") and ("zalo" in url or "zdn.vn" in url)):
        return None

    # crypto.subtle hook (for E2EE sync messages)
    if "crypto.subtle.decrypt" in body or "AES.decrypt" in body:
        body = body + "\n" + CRYPTO_SUBTLE_HOOK

    # JSON.parse hook (for group Info & message decodeAES outputs)
    if "JSON.parse(" in body or "JSON.parse" in body:
        body = body + "\n" + JSON_PARSE_HOOK

    return body if body != original else None

# Dedup cache for handle_capture_dump (module-level)
_seen_hashes: set[str] = set()

def handle_capture_dump(flow: http.HTTPFlow) -> bool:
    """Intercept dummy capture dump API and save to database (with dedup).
    Also handles /api/zalo/commands/pending for command polling.
    
    Handles two types of payloads from the JS hooks:
    1. Group data (from JSON.parse hook): contains memberIds, memberProfiles with globalId
    2. User profiles (from fetchUserProfiles): contains { _type: 'userProfiles', profiles: [...] }
    """
    # Handle command polling: forward to dashboard
    if flow.request.method == "GET" and "api/zalo/commands/pending" in flow.request.path:
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:8888/api/zalo/commands/pending")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = resp.read()
            flow.response = http.Response.make(200, data, {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"})
        except Exception as e:
            flow.response = http.Response.make(200, b"[]", {"Content-Type": "application/json"})
        return True

    global _seen_hashes
    if flow.request.method == "POST" and "api/capture_dump" in flow.request.path:
        content = flow.request.content
        if content:
            # Dedup by content hash
            import hashlib
            content_hash = hashlib.md5(content).hexdigest()
            if content_hash in _seen_hashes:
                flow.response = http.Response.make(200, b"dup")
                return True
            _seen_hashes.add(content_hash)
            # Limit seen hashes cache to 500 entries
            if len(_seen_hashes) > 500:
                _seen_hashes = set(list(_seen_hashes)[-200:])
            
            # Process data and insert into DB directly
            try:
                from proxify.platforms.zalo import zalo_db as db
                
                # CHÚ Ý: Bỏ điều kiện running_jobs để cho phép Zalo Web tự động sync danh sách Group.
                # Do JS hook đã tắt tự động fetchFullGroupInfo, nên dữ liệu rác sẽ không bị kéo về nhiều.
                running_jobs = db.jobs.get_running_jobs()

                obj = ZaloExtractor._decode(content)
                if obj and isinstance(obj, dict):
                    # ── Fast path: userProfiles payload (from fetchUserProfiles) ──
                    # These contain globalId directly from Zalo's profile API
                    if obj.get("_type") == "userProfiles" and isinstance(obj.get("profiles"), list):
                        profiles = obj["profiles"]
                        gid_count = 0
                        for p in profiles:
                            if isinstance(p, dict):
                                uid = str(p.get("userId") or p.get("uid") or p.get("id") or p.get("memberId") or "")
                                global_id = p.get("globalId") or p.get("gid") or ""
                                display_name = (p.get("dName") or p.get("displayName") or p.get("zaloName")
                                                or p.get("name") or p.get("zName") or p.get("fullName") or "")
                                avatar = p.get("avatar") or p.get("avt") or ""
                                phone = (p.get("phone") or p.get("phoneNumber") or p.get("mobile")
                                         or p.get("sdtSearch") or "")
                                if uid:
                                    db.users.upsert(uid, global_id, display_name, avatar, phone, p)
                                    if global_id:
                                        gid_count += 1
                        logger.info(f"[ZALO] 👤 userProfiles → DB: {len(profiles)} users ({gid_count} with globalId)")
                        flow.response = http.Response.make(200, b"ok")
                        return True

                    # ── Standard path: group/other data ──
                    ext = ZaloExtractor()
                    ext._iter_payloads = lambda: [("memory", obj)]

                    groups = ext.get_groups()
                    total_users_upserted = 0
                    total_gid_count = 0

                    for g in groups:
                        gid = g.get("userId")
                        db.groups.upsert(
                            gid,
                            g.get("displayName"),
                            g.get("totalMember"),
                            g
                        )
                        # Link members to this group ONLY if explicitly scanned
                        # This prevents pulling all members of all groups during background sync
                        member_ids = g.get("memberIds", [])
                        if gid and member_ids:
                            logger.info(f"[ZALO] Found {len(member_ids)} members for {gid}. Source = {obj.get('_source')}")
                            if obj.get("_source") == "getGroupInfoV2_paginated":
                                db.memberships.link_members(gid, member_ids)
                                logger.info(f"[ZALO] Linked {len(member_ids)} members to {gid}")
                            else:
                                logger.debug(f"[ZALO] Ignoring members for {gid} (background sync)")
                        
                        # Extract users from memberProfiles (these often have globalId!)
                        member_profiles = g.get("memberProfiles", [])
                        for mp in member_profiles:
                            if isinstance(mp, dict):
                                uid = str(mp.get("userId") or mp.get("uid") or mp.get("id") or "")
                                global_id = mp.get("globalId") or mp.get("gid") or ""
                                display_name = (mp.get("dName") or mp.get("displayName") or mp.get("zaloName")
                                                or mp.get("name") or mp.get("fullName") or "")
                                avatar = mp.get("avatar") or mp.get("avt") or ""
                                phone = (mp.get("phone") or mp.get("phoneNumber") or mp.get("mobile") or "")
                                if uid:
                                    db.users.upsert(uid, global_id, display_name, avatar, phone, mp)
                                    total_users_upserted += 1
                                    if global_id:
                                        total_gid_count += 1

                    # Also extract users from the extractor (catches additional patterns)
                    users = ext.get_users()
                    for u in users:
                        if isinstance(u, dict):
                            uid = str(u.get("userId") or "")
                            if uid:
                                db.users.upsert(
                                    uid,
                                    u.get("globalId") or u.get("gid") or "",
                                    u.get("displayName") or u.get("dName") or u.get("zaloName") or "",
                                    u.get("avatar") or u.get("avt") or "",
                                    u.get("phone") or u.get("phoneNumber") or "",
                                    u
                                )
                                total_users_upserted += 1
                                if u.get("globalId") or u.get("gid"):
                                    total_gid_count += 1

                    if groups:
                        logger.info(f"[ZALO] 📋 Group data → DB: {len(groups)} group(s), "
                                    f"{total_users_upserted} user(s) ({total_gid_count} with globalId)")
                    elif total_users_upserted > 0:
                        logger.info(f"[ZALO] 👤 User data → DB: {total_users_upserted} user(s) "
                                    f"({total_gid_count} with globalId)")
                    else:
                        # Log what we got for debugging
                        keys = list(obj.keys())[:10]
                        logger.debug(f"[ZALO] Capture dump (no groups/users): keys={keys}")

            except Exception as e:
                logger.error(f"[ZALO] Error processing capture dump: {e}", exc_info=True)

        flow.response = http.Response.make(200, b"ok")
        return True
    return False

def modify_zalo_response(flow: http.HTTPFlow) -> None:
    """Intercept Zalo JS responses and inject hooks."""
    url = flow.request.pretty_url
    if not flow.response:
        return

    content = flow.response.content
    is_streamed = getattr(flow.response, 'stream', False)

    # Debug: log all Zalo JS responses
    if "zalo" in url and (".js" in url or "trusted-device-bridge" in url):
        content_len = len(content) if content else 0
        logger.info(f"[ZALO DEBUG] Response: {url.split('/')[-1][:60]} | content={content_len}B | stream={is_streamed}")

    if not content:
        return

    from urllib.parse import urlparse
    parsed = urlparse(url)
    
    # Only target Zalo JS files for hooks
    if ("zalo" not in url and "zdn.vn" not in url) or not parsed.path.lower().endswith(".js"):
        if "trusted-device-bridge" not in url:
            return

    # Decode using flow.response.text which automatically handles gzip/br decompression
    try:
        body = flow.response.text
    except Exception as e:
        logger.warning(f"[ZALO] Failed to decode {url}: {e}")
        return
        
    if not body:
        return

    modified = inject_hooks(url, body)
    if modified is not None:
        flow.response.text = modified
        # Ensure Content-Type has correct charset
        ct = flow.response.headers.get("content-type", "")
        if "charset" not in ct.lower():
            flow.response.headers["content-type"] = ct + "; charset=utf-8" if ct else "application/javascript; charset=utf-8"
        flow.metadata["ad_blocked"] = True
        logger.info(f"[ZALO] Injected hooks → {url.split('/')[-1]}")


# ─── Data extractor (reads dump files) ────────────────────────────────────────

class ZaloExtractor:
    """
    Reads and categorizes Zalo data from dump files.

    Usage:
        extractor = ZaloExtractor("dumps")
        for group in extractor.get_groups():
            print(group['displayName'], group['totalMember'])
    """

    def __init__(self, dump_dir: str = DEFAULT_DUMP_DIR):
        self.dump_dir = Path(dump_dir)

    def _iter_payloads(self):
        """Yield (filename, parsed_dict) for each readable dump file."""
        if not self.dump_dir.exists():
            return

        for f in sorted(self.dump_dir.glob("*.bin"), key=os.path.getmtime):
            raw = f.read_bytes()
            obj = self._decode(raw)
            if obj is not None:
                yield f.name, obj

    @staticmethod
    def _decode(raw: bytes) -> Optional[dict]:
        """Decode a dump file: gzip→JSON or [JSON.parse]→JSON."""
        # Gzip-compressed (from crypto.subtle hook)
        if raw[:2] == b'\x1f\x8b':
            try:
                text = gzip.decompress(raw).decode("utf-8")
                return json.loads(text)
            except Exception:
                return None

        # JSON.parse hook marker (supports both old and new format)
        for prefix in (b'[JSON.parse] ', b'[JSON.parse HOOK] '):
            if raw.startswith(prefix):
                try:
                    return json.loads(raw[len(prefix):].decode("utf-8"))
                except Exception:
                    return None

        # Plain JSON
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    # ── High-level accessors ──

    @staticmethod
    def _normalize_group_id(raw_id) -> str:
        """Normalize a group ID by stripping 'g' prefix."""
        s = str(raw_id or "").strip()
        if s.startswith("g") and s[1:].isdigit():
            return s[1:]
        return s

    @staticmethod
    def _pick_group_id(container: dict, fallback_obj: dict | None = None) -> str | None:
        """Extract a group ID from a payload container."""
        uid = (container.get("groupId") or container.get("grid") or 
               container.get("id") or container.get("group_id"))
        if not uid:
            # Check userId with 'g' prefix (Zalo convention for groups)
            user_id = str(container.get("userId", ""))
            if user_id.startswith("g") and user_id[1:].isdigit():
                uid = user_id
        if not uid and container.get("isGroup"):
            uid = container.get("userId")
        if not uid and fallback_obj and isinstance(fallback_obj, dict):
            uid = fallback_obj.get("groupId") or fallback_obj.get("grid")
        return uid

    def get_messages(self) -> list[dict]:
        """Extract personal and group messages."""
        messages = []
        for _, obj in self._iter_payloads():
            if not isinstance(obj, dict):
                continue
            data = obj.get("data", {})
            if not isinstance(data, dict):
                continue
            for msg in data.get("msgs", []) + data.get("groupMsgs", []) + data.get("pageMsgs", []):
                messages.append(msg)
        return messages

    def get_users(self) -> dict:
        """Extract user profiles (globalId, zName, avatar, etc). Returns a dict of uid -> profile."""
        users = {}
        for _, obj in self._iter_payloads():
            if not isinstance(obj, dict):
                continue
            
            # Legacy/generic payload users
            if "zName" in obj or "displayName" in obj:
                uid = str(obj.get("userId") or obj.get("uid") or obj.get("id") or "")
                if uid and not obj.get("isGroup"):
                    users[uid] = obj

            # New structured userProfiles payload
            if obj.get("_type") == "userProfiles" and isinstance(obj.get("profiles"), list):
                for p in obj["profiles"]:
                    if isinstance(p, dict):
                        uid = str(p.get("userId") or p.get("uid") or p.get("id") or "")
                        if uid:
                            users[uid] = p
                            
        return users

    def get_reactions(self) -> list[dict]:
        """Extract message reactions."""
        reactions = []
        for _, obj in self._iter_payloads():
            if not isinstance(obj, dict):
                continue
            data = obj.get("data", {})
            if isinstance(data, dict):
                for react in data.get("reactGroups", []) + data.get("reacts", []):
                    reactions.append(react)
        return reactions

    def summary(self) -> dict:
        """Return a summary of all captured data."""
        return {
            "groups": len(self.get_groups()),
            "messages": len(self.get_messages()),
            "users": len(self.get_users()),
            "reactions": len(self.get_reactions()),
            "dump_files": len(list(self.dump_dir.glob("*.bin"))) if self.dump_dir.exists() else 0,
        }

    def export_groups_json(self, output_path: str = "zalo_groups.json") -> str:
        """Export groups to a formatted JSON file."""
        groups = self.get_groups()
        out = self.dump_dir / output_path
        with open(out, "w", encoding="utf-8") as f:
            json.dump(groups, f, indent=2, ensure_ascii=False)
        logger.info(f"[ZALO] Exported {len(groups)} groups → {out}")
        return str(out)


    def get_groups(self) -> list[dict]:
        """
        Extract and merge all group data from captured payloads.
        """
        groups = {}
        for _, obj in self._iter_payloads():
            if not isinstance(obj, dict):
                continue
            
            # Zalo payloads can have data in root, 'data', or 'groupInfo'
            candidates = [obj, obj.get("data", {}), obj.get("groupInfo", {})]
            
            # Also if groupInfo has { "groupId": { ... } }
            if isinstance(obj.get("groupInfo"), dict):
                for v in obj["groupInfo"].values():
                    if isinstance(v, dict): candidates.append(v)
            
            for container in candidates:
                if not isinstance(container, dict):
                    continue
                
                uid = self._pick_group_id(container, obj)
                
                if uid:
                    uid = self._normalize_group_id(uid)
                    if uid not in groups:
                        groups[uid] = {
                            "displayName": container.get("dName") or container.get("displayName") or container.get("name") or "",
                            "userId": uid,
                            "totalMember": container.get("totalMember", 0),
                            "memberIds": set(),
                            "memberProfiles": {}
                        }
                    
                    # Update name/total if we found a better one
                    if container.get("dName") or container.get("displayName") or container.get("name"):
                        groups[uid]["displayName"] = container.get("dName") or container.get("displayName") or container.get("name")
                    if container.get("totalMember"):
                        groups[uid]["totalMember"] = container.get("totalMember")

                    raw_members = (
                        container.get("memberList") or container.get("memVerList") or 
                        container.get("members") or container.get("memberIds") or 
                        container.get("participants") or container.get("userList") or 
                        container.get("users") or container.get("topMember") or 
                        container.get("currentMems") or container.get("currentMembers") or 
                        container.get("mems") or container.get("memberInfo") or 
                        container.get("memberInfos") or container.get("membersInfo") or 
                        container.get("groupMembers") or container.get("admins") or []
                    )
                    
                    if isinstance(raw_members, list):
                        for m in raw_members:
                            if isinstance(m, (str, int)):
                                groups[uid]["memberIds"].add(str(m))
                            elif isinstance(m, dict):
                                m_id = m.get("userId") or m.get("uid") or m.get("id") or m.get("memberId")
                                if m_id:
                                    groups[uid]["memberIds"].add(str(m_id))
                    elif isinstance(raw_members, dict):
                        for m in raw_members.values():
                            if isinstance(m, dict):
                                m_id = m.get("userId") or m.get("uid") or m.get("id") or m.get("memberId")
                                if m_id:
                                    groups[uid]["memberIds"].add(str(m_id))
                                    
                    # Extract member profiles (where globalId usually is)
                    profile_keys = ["memberProfiles", "topMember", "currentMems", "currentMembers", "members", "admins"]
                    for pk in profile_keys:
                        raw_profiles = container.get(pk, [])
                        if isinstance(raw_profiles, list):
                            for p in raw_profiles:
                                if isinstance(p, dict):
                                    m_id = p.get("userId") or p.get("uid") or p.get("id") or p.get("memberId")
                                    if m_id:
                                        m_id = str(m_id)
                                        prof = groups[uid]["memberProfiles"].get(m_id, {})
                                        prof["userId"] = m_id
                                        prof["globalId"] = p.get("globalId") or p.get("gid") or prof.get("globalId", "")
                                        prof["displayName"] = p.get("dName") or p.get("displayName") or p.get("zaloName") or p.get("name") or p.get("fullName") or prof.get("displayName", "")
                                        prof["avatar"] = p.get("avatar") or p.get("avt") or prof.get("avatar", "")
                                        groups[uid]["memberProfiles"][m_id] = prof

        # Merge globally extracted users to enrich group profiles
        # get_users() returns list[dict], convert to dict keyed by userId
        all_users_list = self.get_users()
        all_users = {u.get("userId", ""): u for u in all_users_list if isinstance(u, dict) and u.get("userId")}
        
        # Format output
        res = []
        for g in groups.values():
            new_g: dict = g.copy()
            new_g["memberIds"] = list(g["memberIds"])
            
            # Enrich profiles
            profiles: dict = new_g.get("memberProfiles", {})  # type: dict
            for m_id in new_g["memberIds"]:
                if m_id in all_users:
                    prof = profiles.get(m_id, {"userId": m_id})
                    u = all_users[m_id]
                    prof["globalId"] = u.get("globalId") or u.get("gid") or prof.get("globalId", "")
                    prof["displayName"] = u.get("dName") or u.get("displayName") or u.get("zaloName") or u.get("name") or u.get("fullName") or prof.get("displayName", "")
                    prof["avatar"] = u.get("avatar") or u.get("avt") or prof.get("avatar", "")
                    prof["phone"] = u.get("phone") or u.get("phoneNumber") or prof.get("phone", "")
                    profiles[m_id] = prof
            
            new_g["memberProfiles"] = list(profiles.values())
            res.append(new_g)
        return res

    def get_messages(self) -> list[dict]:
        """Extract personal and group messages."""
        messages = []
        for _, obj in self._iter_payloads():
            if not isinstance(obj, dict):
                continue
            data = obj.get("data", {})
            if not isinstance(data, dict):
                continue
            for msg in data.get("msgs", []) + data.get("groupMsgs", []) + data.get("pageMsgs", []):
                messages.append(msg)
        return messages

    def get_users(self) -> list[dict]:
        """Extract user profiles (zName, avatar, globalId, phone)."""
        users = {}
        
        def _extract_profile(p: dict) -> None:
            """Extract a user profile from a dict and merge into users."""
            m_id = p.get("userId") or p.get("uid") or p.get("id") or p.get("memberId")
            if not m_id:
                return
            m_id = str(m_id)
            prof = users.get(m_id, {"userId": m_id})
            prof["globalId"] = p.get("globalId") or p.get("gid") or prof.get("globalId", "")
            prof["displayName"] = (p.get("dName") or p.get("displayName") or p.get("zaloName") 
                                   or p.get("name") or p.get("zName") or p.get("fullName") 
                                   or prof.get("displayName", ""))
            prof["avatar"] = p.get("avatar") or p.get("avt") or prof.get("avatar", "")
            prof["phone"] = (p.get("phone") or p.get("phoneNumber") or p.get("mobile") 
                            or p.get("sdtSearch") or prof.get("phone", ""))
            if prof["displayName"] or prof["phone"]:
                users[m_id] = prof

        for _, obj in self._iter_payloads():
            # Sometimes root is dict, sometimes data is dict
            for container in [obj, obj.get("data", {})] if isinstance(obj, dict) else []:
                if not isinstance(container, dict):
                    continue

                # Handle _type: 'userProfiles' payloads from Webpack runtime
                if container.get("_type") == "userProfiles":
                    for p in container.get("profiles", []):
                        if isinstance(p, dict):
                            _extract_profile(p)
                    continue

                # Handle dict-based profile maps (keys are userIds, values are profile objects)
                # This is how getprofiles/v2 and getProfileFriendByIds return data
                if not container.get("isGroup") and not container.get("groupId"):
                    for key, val in container.items():
                        if isinstance(val, dict) and (val.get("userId") or val.get("uid") or val.get("displayName") or val.get("dName") or val.get("phone")):
                            _extract_profile(val)
                
                # Check root user
                uid = container.get("userId") or container.get("uid") or container.get("id")
                if uid and not container.get("isGroup"):
                    _extract_profile(container)
                        
                # Also check all member profiles inside arrays
                profile_keys = ["memberProfiles", "topMember", "currentMems", "currentMembers", "members", "admins"]
                for pk in profile_keys:
                    raw_profiles = container.get(pk, [])
                    if isinstance(raw_profiles, list):
                        for p in raw_profiles:
                            if isinstance(p, dict):
                                _extract_profile(p)

                # Extract bare member IDs from flat arrays (memberList, memVerList, memberIds)
                id_keys = ["memberList", "memVerList", "memberIds"]
                for ik in id_keys:
                    raw_ids = container.get(ik, [])
                    if isinstance(raw_ids, list):
                        for mid in raw_ids:
                            mid_str = str(mid) if mid else None
                            if mid_str and mid_str not in users:
                                users[mid_str] = {"userId": mid_str, "displayName": "", "globalId": "", "avatar": "", "phone": ""}

                # Scan nested groupInfo dicts (e.g. groupInfo.{groupId}.memberProfiles)
                group_info = container.get("groupInfo", {})
                if isinstance(group_info, dict):
                    for gid, gdata in group_info.items():
                        if not isinstance(gdata, dict):
                            continue
                        for pk in profile_keys:
                            raw_profiles = gdata.get(pk, [])
                            if isinstance(raw_profiles, list):
                                for p in raw_profiles:
                                    if isinstance(p, dict):
                                        _extract_profile(p)
                        for ik in id_keys:
                            raw_ids = gdata.get(ik, [])
                            if isinstance(raw_ids, list):
                                for mid in raw_ids:
                                    mid_str = str(mid) if mid else None
                                    if mid_str and mid_str not in users:
                                        users[mid_str] = {"userId": mid_str, "displayName": "", "globalId": "", "avatar": "", "phone": ""}
                                        
        return list(users.values())

    def get_reactions(self) -> list[dict]:
        """Extract message reactions."""
        reactions = []
        for _, obj in self._iter_payloads():
            if not isinstance(obj, dict):
                continue
            data = obj.get("data", {})
            if isinstance(data, dict):
                for react in data.get("reactGroups", []) + data.get("reacts", []):
                    reactions.append(react)
        return reactions

    def summary(self) -> dict:
        """Return a summary of all captured data."""
        return {
            "groups": len(self.get_groups()),
            "messages": len(self.get_messages()),
            "users": len(self.get_users()),
            "reactions": len(self.get_reactions()),
            "dump_files": len(list(self.dump_dir.glob("*.bin"))) if self.dump_dir.exists() else 0,
        }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Zalo Data Extractor")
    parser.add_argument("--dumps", default="dumps", help="Directory containing .bin dump files")
    parser.add_argument("--out", default="zalo_export.json", help="Output JSON file path")
    args = parser.parse_args()

    print(f"Reading dumps from {args.dumps}...")
    ext = ZaloExtractor(args.dumps)
    
    data = {
        "summary": ext.summary(),
        "groups": ext.get_groups(),
        "messages": ext.get_messages(),
        "users": ext.get_users(),
        "reactions": ext.get_reactions()
    }
    
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Extraction complete! Saved to {args.out}")
    print(json.dumps(data["summary"], indent=2))

