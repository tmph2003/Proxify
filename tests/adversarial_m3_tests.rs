//! Adversarial Stress & Architecture Decoupling Verification Suite (Milestone 3)
//!
//! Specifically validates the 4 adversarial attack vectors assigned to Challenger 1:
//! 1. Zalo Stream Exclusion & Mutator Delivery:
//!    Verifies whether `trusted-device-bridge.js` is excluded from streaming and properly
//!    delivered to `ZaloHookMutator` when upstream responds with `Content-Type: application/javascript`.
//! 2. YouTube 18 Stream Path Rules:
//!    Verifies that all 18 path rules across YouTube and Google domains are correctly matched,
//!    including subdomains, query parameters, and case variants, while non-streaming paths are not.
//! 3. Concurrent GraphQL Alias Resolution:
//!    Fires concurrent requests across multiple threads using `fb_api_req_friendly_name`,
//!    `operationName`, `query_name`, and dynamic registration to stress-test parking_lot RwLock safety.
//! 4. Edge-Case Matrix:
//!    Tests host-with-port matching, URL-casing, and overlapping stream rules.

use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::{Response, StatusCode};
use proxify::test_helpers::*;
use proxify_core::graphql::GraphQLParser;
use proxify_core::router::ProxyRouter;
use proxify_sdk::{async_trait, HttpFlow, MutatorInterceptor};
use std::sync::Arc;

// =========================================================================
// 1. Zalo Stream Exclusion & Mutator Delivery Adversarial Test
// =========================================================================

struct MockZaloHookMutator {
    pub injected_bridge: &'static str,
}

#[async_trait]
impl MutatorInterceptor for MockZaloHookMutator {
    async fn mutate_request(&self, _flow: &mut HttpFlow) {}

    async fn mutate_response(&self, flow: &mut HttpFlow) {
        let path = flow.request.path.clone();
        if path.contains("trusted-device-bridge") && path.ends_with(".js") {
            if let Some(resp) = flow.response.as_mut() {
                resp.content = Bytes::from(self.injected_bridge);
            }
        }
    }
}

#[tokio::test]
async fn test_adv_zalo_trusted_device_bridge_stream_exclusion_mutator_delivery() {
    let proxy = TestProxyServer::start().await;

    const INJECTED_CODE: &str = "// PROXIFY_MUTATED_ZALO_BRIDGE_PAYLOAD_V3";
    const UPSTREAM_RAW_CODE: &str = "// ORIGINAL_UPSTREAM_ZALO_BRIDGE_UNTOUCHED";

    let mutator = Arc::new(MockZaloHookMutator {
        injected_bridge: INJECTED_CODE,
    });

    // Register mutator and stream exclusion on 127.0.0.1
    proxy.router.register_mutator("127.0.0.1", mutator.clone());
    proxy
        .router
        .register_stream_exclusion("127.0.0.1", "trusted-device-bridge");

    // Also register on chat.zalo.me and *.zalo.me
    proxy.router.register_mutator("*.zalo.me", mutator.clone());
    proxy.router.register_mutator("chat.zalo.me", mutator);
    proxy
        .router
        .register_stream_exclusion("*.zalo.me", "trusted-device-bridge");
    proxy
        .router
        .register_stream_exclusion("chat.zalo.me", "trusted-device-bridge");

    // Verify router level logic first
    assert!(
        proxy
            .router
            .is_stream_excluded("127.0.0.1", "/assets/trusted-device-bridge.js"),
        "Router must recognize 127.0.0.1 /assets/trusted-device-bridge.js as stream-excluded"
    );
    assert!(
        proxy
            .router
            .is_stream_excluded("chat.zalo.me", "/v2/trusted-device-bridge.js"),
        "Router must recognize chat.zalo.me /v2/trusted-device-bridge.js as stream-excluded"
    );

    // Upstream server serves the JS file with standard Content-Type: application/javascript
    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        assert!(req.uri().path().contains("trusted-device-bridge.js"));
        Response::builder()
            .status(StatusCode::OK)
            .header("Content-Type", "application/javascript; charset=utf-8")
            .header("X-Upstream-Original", "true")
            .body(Full::new(Bytes::from_static(UPSTREAM_RAW_CODE.as_bytes())).boxed())
            .unwrap()
    })
    .await;

    let target_url = upstream.url("/assets/trusted-device-bridge.js");
    let (status, headers, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &target_url,
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    let body_str = String::from_utf8_lossy(&body);

    println!("[Adversarial Test] Received body: {:?}", body_str);
    println!("[Adversarial Test] Received headers: {:?}", headers);

    // CRITICAL ADVERSARIAL CHECK:
    // If the proxy streamed the JS response because Content-Type contains 'javascript',
    // then mutate_response was bypassed and body_str contains UPSTREAM_RAW_CODE.
    // If stream exclusion worked completely through the forward_upstream pipeline,
    // then body_str contains INJECTED_CODE!
    assert_eq!(
        body_str, INJECTED_CODE,
        "trusted-device-bridge.js must NOT be streamed! It must be delivered to Zalo mutator so the payload is rewritten."
    );
}

// =========================================================================
// 2. YouTube 18 Stream Path Rules Verification
// =========================================================================

#[test]
fn test_adv_youtube_18_path_rules_coverage_matrix() {
    let router = ProxyRouter::new();

    const YOUTUBE_STREAM_PATHS: &[&str] = &[
        "/live_chat",
        "/youtubei/v1/live_chat/",
        "/youtubei/v1/log_event",
        "/youtubei/v1/feedback",
        "/youtubei/v1/updated_metadata",
        "/youtubei/v1/notification/",
        "/youtubei/v1/att/",
        "/api/stats/",
        "/videoplayback",
        "/api/manifest/",
        "/punctual/",
        "/rotatecookiespage",
        "/generate_204",
        "/gen_204",
        "/error_204",
        "/csi_204",
        "/s/player/",
        "/s/desktop/",
        "/s/_/ytmainappweb/",
    ];

    assert_eq!(
        YOUTUBE_STREAM_PATHS.len(),
        19,
        "There must be exactly 19 YouTube path rules"
    );

    let stream_domains = [
        "*.youtube.com",
        "youtube.com",
        "*.googlevideo.com",
        "googlevideo.com",
        "*.google.com",
        "google.com",
    ];

    for domain in stream_domains {
        for path in YOUTUBE_STREAM_PATHS {
            router.register_stream_path_rule(domain, path);
        }
    }

    // Test matrix across various actual hostnames
    let test_hosts = [
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube.com",
        "rr1.googlevideo.com",
        "rr2---sn-4g5ednks.googlevideo.com",
        "googlevideo.com",
        "play.google.com",
        "apis.google.com",
        "google.com",
    ];

    for host in test_hosts {
        for path in YOUTUBE_STREAM_PATHS {
            // Direct path match
            assert!(
                router.should_stream_path(host, path),
                "Host '{}' path '{}' must match streaming path rule",
                host,
                path
            );

            // Path with query parameters (e.g. /live_chat?v=123)
            let path_with_query = format!("{}?param1=abc&param2=123", path);
            assert!(
                router.should_stream_path(host, &path_with_query),
                "Host '{}' path '{}' must match streaming rule with query string",
                host,
                path_with_query
            );

            // Path with sub-path (e.g. /videoplayback/id/123)
            let sub_path = format!("{}/sub_resource", path.trim_end_matches('/'));
            assert!(
                router.should_stream_path(host, &sub_path),
                "Host '{}' path '{}' must match streaming prefix rule",
                host,
                sub_path
            );

            // Case insensitivity of path (e.g. /LIVE_CHAT)
            let upper_path = path.to_uppercase();
            assert!(
                router.should_stream_path(host, &upper_path),
                "Host '{}' upper path '{}' must match case-insensitively",
                host,
                upper_path
            );

            // Host with port (e.g. www.youtube.com:443)
            let host_with_port = format!("{}:443", host);
            assert!(
                router.should_stream_path(&host_with_port, path),
                "Host with port '{}' path '{}' must match streaming rule",
                host_with_port,
                path
            );
        }
    }

    // Negative tests: Paths that should NOT be streamed
    let non_stream_paths = [
        "/watch",
        "/watch?v=dQw4w9WgXcQ",
        "/shorts/abcdef",
        "/feed/subscriptions",
        "/channel/UC123456",
        "/results?search_query=rust",
        "/api/custom_endpoint",
        "/about",
    ];

    for host in test_hosts {
        for path in non_stream_paths {
            assert!(
                !router.should_stream_path(host, path),
                "Host '{}' path '{}' must NOT match streaming rule",
                host,
                path
            );
        }
    }

    // Negative tests: Domains that are NOT in YouTube/Google stream rules
    let non_stream_domains = [
        "vimeo.com",
        "dailymotion.com",
        "twitch.tv",
        "facebook.com",
        "zalo.me",
        "example.com",
    ];

    for host in non_stream_domains {
        for path in YOUTUBE_STREAM_PATHS {
            assert!(
                !router.should_stream_path(host, path),
                "External host '{}' path '{}' must NOT be streamed under YouTube rules",
                host,
                path
            );
        }
    }
}

// =========================================================================
// 3. Concurrent GraphQL Alias Resolution Across Multiple Threads
// =========================================================================

#[tokio::test]
async fn test_adv_graphql_concurrent_alias_resolution_stress() {
    GraphQLParser::register_operation_alias("fb_api_req_friendly_name");
    GraphQLParser::register_query_alias("doc_id");

    let mut handles = Vec::new();

    // Spawn 50 concurrent tasks querying GraphQL simultaneously with different aliases
    for task_id in 0..50 {
        let handle = tokio::spawn(async move {
            match task_id % 4 {
                0 => {
                    // Form-urlencoded with fb_api_req_friendly_name & doc_id
                    let body = format!(
                        "fb_api_req_friendly_name=Query_{}&doc_id=10000{}&variables=%7B%7D",
                        task_id, task_id
                    );
                    let info = GraphQLParser::parse(
                        "https://www.facebook.com/api/graphql/",
                        "POST",
                        "application/x-www-form-urlencoded",
                        Some(body.as_bytes()),
                    )
                    .expect("Failed to parse fb_api_req_friendly_name form-urlencoded");

                    assert_eq!(
                        info.operation_name.as_deref(),
                        Some(format!("Query_{}", task_id).as_str())
                    );
                    assert_eq!(
                        info.query.as_deref(),
                        Some(format!("doc_id: 10000{}", task_id).as_str())
                    );
                }
                1 => {
                    // Standard operationName in JSON body
                    let body = format!(
                        r#"{{"operationName":"JsonOp_{}","query":"query JsonOp_{} {{ user {{ id }} }}"}}"#,
                        task_id, task_id
                    );
                    let info = GraphQLParser::parse(
                        "https://api.example.com/graphql",
                        "POST",
                        "application/json",
                        Some(body.as_bytes()),
                    )
                    .expect("Failed to parse standard operationName JSON");

                    assert_eq!(
                        info.operation_name.as_deref(),
                        Some(format!("JsonOp_{}", task_id).as_str())
                    );
                }
                2 => {
                    // GET query with query_name parameter
                    let url = format!(
                        "https://api.example.com/graphql?query_name=GetFeed_{}&query=%7Bfeed%7Bitems%7D%7D",
                        task_id
                    );
                    let info = GraphQLParser::parse(&url, "GET", "", None)
                        .expect("Failed to parse GET query_name parameter");

                    assert_eq!(
                        info.operation_name.as_deref(),
                        Some(format!("GetFeed_{}", task_id).as_str())
                    );
                    assert_eq!(info.query.as_deref(), Some("{feed{items}}"));
                }
                _ => {
                    // Dynamic registration in parallel with parsing
                    let custom_alias = format!("custom_op_alias_{}", task_id);
                    GraphQLParser::register_operation_alias(&custom_alias);

                    let body = format!("{}=OpVal_{}&query=test", custom_alias, task_id);
                    let info = GraphQLParser::parse(
                        "https://api.example.com/graphql",
                        "POST",
                        "application/x-www-form-urlencoded",
                        Some(body.as_bytes()),
                    );
                    assert!(
                        info.is_some(),
                        "Dynamically registered alias must be recognized"
                    );
                }
            }
        });
        handles.push(handle);
    }

    for h in handles {
        h.await.expect("Concurrent GraphQL task panicked");
    }
}

#[test]
fn test_adv_graphql_json_alias_resolution() {
    GraphQLParser::register_operation_alias("query_name");
    GraphQLParser::register_operation_alias("fb_api_req_friendly_name");
    GraphQLParser::register_query_alias("doc_id");

    // JSON body with custom operation alias query_name
    let body1 = br#"{"query_name":"GetUserFeed","query":"query { feed }"}"#;
    let info1 = GraphQLParser::parse(
        "https://api.example.com/graphql",
        "POST",
        "application/json",
        Some(body1),
    );

    // JSON body with Facebook aliases
    let body2 = br#"{"fb_api_req_friendly_name":"FBFeed","doc_id":"98765"}"#;
    let info2 = GraphQLParser::parse(
        "https://www.facebook.com/api/graphql",
        "POST",
        "application/json",
        Some(body2),
    );

    println!("[GraphQL JSON Test] info1: {:?}", info1);
    println!("[GraphQL JSON Test] info2: {:?}", info2);

    assert!(info1.is_some(), "info1 must be parsed from JSON payload");
    let i1 = info1.unwrap();
    assert_eq!(i1.operation_name.as_deref(), Some("GetUserFeed"));
    assert_eq!(i1.query.as_deref(), Some("query { feed }"));

    assert!(info2.is_some(), "info2 must be parsed from JSON payload");
    let i2 = info2.unwrap();
    assert_eq!(i2.operation_name.as_deref(), Some("FBFeed"));
    assert_eq!(i2.query.as_deref(), Some("98765"));
}

// =========================================================================
// 4. Stream Exclusion Matrix: Case-Insensitivity & Overlapping Rules
// =========================================================================

#[test]
fn test_adv_stream_exclusion_rules_matrix() {
    let router = ProxyRouter::new();

    // Register stream rules
    router.register_stream_rule("*.zalo.me");
    router.register_stream_rule("zalo.me");
    router.register_stream_rule("chat.zalo.me");

    // Register stream exclusions
    router.register_stream_exclusion("*.zalo.me", "trusted-device-bridge");
    router.register_stream_exclusion("zalo.me", "trusted-device-bridge");
    router.register_stream_exclusion("chat.zalo.me", "trusted-device-bridge");

    // Normal JS file under chat.zalo.me should stream
    assert!(
        router.should_stream_request("chat.zalo.me", "/assets/app.js"),
        "Normal app.js must stream"
    );

    // trusted-device-bridge under chat.zalo.me must be excluded
    assert!(
        router.is_stream_excluded("chat.zalo.me", "/assets/trusted-device-bridge.js"),
        "trusted-device-bridge must be excluded"
    );
    assert!(
        !router.should_stream_request("chat.zalo.me", "/assets/trusted-device-bridge.js"),
        "should_stream_request must return false for trusted-device-bridge"
    );

    // Subdomain wildcard matching (e.g. dev.chat.zalo.me)
    assert!(
        router.is_stream_excluded("dev.chat.zalo.me", "/v1/trusted-device-bridge.js"),
        "Wildcard *.zalo.me must exclude on subdomains"
    );

    // Case insensitivity in path
    assert!(
        router.is_stream_excluded("chat.zalo.me", "/assets/Trusted-Device-Bridge.js"),
        "Mixed case path must be excluded"
    );

    // Host with port
    assert!(
        router.is_stream_excluded("chat.zalo.me:8080", "/assets/trusted-device-bridge.js"),
        "Host with port must be excluded"
    );
}
