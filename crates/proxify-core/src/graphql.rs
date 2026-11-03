use parking_lot::RwLock;
use serde_json::Value;
use std::sync::LazyLock;
use url::Url;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GraphQLInfo {
    pub operation_name: Option<String>,
    pub query: Option<String>,
    pub variables: Option<String>,
}

static OPERATION_ALIASES: LazyLock<RwLock<Vec<String>>> = LazyLock::new(|| {
    RwLock::new(vec![
        "operationName".to_string(),
        "operation_name".to_string(),
        "query_name".to_string(),
        "op".to_string(),
    ])
});

static QUERY_ALIASES: LazyLock<RwLock<Vec<String>>> = LazyLock::new(|| {
    RwLock::new(vec![
        "query".to_string(),
        "query_id".to_string(),
        "document_id".to_string(),
    ])
});

static VARIABLES_ALIASES: LazyLock<RwLock<Vec<String>>> =
    LazyLock::new(|| RwLock::new(vec!["variables".to_string(), "vars".to_string()]));

pub struct GraphQLParser;

impl GraphQLParser {
    pub fn register_operation_alias(alias: &str) {
        let clean = alias.trim();
        if !clean.is_empty() {
            let mut list = OPERATION_ALIASES.write();
            if !list.iter().any(|a| a.eq_ignore_ascii_case(clean)) {
                list.push(clean.to_string());
            }
        }
    }

    pub fn register_query_alias(alias: &str) {
        let clean = alias.trim();
        if !clean.is_empty() {
            let mut list = QUERY_ALIASES.write();
            if !list.iter().any(|a| a.eq_ignore_ascii_case(clean)) {
                list.push(clean.to_string());
            }
        }
    }

    fn is_operation_key(key: &str) -> bool {
        OPERATION_ALIASES
            .read()
            .iter()
            .any(|a| a.eq_ignore_ascii_case(key))
    }

    fn is_query_key(key: &str) -> bool {
        QUERY_ALIASES
            .read()
            .iter()
            .any(|a| a.eq_ignore_ascii_case(key))
    }

    fn is_variables_key(key: &str) -> bool {
        VARIABLES_ALIASES
            .read()
            .iter()
            .any(|a| a.eq_ignore_ascii_case(key))
    }

    fn has_graphql_keys_in_form(body_str: &str) -> bool {
        let ops = OPERATION_ALIASES.read();
        let qrys = QUERY_ALIASES.read();
        ops.iter().any(|op| body_str.contains(&format!("{}=", op)))
            || qrys.iter().any(|q| body_str.contains(&format!("{}=", q)))
    }

    pub fn parse(
        url: &str,
        method: &str,
        content_type: &str,
        body: Option<&[u8]>,
    ) -> Option<GraphQLInfo> {
        let url_lower = url.to_lowercase();
        let is_gql_url = url_lower.contains("/graphql") || url_lower.contains("api/graphql");

        if method.eq_ignore_ascii_case("GET") && is_gql_url {
            if let Ok(parsed) = Url::parse(url) {
                let mut op = None;
                let mut q = None;
                let mut vars = None;
                for (k, v) in parsed.query_pairs() {
                    let key = k.as_ref();
                    if Self::is_operation_key(key) && op.is_none() {
                        op = Some(v.into_owned());
                    } else if Self::is_query_key(key) && q.is_none() {
                        q = Some(v.into_owned());
                    } else if Self::is_variables_key(key) && vars.is_none() {
                        vars = Some(v.into_owned());
                    }
                }
                if op.is_some() || q.is_some() {
                    return Some(GraphQLInfo {
                        operation_name: op,
                        query: q,
                        variables: vars,
                    });
                }
            }
        }

        let raw_bytes = body?;
        if raw_bytes.is_empty() {
            return None;
        }
        let body_str = std::str::from_utf8(raw_bytes).ok()?;

        if content_type.contains("urlencoded") || Self::has_graphql_keys_in_form(body_str) {
            let mut op = None;
            let mut doc_id = None;
            let mut vars = None;

            for (k, v) in url::form_urlencoded::parse(raw_bytes) {
                let key = k.as_ref();
                if Self::is_operation_key(key) && op.is_none() && !v.is_empty() {
                    op = Some(v.into_owned());
                } else if Self::is_query_key(key) && doc_id.is_none() && !v.is_empty() {
                    if key.contains("doc_id") || key.contains("document_id") {
                        doc_id = Some(format!("doc_id: {}", v));
                    } else {
                        doc_id = Some(v.into_owned());
                    }
                } else if Self::is_variables_key(key) && vars.is_none() && !v.is_empty() {
                    vars = Some(v.into_owned());
                }
            }

            if op.is_some() || doc_id.is_some() {
                return Some(GraphQLInfo {
                    operation_name: op,
                    query: doc_id,
                    variables: vars,
                });
            }
        }

        let trimmed = body_str.trim_start();
        if trimmed.starts_with('{') {
            if let Ok(Value::Object(map)) = serde_json::from_str::<Value>(trimmed) {
                let op = map
                    .iter()
                    .find(|(k, _)| Self::is_operation_key(k))
                    .and_then(|(_, v)| v.as_str())
                    .map(|s| s.to_string());
                let q = map
                    .iter()
                    .find(|(k, _)| Self::is_query_key(k))
                    .and_then(|(_, v)| {
                        v.as_str()
                            .map(|s| s.to_string())
                            .or_else(|| v.as_i64().map(|n| n.to_string()))
                            .or_else(|| v.as_u64().map(|u| u.to_string()))
                    });
                let vars = map
                    .iter()
                    .find(|(k, _)| Self::is_variables_key(k))
                    .and_then(|(_, v)| {
                        if v.is_null() {
                            None
                        } else {
                            serde_json::to_string(v).ok()
                        }
                    });

                if op.is_some() || q.is_some() || (is_gql_url && vars.is_some()) {
                    return Some(GraphQLInfo {
                        operation_name: op,
                        query: q,
                        variables: vars,
                    });
                }
            }
        }

        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_fb_urlencoded() {
        GraphQLParser::register_operation_alias("fb_api_req_friendly_name");
        GraphQLParser::register_query_alias("doc_id");

        let body = b"fb_api_req_friendly_name=GroupsCometFeedQuery&doc_id=123456&variables=%7B%22id%22%3A%22999%22%7D";
        let info = GraphQLParser::parse(
            "https://www.facebook.com/api/graphql/",
            "POST",
            "application/x-www-form-urlencoded",
            Some(body),
        )
        .unwrap();
        assert_eq!(info.operation_name.as_deref(), Some("GroupsCometFeedQuery"));
        assert_eq!(info.query.as_deref(), Some("doc_id: 123456"));
    }

    #[test]
    fn test_generic_graphql_operation_name_and_query_name() {
        let info_get = GraphQLParser::parse(
            "https://api.example.com/graphql?query_name=GetUserProfile&query=%7Buser%7Bid%7D%7D",
            "GET",
            "",
            None,
        )
        .unwrap();
        assert_eq!(info_get.operation_name.as_deref(), Some("GetUserProfile"));
        assert_eq!(info_get.query.as_deref(), Some("{user{id}}"));

        let body_json =
            br#"{"operationName":"FeedQuery","query":"query FeedQuery { feed { id } }"}"#;
        let info_json = GraphQLParser::parse(
            "https://api.example.com/graphql",
            "POST",
            "application/json",
            Some(body_json),
        )
        .unwrap();
        assert_eq!(info_json.operation_name.as_deref(), Some("FeedQuery"));
        assert_eq!(
            info_json.query.as_deref(),
            Some("query FeedQuery { feed { id } }")
        );
    }
}
