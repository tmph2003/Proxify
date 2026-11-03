//! Export captured requests to JSON, HAR 1.2, Python `requests`, and cURL formats.

use serde_json::{json, Value};
use url::Url;

pub fn export_to_json(requests: &[Value], pretty: bool) -> String {
    let mut cleaned = Vec::with_capacity(requests.len());

    for req in requests {
        let mut entry = json!({
            "id": req.get("id"),
            "timestamp": req.get("timestamp"),
            "method": req.get("method"),
            "url": req.get("url"),
            "domain": req.get("domain"),
            "status_code": req.get("status_code"),
            "duration_ms": req.get("duration_ms"),
            "request": {
                "headers": req.get("request_headers").cloned().unwrap_or_else(|| json!({})),
                "body": req.get("request_body"),
                "content_type": req.get("request_content_type"),
            },
            "response": {
                "headers": req.get("response_headers").cloned().unwrap_or_else(|| json!({})),
                "body": req.get("response_body"),
                "content_type": req.get("response_content_type"),
                "size": req.get("response_size"),
            }
        });

        let is_gql = req.get("is_graphql").and_then(|v| v.as_i64()).unwrap_or(0) != 0;
        if is_gql {
            let vars_val = req
                .get("graphql_variables")
                .and_then(|v| v.as_str())
                .map(|s| {
                    serde_json::from_str::<Value>(s)
                        .unwrap_or_else(|_| Value::String(s.to_string()))
                })
                .unwrap_or(Value::Null);

            entry["graphql"] = json!({
                "operation": req.get("graphql_operation"),
                "doc_id": req.get("graphql_doc_id"),
                "variables": vars_val,
            });
        }
        cleaned.push(entry);
    }

    if pretty {
        serde_json::to_string_pretty(&cleaned).unwrap_or_else(|_| "[]".to_string())
    } else {
        serde_json::to_string(&cleaned).unwrap_or_else(|_| "[]".to_string())
    }
}

pub fn export_to_har(requests: &[Value]) -> String {
    let mut entries = Vec::with_capacity(requests.len());

    for req in requests {
        let req_headers = headers_to_har(req.get("request_headers"));
        let resp_headers = headers_to_har(req.get("response_headers"));

        let url_str = req.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let mut query_params = Vec::new();
        if let Ok(parsed) = Url::parse(url_str) {
            for (k, v) in parsed.query_pairs() {
                query_params.push(json!({"name": k, "value": v}));
            }
        }

        let req_body = req
            .get("request_body")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let req_ct = req
            .get("request_content_type")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let mut entry = json!({
            "startedDateTime": req.get("timestamp").and_then(|v| v.as_str()).unwrap_or(""),
            "time": req.get("duration_ms").and_then(|v| v.as_f64()).unwrap_or(0.0),
            "request": {
                "method": req.get("method").and_then(|v| v.as_str()).unwrap_or("GET"),
                "url": url_str,
                "httpVersion": "HTTP/2.0",
                "headers": req_headers,
                "queryString": query_params,
                "cookies": [],
                "headersSize": -1,
                "bodySize": req_body.len(),
            },
            "response": {
                "status": req.get("status_code").and_then(|v| v.as_i64()).unwrap_or(0),
                "statusText": "",
                "httpVersion": "HTTP/2.0",
                "headers": resp_headers,
                "cookies": [],
                "content": {
                    "size": req.get("response_size").and_then(|v| v.as_i64()).unwrap_or(0),
                    "mimeType": req.get("response_content_type").and_then(|v| v.as_str()).unwrap_or(""),
                    "text": req.get("response_body").and_then(|v| v.as_str()).unwrap_or(""),
                },
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": req.get("response_size").and_then(|v| v.as_i64()).unwrap_or(0),
            },
            "cache": {},
            "timings": {
                "send": 0,
                "wait": req.get("duration_ms").and_then(|v| v.as_f64()).unwrap_or(0.0),
                "receive": 0,
            }
        });

        if !req_body.is_empty() {
            let mut post_data = json!({
                "mimeType": req_ct,
                "text": req_body,
            });
            if req_ct.contains("x-www-form-urlencoded") {
                let mut params = Vec::new();
                for (k, v) in url::form_urlencoded::parse(req_body.as_bytes()) {
                    params.push(json!({"name": k, "value": v}));
                }
                post_data["params"] = Value::Array(params);
            }
            entry["request"]["postData"] = post_data;
        }

        entries.push(entry);
    }

    let har = json!({
        "log": {
            "version": "1.2",
            "creator": {"name": "Proxify Rust", "version": "2.0.0"},
            "entries": entries,
        }
    });

    serde_json::to_string_pretty(&har).unwrap_or_else(|_| "{}".to_string())
}

pub fn export_to_python(requests: &[Value]) -> String {
    let mut lines = vec!["import requests".to_string(), String::new()];
    let skip_headers = [
        "content-length",
        "host",
        "connection",
        "accept-encoding",
        "transfer-encoding",
    ];

    for (i, req) in requests.iter().enumerate() {
        let method = req
            .get("method")
            .and_then(|v| v.as_str())
            .unwrap_or("GET")
            .to_ascii_lowercase();
        let url = req.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let domain = req.get("domain").and_then(|v| v.as_str()).unwrap_or("");
        let path = req.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let id = req
            .get("id")
            .and_then(|v| v.as_i64())
            .unwrap_or((i + 1) as i64);

        lines.push(format!(
            "# Request #{}: {} {}{}",
            id,
            method.to_ascii_uppercase(),
            domain,
            path
        ));

        let mut filtered_headers = serde_json::Map::new();
        if let Some(Value::Object(map)) = req.get("request_headers") {
            for (k, v) in map {
                if !skip_headers.contains(&k.to_ascii_lowercase().as_str()) {
                    filtered_headers.insert(k.clone(), v.clone());
                }
            }
        }

        if !filtered_headers.is_empty() {
            lines.push(format!(
                "headers_{} = {}",
                i,
                serde_json::to_string_pretty(&filtered_headers)
                    .unwrap_or_else(|_| "{}".to_string())
            ));
            lines.push(String::new());
        }

        let mut args = vec![format!("{:?}", url)];
        if !filtered_headers.is_empty() {
            args.push(format!("headers=headers_{}", i));
        }

        if let Some(body) = req.get("request_body").and_then(|v| v.as_str()) {
            if !body.is_empty() {
                lines.push(format!("data_{} = {:?}", i, body));
                lines.push(String::new());
                args.push(format!("data=data_{}", i));
            }
        }

        lines.push(format!(
            "response_{} = requests.{}({})",
            i,
            method,
            args.join(", ")
        ));
        lines.push(String::new());
    }

    lines.join("\n")
}

pub fn export_to_curl(requests: &[Value]) -> String {
    let mut commands = Vec::with_capacity(requests.len());
    let skip_headers = ["content-length", "host", "connection"];

    for req in requests {
        let method = req.get("method").and_then(|v| v.as_str()).unwrap_or("GET");
        let url = req.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let domain = req.get("domain").and_then(|v| v.as_str()).unwrap_or("");
        let path = req.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let id = req
            .get("id")
            .and_then(|v| v.as_i64())
            .map(|n| n.to_string())
            .unwrap_or_else(|| "?".to_string());

        let mut parts = vec!["curl".to_string()];
        if method != "GET" {
            parts.push(format!("-X {}", method));
        }
        parts.push(format!("'{}'", url));

        if let Some(Value::Object(map)) = req.get("request_headers") {
            for (k, v) in map {
                if !skip_headers.contains(&k.to_ascii_lowercase().as_str()) {
                    let v_str = v.as_str().unwrap_or("");
                    let escaped = v_str.replace('\'', "'\\''");
                    parts.push(format!("-H '{}: {}'", k, escaped));
                }
            }
        }

        if let Some(body) = req.get("request_body").and_then(|v| v.as_str()) {
            if !body.is_empty() {
                let mut escaped = body.replace('\'', "'\\''");
                if escaped.len() > 2000 {
                    escaped.truncate(2000);
                    escaped.push_str("... [truncated]");
                }
                parts.push(format!("--data-raw '{}'", escaped));
            }
        }

        commands.push(format!(
            "# Request #{}: {} {}{}\n{}",
            id,
            method,
            domain,
            path,
            parts.join(" \\\n  ")
        ));
    }

    commands.join("\n\n")
}

fn headers_to_har(headers: Option<&Value>) -> Vec<Value> {
    let mut out = Vec::new();
    if let Some(Value::Object(map)) = headers {
        for (k, v) in map {
            out.push(json!({
                "name": k,
                "value": v.as_str().unwrap_or(""),
            }));
        }
    }
    out
}

pub struct RequestExporter;

impl RequestExporter {
    pub fn to_json(requests: &[Value], pretty: bool) -> String {
        export_to_json(requests, pretty)
    }

    pub fn to_har(requests: &[Value]) -> String {
        export_to_har(requests)
    }

    pub fn to_python(requests: &[Value]) -> String {
        export_to_python(requests)
    }

    pub fn to_curl(requests: &[Value]) -> String {
        export_to_curl(requests)
    }
}
