use base64::Engine;
use regex::Regex;
use serde_json::{json, Value};
use std::collections::{HashSet, VecDeque};
use std::sync::OnceLock;
use url::Url;

pub struct DataHelper;

impl DataHelper {
    pub fn find_key(data: &Value, target_key: &str) -> Vec<Value> {
        let mut results = Vec::new();
        let mut queue = VecDeque::new();
        queue.push_back(data);

        while let Some(curr) = queue.pop_front() {
            match curr {
                Value::Object(map) => {
                    for (k, v) in map {
                        if k == target_key {
                            results.push(v.clone());
                        }
                        if v.is_object() || v.is_array() {
                            queue.push_back(v);
                        }
                    }
                }
                Value::Array(arr) => {
                    for item in arr {
                        if item.is_object() || item.is_array() {
                            queue.push_back(item);
                        }
                    }
                }
                _ => {}
            }
        }
        results
    }

    pub fn extract_nodes(raw_text: &str) -> Vec<Value> {
        let mut nodes = Vec::new();
        for line in raw_text.lines() {
            let trimmed = line.trim().trim_start_matches("for (;;);");
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(parsed) = serde_json::from_str::<Value>(trimmed) {
                Self::collect_nodes_from_json(&parsed, &mut nodes);
            }
        }
        nodes
    }

    fn collect_nodes_from_json(parsed: &Value, nodes: &mut Vec<Value>) {
        let mut queue = VecDeque::new();
        queue.push_back(parsed);

        while let Some(curr) = queue.pop_front() {
            match curr {
                Value::Object(map) => {
                    if let Some(edges) = map.get("edges").and_then(|v| v.as_array()) {
                        for edge in edges {
                            if let Some(node) = edge.get("node") {
                                if node.is_object() {
                                    nodes.push(node.clone());
                                }
                            }
                        }
                    }
                    if let Some(node) = map.get("node") {
                        if node.is_object()
                            && (node.get("post_id").is_some()
                                || node.get("comet_sections").is_some()
                                || node.get("legacy_fbid").is_some())
                        {
                            nodes.push(node.clone());
                        }
                    }
                    for (_, v) in map {
                        if v.is_object() || v.is_array() {
                            queue.push_back(v);
                        }
                    }
                }
                Value::Array(arr) => {
                    for item in arr {
                        if item.is_object() || item.is_array() {
                            queue.push_back(item);
                        }
                    }
                }
                _ => {}
            }
        }
    }

    pub fn decode_relay_numeric_id(val: &str) -> Option<String> {
        let s = val.trim();
        if s.is_empty() {
            return None;
        }
        if s.chars().all(|c| c.is_ascii_digit()) {
            return Some(s.to_string());
        }
        let padded = match s.len() % 4 {
            2 => format!("{}==", s),
            3 => format!("{}=", s),
            _ => s.to_string(),
        };
        if let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(&padded) {
            if let Ok(decoded) = std::str::from_utf8(&bytes) {
                static RE_NUM: OnceLock<Regex> = OnceLock::new();
                let re = RE_NUM.get_or_init(|| Regex::new(r"(\d{8,})").unwrap());
                let matches: Vec<&str> = re.find_iter(decoded).map(|m| m.as_str()).collect();
                if let Some(last) = matches.last() {
                    return Some((*last).to_string());
                }
            }
        }
        None
    }

    pub fn extract_id_from_post_url(url_str: &str) -> Option<String> {
        static RE_URL_ID: OnceLock<Regex> = OnceLock::new();
        let re = RE_URL_ID.get_or_init(|| {
            Regex::new(r"/(?:posts|permalink|videos|reel|photos)/(\d{8,})|story_fbid=(\d{8,})|fbid=(\d{8,})")
                .unwrap()
        });
        if let Some(caps) = re.captures(url_str) {
            for idx in 1..=3 {
                if let Some(m) = caps.get(idx) {
                    return Some(m.as_str().to_string());
                }
            }
        }
        None
    }

    pub fn extract_canonical_post_id(node: &Value) -> Option<String> {
        for key in ["post_id", "legacy_fbid", "top_level_post_id"] {
            for val in Self::find_key(node, key) {
                if let Some(s) = val.as_str() {
                    if let Some(num) = Self::decode_relay_numeric_id(s) {
                        return Some(num);
                    }
                } else if let Some(n) = val.as_i64() {
                    return Some(n.to_string());
                }
            }
        }

        for url_key in ["permalink_url", "wwwURL", "url"] {
            for val in Self::find_key(node, url_key) {
                if let Some(u) = val.as_str() {
                    if let Some(pid) = Self::extract_id_from_post_url(u) {
                        return Some(pid);
                    }
                }
            }
        }

        if let Some(id_str) = node.get("id").and_then(|v| v.as_str()) {
            if let Some(num) = Self::decode_relay_numeric_id(id_str) {
                return Some(num);
            }
            if !id_str.is_empty() {
                return Some(id_str.to_string());
            }
        }
        None
    }
}

pub struct AuthorExtractor;

impl AuthorExtractor {
    pub fn extract_from_actor(actor: &Value) -> Option<Value> {
        let obj = actor.as_object()?;
        let raw_id = obj.get("id")?.as_str()?;
        let uid = DataHelper::decode_relay_numeric_id(raw_id).unwrap_or_else(|| raw_id.to_string());
        let name = obj
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown");
        let url = obj
            .get("url")
            .or_else(|| obj.get("profile_url"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let mut avatar = String::new();
        if let Some(pic) = obj.get("profile_picture").and_then(|v| v.as_object()) {
            if let Some(uri) = pic.get("uri").and_then(|v| v.as_str()) {
                avatar = uri.to_string();
            }
        }

        Some(json!({
            "id": uid,
            "name": name,
            "url": url,
            "avatar": avatar,
        }))
    }
}

pub struct DocumentLinker;

impl DocumentLinker {
    pub fn clean_fb_redirect(raw_url: &str) -> String {
        if raw_url.contains("l.facebook.com/l.php") {
            if let Ok(parsed) = Url::parse(raw_url) {
                for (k, v) in parsed.query_pairs() {
                    if k == "u" {
                        return v.into_owned();
                    }
                }
            }
        }
        raw_url.to_string()
    }

    pub fn extract_urls_from_text(text: &str) -> Vec<String> {
        static RE_HTTP: OnceLock<Regex> = OnceLock::new();
        let re = RE_HTTP.get_or_init(|| Regex::new(r#"https?://[^\s"'<>)\]]+"#).unwrap());
        let mut seen = HashSet::new();
        let mut list = Vec::new();
        for m in re.find_iter(text) {
            let clean = Self::clean_fb_redirect(m.as_str());
            if seen.insert(clean.clone()) {
                list.push(clean);
            }
        }
        list
    }
}

pub struct PostExtractor;

impl PostExtractor {
    pub fn extract(node: &Value, group_id_override: Option<&str>) -> Option<Value> {
        let post_id = DataHelper::extract_canonical_post_id(node)?;

        let mut author = json!({"id": "unknown", "name": "Unknown", "url": "", "avatar": ""});
        for actors_val in DataHelper::find_key(node, "actors") {
            if let Some(arr) = actors_val.as_array() {
                if let Some(first) = arr.first() {
                    if let Some(extracted_author) = AuthorExtractor::extract_from_actor(first) {
                        author = extracted_author;
                        break;
                    }
                }
            }
        }
        if author["id"] == "unknown" {
            for author_val in DataHelper::find_key(node, "author") {
                if let Some(extracted_author) = AuthorExtractor::extract_from_actor(&author_val) {
                    author = extracted_author;
                    break;
                }
            }
        }

        let mut content = String::new();
        for msg in DataHelper::find_key(node, "message") {
            if let Some(txt) = msg.get("text").and_then(|v| v.as_str()) {
                if txt.len() > content.len() {
                    content = txt.to_string();
                }
            }
        }
        if content.is_empty() {
            for msg in DataHelper::find_key(node, "story") {
                if let Some(txt) = msg.get("text").and_then(|v| v.as_str()) {
                    content = txt.to_string();
                    break;
                }
            }
        }

        let mut created_at: i64 = 0;
        for ts_val in DataHelper::find_key(node, "creation_time") {
            if let Some(ts) = ts_val.as_i64() {
                if ts > 1_000_000_000 {
                    created_at = ts;
                    break;
                }
            }
        }

        let mut url = format!("https://www.facebook.com/{}", post_id);
        for u_val in DataHelper::find_key(node, "wwwURL")
            .into_iter()
            .chain(DataHelper::find_key(node, "permalink_url"))
        {
            if let Some(u_str) = u_val.as_str() {
                if u_str.starts_with("http") {
                    url = u_str.to_string();
                    break;
                }
            }
        }

        let mut reaction_count = 0_i64;
        for r_val in DataHelper::find_key(node, "reaction_count") {
            if let Some(c) = r_val.get("count").and_then(|v| v.as_i64()) {
                reaction_count = reaction_count.max(c);
            } else if let Some(c) = r_val.as_i64() {
                reaction_count = reaction_count.max(c);
            }
        }

        let mut comment_count = 0_i64;
        for c_val in DataHelper::find_key(node, "total_comment_count") {
            if let Some(c) = c_val.as_i64() {
                comment_count = comment_count.max(c);
            }
        }

        let mut share_count = 0_i64;
        for s_val in DataHelper::find_key(node, "share_count") {
            if let Some(c) = s_val.get("count").and_then(|v| v.as_i64()) {
                share_count = share_count.max(c);
            }
        }

        let mut group_id = group_id_override.unwrap_or("unknown").to_string();
        let mut group_name = String::new();
        for to_val in DataHelper::find_key(node, "target_group")
            .into_iter()
            .chain(DataHelper::find_key(node, "to"))
            .chain(DataHelper::find_key(node, "owning_profile"))
        {
            if group_id == "unknown" {
                if let Some(gid) = to_val.get("id").and_then(|v| v.as_str()) {
                    group_id =
                        DataHelper::decode_relay_numeric_id(gid).unwrap_or_else(|| gid.to_string());
                }
            }
            if group_name.is_empty() {
                if let Some(gname) = to_val.get("name").and_then(|v| v.as_str()) {
                    if !gname.trim().is_empty() {
                        group_name = gname.trim().to_string();
                    }
                }
            }
        }

        let mut feedback_id = String::new();
        for fb_val in DataHelper::find_key(node, "feedback") {
            if let Some(fid) = fb_val.get("id").and_then(|v| v.as_str()) {
                if !fid.is_empty() {
                    feedback_id = fid.to_string();
                    break;
                }
            }
        }
        if feedback_id.is_empty() {
            use base64::Engine;
            feedback_id =
                base64::engine::general_purpose::STANDARD.encode(format!("feedback:{}", post_id));
        }

        let mut attachments = Vec::new();
        let mut seen_urls = HashSet::new();
        for link in DocumentLinker::extract_urls_from_text(&content) {
            if seen_urls.insert(link.clone()) {
                attachments.push(json!({
                    "id": format!("att_{}_{}", post_id, attachments.len()),
                    "type": "ExternalLink",
                    "url": link,
                    "title": "",
                }));
            }
        }

        for att_arr in DataHelper::find_key(node, "attachments") {
            if let Some(arr) = att_arr.as_array() {
                for item in arr {
                    for uri_val in DataHelper::find_key(item, "uri")
                        .into_iter()
                        .chain(DataHelper::find_key(item, "playable_url"))
                    {
                        if let Some(u) = uri_val.as_str() {
                            if u.starts_with("http") && seen_urls.insert(u.to_string()) {
                                attachments.push(json!({
                                    "id": format!("att_{}_{}", post_id, attachments.len()),
                                    "type": "Media",
                                    "url": DocumentLinker::clean_fb_redirect(u),
                                    "title": "",
                                }));
                            }
                        }
                    }
                }
            }
        }

        let comments = CommentExtractor::extract_all_from_node(node, &post_id);

        if content.is_empty() && attachments.is_empty() && comments.is_empty() {
            return None;
        }

        Some(json!({
            "post_id": post_id,
            "group_id": group_id,
            "group_name": group_name,
            "feedback_id": feedback_id,
            "url": url,
            "created_at": created_at,
            "content": content,
            "author": author,
            "stats": {
                "reactions": reaction_count,
                "comments": comment_count,
                "shares": share_count,
            },
            "attachments": attachments,
            "comments": comments,
        }))
    }
}

pub struct CommentExtractor;

impl CommentExtractor {
    pub fn extract_all_from_node(root: &Value, default_post_id: &str) -> Vec<Value> {
        let mut results = Vec::new();
        let mut seen_ids = HashSet::new();
        let mut queue = VecDeque::new();
        queue.push_back(root);

        while let Some(curr) = queue.pop_front() {
            match curr {
                Value::Object(map) => {
                    let is_comment = map
                        .get("__typename")
                        .and_then(|v| v.as_str())
                        .map(|t| t == "Comment")
                        .unwrap_or(false)
                        || (map.contains_key("legacy_fbid")
                            && map.contains_key("author")
                            && map.contains_key("body"));

                    if is_comment {
                        if let Some(c) = Self::parse_single_comment(curr, default_post_id) {
                            if let Some(cid) = c.get("comment_id").and_then(|v| v.as_str()) {
                                if seen_ids.insert(cid.to_string()) {
                                    results.push(c);
                                }
                            }
                        }
                    }

                    for (_, v) in map {
                        if v.is_object() || v.is_array() {
                            queue.push_back(v);
                        }
                    }
                }
                Value::Array(arr) => {
                    for item in arr {
                        if item.is_object() || item.is_array() {
                            queue.push_back(item);
                        }
                    }
                }
                _ => {}
            }
        }

        results
    }

    fn parse_single_comment(node: &Value, default_post_id: &str) -> Option<Value> {
        let raw_id = node
            .get("legacy_fbid")
            .or_else(|| node.get("id"))?
            .as_str()?;
        let comment_id =
            DataHelper::decode_relay_numeric_id(raw_id).unwrap_or_else(|| raw_id.to_string());

        let author = node
            .get("author")
            .and_then(AuthorExtractor::extract_from_actor)
            .unwrap_or_else(
                || json!({"id": "unknown", "name": "Unknown", "url": "", "avatar": ""}),
            );

        let content = node
            .get("body")
            .and_then(|b| b.get("text"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        let created_at = node
            .get("created_time")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);

        let mut attachments = Vec::new();
        for link in DocumentLinker::extract_urls_from_text(&content) {
            attachments.push(json!({
                "id": format!("catt_{}_{}", comment_id, attachments.len()),
                "type": "ExternalLink",
                "url": link,
                "title": "",
            }));
        }

        Some(json!({
            "comment_id": comment_id,
            "post_id": default_post_id,
            "parent_id": Value::Null,
            "created_at": created_at,
            "content": content,
            "author": author,
            "reaction_count": 0,
            "attachments": attachments,
        }))
    }
}
