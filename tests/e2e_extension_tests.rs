//! Tier 4 Opaque-Box Integration Tests: Extension Plugins & Interceptor Subsystems
//!
//! Covers:
//! - YouTube AdBlock request blocking (204 No Content synthetic responses)
//! - YouTube anti-AFK watchdog script injection and JSON ad stripping
//! - YouTube streaming & noise record filtering
//! - Zalo extension mutators & media stream rules
//! - Facebook GraphQL request/response observation and event bus dispatching
//! - Radix-Trie domain routing hierarchy (exact, wildcard, global)
//! - Chained mutator request/response transformation pipeline

use ext_facebook::FacebookGraphQLObserver;
use ext_youtube::{
    clean_youtube_json_data, inject_youtube_anti_afk_with_nonce, YouTubeRecordFilter,
};
use proxify::test_helpers::*;
use proxify_core::router::ProxyRouter;
use proxify_sdk::{
    async_trait, FlowRequest, FlowResponse, HttpFlow, MutatorInterceptor, ObserverInterceptor,
    RecordFilter,
};
use serde_json::json;
use std::collections::HashMap;
use std::sync::Arc;

#[tokio::test]
async fn test_tier4_youtube_adblock_request_interception() {
    // Network-level 204 ad blocking is disabled for SABR compatibility (prevents error 282054944
    // and playlist auto-skip). Ads are handled client-side via YOUTUBE_WATCHDOG_JS.
    assert!(
        !ext_youtube::is_youtube_ad_request(
            "googleads.g.doubleclick.net",
            "/pagead/ads",
            "https://googleads.g.doubleclick.net/pagead/ads"
        ),
        "Ad requests must pass through at network level for SABR compatibility"
    );
    assert!(
        !ext_youtube::is_youtube_ad_request(
            "www.youtube.com",
            "/youtubei/v1/player",
            "https://www.youtube.com/youtubei/v1/player"
        ),
        "Player API must not be blocked"
    );
}

#[tokio::test]
async fn test_tier4_youtube_json_ad_stripping_and_anti_afk() {
    let mut api_data = json!({
        "videoDetails": { "title": "Great Video", "videoId": "v123" },
        "adPlacements": [{ "adPlacementRenderer": { "config": "ad_1" } }],
        "playerAds": [{ "playerAdParams": "ad_params" }],
        "messages": [
            {
                "youThereRenderer": {
                    "lactThresholdMs": "1800000",
                    "playbackPauseDelayMs": "30000"
                }
            }
        ]
    });

    let modified = clean_youtube_json_data(&mut api_data);
    assert!(modified, "JSON data must be cleaned");
    assert!(
        api_data.get("adPlacements").is_some(),
        "adPlacements must be preserved for SABR compatibility"
    );
    assert!(
        api_data.get("playerAds").is_none(),
        "playerAds must be removed"
    );

    let messages = api_data["messages"].as_array().unwrap();
    let ytr = &messages[0]["youThereRenderer"];
    assert_eq!(ytr["lactThresholdMs"], "86400000000");
}

#[tokio::test]
async fn test_tier4_youtube_anti_afk_watchdog_injection() {
    let original_html = r#"<!DOCTYPE html><html><head><script nonce="test_csp_nonce">var ytInitialPlayerResponse = {"adPlacements":[{"id":1}]};</script></head><body><h1>YouTube</h1></body></html>"#;
    let transformed = inject_youtube_anti_afk_with_nonce(original_html, "test_csp_nonce");

    assert!(
        transformed.contains("\"adPlacements\""),
        "adPlacements must be preserved for SABR"
    );
    assert!(transformed.contains("id=\"proxify-yt-watchdog\""));
    assert!(transformed.contains("nonce=\"test_csp_nonce\""));
    assert!(transformed.contains("__proxify_anti_afk__"));
}

#[tokio::test]
async fn test_tier4_youtube_record_filter() {
    let filter = YouTubeRecordFilter;

    let ad_flow = HttpFlow {
        request: FlowRequest {
            method: "POST".to_string(),
            url: "https://www.youtube.com/pagead/interaction".to_string(),
            host: "www.youtube.com".to_string(),
            port: 443,
            path: "/pagead/interaction".to_string(),
            scheme: "https".to_string(),
            headers: HashMap::new(),
            content: bytes::Bytes::new(),
            timestamp_start: 0.0,
        },
        response: None,
    };
    // Ad/noise requests must NOT be recorded in database
    assert!(
        !filter.should_record(&ad_flow),
        "Ad noise paths must be filtered out from database recording"
    );

    let video_chunk_flow = HttpFlow {
        request: FlowRequest {
            method: "GET".to_string(),
            url: "https://googlevideo.com/videoplayback?id=123".to_string(),
            host: "rr1.googlevideo.com".to_string(),
            port: 443,
            path: "/videoplayback".to_string(),
            scheme: "https".to_string(),
            headers: HashMap::new(),
            content: bytes::Bytes::new(),
            timestamp_start: 0.0,
        },
        response: None,
    };
    assert!(
        !filter.should_record(&video_chunk_flow),
        "Video chunks must not be recorded in database"
    );

    let regular_watch_flow = HttpFlow {
        request: FlowRequest {
            method: "GET".to_string(),
            url: "https://www.youtube.com/watch?v=abc".to_string(),
            host: "www.youtube.com".to_string(),
            port: 443,
            path: "/watch".to_string(),
            scheme: "https".to_string(),
            headers: HashMap::new(),
            content: bytes::Bytes::new(),
            timestamp_start: 0.0,
        },
        response: Some(FlowResponse {
            status_code: 200,
            headers: HashMap::from([(
                "content-type".to_string(),
                "text/html; charset=utf-8".to_string(),
            )]),
            content: bytes::Bytes::from_static(b"<html></html>"),
        }),
    };
    assert!(
        filter.should_record(&regular_watch_flow),
        "Regular watch page request should be recorded"
    );
}

#[tokio::test]
async fn test_tier4_facebook_graphql_observer_interception() {
    let mock_bus = Arc::new(MockEventBus::new());
    let observer = FacebookGraphQLObserver::new(mock_bus.clone());

    let req_payload = r#"doc_id=123456789&variables={"id":"user_1"}"#;
    let resp_payload = r#"{"data":{"node":{"id":"user_1","name":"Alice"}}}"#;

    let flow = HttpFlow {
        request: FlowRequest {
            method: "POST".to_string(),
            url: "https://www.facebook.com/api/graphql".to_string(),
            host: "www.facebook.com".to_string(),
            port: 443,
            path: "/api/graphql".to_string(),
            scheme: "https".to_string(),
            headers: HashMap::from([(
                "content-type".to_string(),
                "application/x-www-form-urlencoded".to_string(),
            )]),
            content: bytes::Bytes::copy_from_slice(req_payload.as_bytes()),
            timestamp_start: 1000.0,
        },
        response: Some(FlowResponse {
            status_code: 200,
            headers: HashMap::from([("content-type".to_string(), "application/json".to_string())]),
            content: bytes::Bytes::copy_from_slice(resp_payload.as_bytes()),
        }),
    };

    observer.observe_response(&flow).await;

    let events = mock_bus.get_events("facebook.graphql.request");
    assert_eq!(
        events.len(),
        1,
        "Must publish event to facebook.graphql.request topic"
    );
    let event_data = &events[0];
    assert_eq!(event_data["url"], "https://www.facebook.com/api/graphql");
    assert_eq!(event_data["req_body"], req_payload);
    assert_eq!(event_data["resp_body"], resp_payload);
}

#[tokio::test]
async fn test_tier4_radix_trie_domain_routing_hierarchy() {
    let router = ProxyRouter::new();

    struct TestMutator(#[allow(dead_code)] String);
    #[async_trait]
    impl MutatorInterceptor for TestMutator {}

    let m_wildcard = Arc::new(TestMutator("wildcard".to_string()));
    let m_exact = Arc::new(TestMutator("exact".to_string()));
    let m_global = Arc::new(TestMutator("global".to_string()));

    router.register_mutator("*", m_global);
    router.register_mutator("*.youtube.com", m_wildcard);
    router.register_mutator("chat.zalo.me", m_exact);

    // 1. Wildcard match (e.g. music.youtube.com -> global + wildcard = 2 mutators)
    let (_, yt_mutators) = router.resolve("music.youtube.com");
    assert_eq!(yt_mutators.len(), 2);

    // 2. Exact match (chat.zalo.me -> global + exact = 2 mutators)
    let (_, zalo_mutators) = router.resolve("chat.zalo.me");
    assert_eq!(zalo_mutators.len(), 2);

    // 3. Unmatched domain (example.com -> only global = 1 mutator)
    let (_, other_mutators) = router.resolve("example.com");
    assert_eq!(other_mutators.len(), 1);
}

#[tokio::test]
async fn test_tier4_custom_mutator_chain_transformation() {
    struct HeaderInjectorMutator;
    #[async_trait]
    impl MutatorInterceptor for HeaderInjectorMutator {
        async fn mutate_request(&self, flow: &mut HttpFlow) {
            flow.request
                .headers
                .insert("X-Proxify-Injected".to_string(), "level_1".to_string());
        }
    }

    struct BodyRewriteMutator;
    #[async_trait]
    impl MutatorInterceptor for BodyRewriteMutator {
        async fn mutate_response(&self, flow: &mut HttpFlow) {
            if let Some(resp) = flow.response.as_mut() {
                resp.content = bytes::Bytes::from_static(b"rewritten by mutator chain");
            }
        }
    }

    let router = ProxyRouter::new();
    router.register_mutator("api.target.local", Arc::new(HeaderInjectorMutator));
    router.register_mutator("api.target.local", Arc::new(BodyRewriteMutator));

    let (_, mutators) = router.resolve("api.target.local");
    assert_eq!(mutators.len(), 2);

    let mut flow = HttpFlow {
        request: FlowRequest {
            method: "GET".to_string(),
            url: "http://api.target.local/data".to_string(),
            host: "api.target.local".to_string(),
            port: 80,
            path: "/data".to_string(),
            scheme: "http".to_string(),
            headers: HashMap::new(),
            content: bytes::Bytes::new(),
            timestamp_start: 0.0,
        },
        response: Some(FlowResponse {
            status_code: 200,
            headers: HashMap::new(),
            content: bytes::Bytes::from_static(b"original content"),
        }),
    };

    for m in &mutators {
        m.mutate_request(&mut flow).await;
    }
    assert_eq!(
        flow.request.headers.get("X-Proxify-Injected"),
        Some(&"level_1".to_string())
    );

    for m in &mutators {
        m.mutate_response(&mut flow).await;
    }
    assert_eq!(
        flow.response.as_ref().map(|r| r.content.as_ref()),
        Some(b"rewritten by mutator chain".as_slice())
    );
}
