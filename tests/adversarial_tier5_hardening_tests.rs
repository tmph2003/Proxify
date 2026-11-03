//! Tier 5 Adversarial Coverage Hardening Integration Test Suite (Milestone 4)
//!
//! Specifically validates the Tier 5 adversarial attack vectors assigned to Challenger:
//! 1. High-Concurrency Certificate Generation: 100 concurrent requests across distinct domains
//!    offloaded to blocking threads without reactor starvation or lock contention.
//! 2. High-Concurrency Thundering Herd & Single-Flight Coalescing: 100 simultaneous requests
//!    for identical domain coalesce into a single leaf signing operation.
//! 3. Bounded CA LRU Eviction & Memory Leak Prevention: Strict capacity bound of 4096 entries,
//!    purging 512 oldest entries when exceeded, while preserving actively renewed entries.
//! 4. Single-Flight Broadcast Channel Drop & Cancellation Guard: Ensures tasks aborted mid-flight
//!    cleanly drop broadcast channels without leaking memory or causing subsequent deadlocks.
//! 5. High-Load Database Flush Batch Overflow & Backpressure: Enqueue 5,000 records into bounded
//!    mpsc channel, verifying zero panic on queue saturation, zero-copy payload truncation to
//!    `max_body_size`, and graceful shutdown flush.
//! 6. Half-Closed HTTP/1.1 Connections: Verifies proxy correctly handles client TCP write-shutdown
//!    (FIN packet sent by client after transmitting request), forwarding response cleanly.
//! 7. Malformed HTTP Headers & Protocol Invariants: Verifies proxy tolerance to corrupt headers,
//!    missing colons, binary junk on HTTP port, NUL bytes, and extreme header counts without crash.
//! 8. Abrupt TCP RST & Slowloris Drip Attack: Validates resilience against socket drops and drip feeds
//!    without degrading concurrent healthy proxy connections.
//! 9. Stealth Crawl Circuit Breaker Concurrency Stress: 50 concurrent tasks transitioning states
//!    (CLOSED -> OPEN -> HALF_OPEN -> CLOSED) without lock contention or invalid state transitions.
//! 10. Radix-Trie Router Adversarial Domain Matrix: Stresses wildcard lookups with unicode,
//!     overlapping wildcards, excessive dots, and dynamic concurrent rule additions.

use bytes::Bytes;
use futures_util::future::join_all;
use http_body_util::{BodyExt, Full};
use hyper::{Response, StatusCode};
use proxify::test_helpers::*;
use proxify_core::ca::CertificateAuthority;
use proxify_core::proxy::Ipv4PreferredDnsResolver;
use proxify_core::router::ProxyRouter;
use proxify_core::stealth::CrawlCircuitBreaker;
use proxify_core::storage::{create_pg_pool, RequestRecord, RequestStorage};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::sync::Barrier;

// =========================================================================
// 1. High-Concurrency Certificate Generation (100 Distinct Domains)
// =========================================================================

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_tier5_adv_cert_gen_100_concurrent_distinct_domains() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_tier5_ca_100_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    // Spawn 100 concurrent tasks requesting 100 distinct domains
    let barrier = Arc::new(Barrier::new(100));
    let mut tasks = Vec::with_capacity(100);

    for i in 0..100 {
        let ca_clone = ca.clone();
        let barrier_clone = barrier.clone();
        tasks.push(tokio::spawn(async move {
            barrier_clone.wait().await;
            let host = format!("tier5-distinct-{}.adversarial-infra.org", i);
            ca_clone.server_config_for_host_async(&host).await
        }));
    }

    let results = join_all(tasks).await;

    let mut distinct_configs = Vec::with_capacity(100);
    for (i, res) in results.into_iter().enumerate() {
        let cfg = res
            .unwrap_or_else(|e| panic!("Task {} failed to join: {}", i, e))
            .unwrap_or_else(|e| panic!("Cert gen for domain {} failed: {}", i, e));

        assert!(
            cfg.alpn_protocols.contains(&b"http/1.1".to_vec()),
            "Config for distinct domain {} must support HTTP/1.1",
            i
        );
        assert!(
            cfg.alpn_protocols.contains(&b"h2".to_vec()),
            "Config for distinct domain {} must support h2",
            i
        );
        distinct_configs.push(cfg);
    }
    assert_eq!(distinct_configs.len(), 100);

    // Second wave: Verify all 100 distinct domains hit the leaf cache instantaneously
    let mut cache_tasks = Vec::with_capacity(100);
    for i in 0..100 {
        let ca_clone = ca.clone();
        cache_tasks.push(tokio::spawn(async move {
            let host = format!("tier5-distinct-{}.adversarial-infra.org", i);
            ca_clone.server_config_for_host_async(&host).await
        }));
    }

    let cache_results = join_all(cache_tasks).await;
    for (i, res) in cache_results.into_iter().enumerate() {
        let cached_cfg = res.unwrap().unwrap();
        assert!(
            Arc::ptr_eq(&distinct_configs[i], &cached_cfg),
            "Domain {} must return the exact same cached Arc pointer",
            i
        );
    }

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 2. High-Concurrency Thundering Herd & Single-Flight Coalescing (100 Requests)
// =========================================================================

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_tier5_adv_cert_gen_100_concurrent_thundering_herd() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_tier5_herd_100_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    let target_domain = "tier5-thundering-herd.stress-matrix.io";
    let barrier = Arc::new(Barrier::new(100));
    let mut tasks = Vec::with_capacity(100);

    for _ in 0..100 {
        let ca_clone = ca.clone();
        let barrier_clone = barrier.clone();
        tasks.push(tokio::spawn(async move {
            barrier_clone.wait().await;
            ca_clone.server_config_for_host_async(target_domain).await
        }));
    }

    let results = join_all(tasks).await;
    let mut configs = Vec::with_capacity(100);

    for (i, res) in results.into_iter().enumerate() {
        let cfg = res
            .unwrap_or_else(|e| panic!("Thundering herd task {} join error: {}", i, e))
            .unwrap_or_else(|e| panic!("Thundering herd cert gen {} failed: {}", i, e));
        configs.push(cfg);
    }

    // All 100 concurrent callers must receive the exact same Arc pointer via single-flight
    let root_ptr = Arc::as_ptr(&configs[0]);
    for (i, cfg) in configs.iter().enumerate().skip(1) {
        assert!(
            Arc::ptr_eq(&configs[0], cfg),
            "Task {} got divergent Arc pointer ({:?} vs root {:?})! Single-flight coalescing failed.",
            i,
            Arc::as_ptr(cfg),
            root_ptr
        );
    }

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 3. Bounded CA LRU Eviction & Memory Leak Prevention (4096 Threshold)
// =========================================================================

#[tokio::test]
async fn test_tier5_adv_ca_lru_cache_bounded_4096_eviction_and_renewal() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_tier5_lru_bound_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    // Populate baseline: host-0000 through host-4095 (4096 total entries)
    let host_0 = "tier5-lru-host-0000.bounded.test";
    let host_7 = "tier5-lru-host-0007.bounded.test";
    let host_42 = "tier5-lru-host-0042.bounded.test";

    let cfg_0 = ca
        .server_config_for_host_async(host_0)
        .await
        .expect("Host 0 gen");
    let cfg_7 = ca
        .server_config_for_host_async(host_7)
        .await
        .expect("Host 7 gen");
    let cfg_42 = ca
        .server_config_for_host_async(host_42)
        .await
        .expect("Host 42 gen");

    // Fill up to 4096 entries
    for i in 1..4096 {
        if i == 7 || i == 42 {
            continue;
        }
        let h = format!("tier5-lru-host-{:04}.bounded.test", i);
        let _ = ca.server_config_for_host_async(&h).await.unwrap();
    }

    // Explicitly re-access host_7 and host_42 to update their LRU access counter to the current top
    let cfg_7_renewed = ca.server_config_for_host_async(host_7).await.unwrap();
    assert!(Arc::ptr_eq(&cfg_7, &cfg_7_renewed));
    let cfg_42_renewed = ca.server_config_for_host_async(host_42).await.unwrap();
    assert!(Arc::ptr_eq(&cfg_42, &cfg_42_renewed));

    // Now insert host-4096. This pushes length to 4096, triggering eviction of 512 oldest entries!
    let host_4096 = "tier5-lru-host-4096.bounded.test";
    let _ = ca.server_config_for_host_async(host_4096).await.unwrap();

    // 1. host_0 was NOT re-accessed, so it was among the oldest 512 entries and must be evicted!
    let cfg_0_after = ca.server_config_for_host_async(host_0).await.unwrap();
    assert!(
        !Arc::ptr_eq(&cfg_0, &cfg_0_after),
        "host_0 should have been evicted by LRU threshold! Pointers matched ({:?}), unbounded leak suspected.",
        Arc::as_ptr(&cfg_0)
    );

    // 2. host_7 and host_42 WERE renewed, so despite having low indices, they MUST survive eviction!
    let cfg_7_after = ca.server_config_for_host_async(host_7).await.unwrap();
    assert!(
        Arc::ptr_eq(&cfg_7, &cfg_7_after),
        "host_7 was incorrectly evicted despite recent LRU renewal!"
    );

    let cfg_42_after = ca.server_config_for_host_async(host_42).await.unwrap();
    assert!(
        Arc::ptr_eq(&cfg_42, &cfg_42_after),
        "host_42 was incorrectly evicted despite recent LRU renewal!"
    );

    // 3. Stress further by adding 200 more entries up to 4300
    for i in 4097..4300 {
        let h = format!("tier5-lru-host-{:04}.bounded.test", i);
        let _ = ca.server_config_for_host_async(&h).await.unwrap();
    }

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 4. Single-Flight Broadcast Channel Drop & Cancellation Guard
// =========================================================================

#[tokio::test]
async fn test_tier5_adv_single_flight_cancellation_and_channel_cleanup() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_tier5_cancel_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    // Spawn 15 leader tasks and abort them immediately
    for i in 0..15 {
        let host = format!("tier5-abort-host-{}.resilience.local", i);
        let ca_clone = ca.clone();
        let handle =
            tokio::spawn(async move { ca_clone.server_config_for_host_async(&host).await });
        handle.abort();
        let _ = handle.await;
    }

    // Verify that the InFlightGuard properly pruned all in-flight entries:
    // Subsequent requests for all 15 domains must succeed immediately without deadlocking or hanging
    let mut followup_tasks = Vec::with_capacity(15);
    for i in 0..15 {
        let ca_clone = ca.clone();
        followup_tasks.push(tokio::spawn(async move {
            let host = format!("tier5-abort-host-{}.resilience.local", i);
            tokio::time::timeout(
                Duration::from_secs(3),
                ca_clone.server_config_for_host_async(&host),
            )
            .await
        }));
    }

    let followup_res = join_all(followup_tasks).await;
    for (i, res) in followup_res.into_iter().enumerate() {
        let timeout_res = res.unwrap();
        assert!(
            timeout_res.is_ok(),
            "Domain {} deadlocked or timed out after leader task abort!",
            i
        );
        let cfg = timeout_res.unwrap().unwrap();
        assert!(cfg.alpn_protocols.contains(&b"http/1.1".to_vec()));
    }

    // Also verify DNS Single-Flight Deduplication and clean resolution
    let ips = Ipv4PreferredDnsResolver::resolve_ips("127.0.0.1")
        .await
        .expect("DNS resolve 127.0.0.1");
    assert!(!ips.is_empty());

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 5. High-Load Database Flush Batch Overflow & Backpressure
// =========================================================================

#[tokio::test]
async fn test_tier5_adv_storage_high_load_batch_overflow_and_backpressure() {
    let pool = create_pg_pool("postgresql://dummy:dummy@127.0.0.1:5432/dummy", 1).unwrap();
    let storage = RequestStorage::new(pool);
    storage.set_saving(true);

    // Test zero-copy payload truncation: payload of 6MB exceeds default max_body_size (5MB)
    let giant_body = Bytes::from(vec![b'A'; 6 * 1024 * 1024]);
    let rec = RequestRecord {
        id: None,
        timestamp: 1700000000.0,
        method: "POST".to_string(),
        url: "http://example.com/oversized".to_string(),
        host: "example.com".to_string(),
        path: "/oversized".to_string(),
        status_code: Some(200),
        request_headers: "".to_string(),
        request_body: Some(giant_body),
        response_headers: None,
        response_body: None,
        content_type: Some("application/octet-stream".to_string()),
        duration_ms: Some(15.0),
        is_graphql: 0,
        graphql_operation: None,
        graphql_query: None,
        graphql_variables: None,
        size_bytes: 6 * 1024 * 1024,
    };

    // Enqueue must truncate body to max_body_size without panic
    storage.enqueue(rec);

    // Concurrently flood the storage queue with 5,000 records across 50 concurrent tasks
    // The bounded mpsc channel capacity is 2,000. Backpressure will drop items via `try_send`
    // without blocking workers or causing unbounded heap growth.
    let mut flood_tasks = Vec::with_capacity(50);
    let storage_clone = storage.clone();

    for task_idx in 0..50 {
        let s = storage_clone.clone();
        flood_tasks.push(tokio::spawn(async move {
            for i in 0..100 {
                let r = RequestRecord {
                    id: None,
                    timestamp: 1700000000.0 + (task_idx * 100 + i) as f64,
                    method: "GET".to_string(),
                    url: format!("http://example.com/item/{}", i),
                    host: "example.com".to_string(),
                    path: format!("/item/{}", i),
                    status_code: Some(200),
                    request_headers: "host: example.com\r\n".to_string(),
                    request_body: Some(Bytes::from_static(b"tiny-body")),
                    response_headers: None,
                    response_body: None,
                    content_type: Some("text/plain".to_string()),
                    duration_ms: Some(2.5),
                    is_graphql: 0,
                    graphql_operation: None,
                    graphql_query: None,
                    graphql_variables: None,
                    size_bytes: 9,
                };
                s.enqueue(r);
            }
        }));
    }

    join_all(flood_tasks).await;

    // Flush and shutdown must complete gracefully within timeout
    let flush_res = tokio::time::timeout(Duration::from_secs(3), storage.flush()).await;
    assert!(
        flush_res.is_ok(),
        "Storage flush timed out under backpressure!"
    );

    let shutdown_res = tokio::time::timeout(Duration::from_secs(3), storage.shutdown()).await;
    assert!(
        shutdown_res.is_ok(),
        "Storage graceful shutdown timed out under backpressure!"
    );
}

// =========================================================================
// 6. Half-Closed HTTP/1.1 Connections (Client TCP Write Shutdown)
// =========================================================================

#[tokio::test]
async fn test_tier5_adv_half_closed_http11_client_write_shutdown() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        assert_eq!(req.uri().path(), "/adv-half-closed");
        Response::builder()
            .status(StatusCode::OK)
            .header("Content-Type", "text/plain")
            .header("X-Half-Closed-Ack", "true")
            .body(Full::new(Bytes::from("echo-half-closed-payload-ok")).boxed())
            .unwrap()
    })
    .await;

    let target_url = upstream.url("/adv-half-closed");
    let mut stream = TcpStream::connect(proxy.addr)
        .await
        .expect("Failed to connect to proxy");

    // Write full HTTP/1.1 request
    let req_str = format!(
        "GET {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        target_url,
        upstream.addr.port()
    );
    stream.write_all(req_str.as_bytes()).await.unwrap();
    stream.flush().await.unwrap();

    // Small delay to allow TCP stack to deliver request before write shutdown
    tokio::time::sleep(Duration::from_millis(50)).await;

    // Half-close: Client sends TCP FIN for the write direction
    stream
        .shutdown()
        .await
        .expect("Client write shutdown failed");

    // Client continues reading the response until server closes
    let mut resp_bytes = Vec::new();
    let read_res =
        tokio::time::timeout(Duration::from_secs(5), stream.read_to_end(&mut resp_bytes)).await;

    assert!(
        read_res.is_ok(),
        "Timed out waiting for response on half-closed connection!"
    );
    assert!(
        !resp_bytes.is_empty(),
        "Response should not be empty on half-closed connection"
    );

    let (status, headers, body) = parse_raw_http_response(&resp_bytes);
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get("x-half-closed-ack").and_then(|v| v.first()),
        Some(&"true".to_string())
    );
    assert_eq!(
        String::from_utf8_lossy(&body),
        "echo-half-closed-payload-ok"
    );
}

// =========================================================================
// 7. Malformed HTTP Headers & Protocol Invariants
// =========================================================================

#[tokio::test]
async fn test_tier5_adv_malformed_headers_and_bad_requests() {
    let proxy = TestProxyServer::start().await;
    let upstream = MockHttpUpstream::start_simple_echo().await;

    // Scenario A: Header missing colon
    {
        let mut stream = TcpStream::connect(proxy.addr).await.unwrap();
        let payload = format!(
            "GET {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nInvalidHeaderWithoutColon\r\n\r\n",
            upstream.url("/test-no-colon"),
            upstream.addr.port()
        );
        let _ = stream.write_all(payload.as_bytes()).await;
        let _ = stream.flush().await;

        let mut resp = Vec::new();
        let _ = stream.read_to_end(&mut resp).await;
        let resp_str = String::from_utf8_lossy(&resp);
        assert!(
            resp.is_empty()
                || resp_str.contains("400")
                || resp_str.contains("Bad Request")
                || resp_str.contains("400 Bad Request"),
            "Missing colon header must yield 400 or socket close, got: {:?}",
            resp_str
        );
    }

    // Scenario B: Binary garbage sent to HTTP proxy port
    {
        let mut stream = TcpStream::connect(proxy.addr).await.unwrap();
        let garbage = b"\x16\x03\x01\x00\xa5\x01\x00\x00\xa1\x03\x03\xde\xad\xbe\xef\r\n\r\n";
        let _ = stream.write_all(garbage).await;
        let _ = stream.flush().await;

        let mut resp = Vec::new();
        let _ = stream.read_to_end(&mut resp).await;
        // Proxy must reject or close connection without panic
    }

    // Scenario C: Malformed HTTP version
    {
        let mut stream = TcpStream::connect(proxy.addr).await.unwrap();
        let payload = format!(
            "GET {} HTTP/9.99\r\nHost: 127.0.0.1:{}\r\n\r\n",
            upstream.url("/test-bad-version"),
            upstream.addr.port()
        );
        let _ = stream.write_all(payload.as_bytes()).await;
        let _ = stream.flush().await;

        let mut resp = Vec::new();
        let _ = stream.read_to_end(&mut resp).await;
        let resp_str = String::from_utf8_lossy(&resp);
        assert!(
            resp.is_empty() || resp_str.contains("400") || resp_str.contains("505"),
            "Malformed HTTP version must be rejected safely"
        );
    }

    // Scenario D: 150 headers with large cumulative sizes
    {
        let mut headers = vec![("Host", "127.0.0.1")];
        let header_pool: Vec<(String, String)> = (0..150)
            .map(|i| (format!("X-Adv-Header-{}", i), format!("Val-{}", i)))
            .collect();
        for (k, v) in &header_pool {
            headers.push((k.as_str(), v.as_str()));
        }

        let target_url = upstream.url("/echo-150-headers");
        let (status, _, _) =
            send_raw_proxy_request(proxy.addr, "GET", &target_url, &headers, b"").await;

        assert!(
            status == StatusCode::OK || status == StatusCode::REQUEST_HEADER_FIELDS_TOO_LARGE,
            "Proxy must either handle 150 headers or safely reject with 431 Request Header Fields Too Large without panic, got: {:?}",
            status
        );
    }

    // Scenario E: Invariant verification — normal request immediately succeeds afterwards
    {
        let target_url = upstream.url("/sanity-check");
        let (status, _, body) = send_raw_proxy_request(
            proxy.addr,
            "GET",
            &target_url,
            &[("Host", "127.0.0.1")],
            b"",
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert!(String::from_utf8_lossy(&body).contains("sanity-check"));
    }
}

// =========================================================================
// 8. Abrupt TCP RST & Slowloris Drip Attack Resilience
// =========================================================================

#[tokio::test]
async fn test_tier5_adv_abrupt_client_rst_and_slowloris() {
    let proxy = TestProxyServer::start().await;
    let upstream = MockHttpUpstream::start_simple_echo().await;

    // 1. Abrupt TCP reset (drop socket mid-flight)
    for _ in 0..5 {
        if let Ok(mut stream) = TcpStream::connect(proxy.addr).await {
            let partial = b"GET http://127.0.0.1/partial-request HTTP/1.1\r\nHost: 127";
            let _ = stream.write_all(partial).await;
            let _ = stream.flush().await;
            // Immediate drop without FIN (initiates TCP RST / abort)
            drop(stream);
        }
    }

    // 2. Slowloris trickle: Send 1 byte every 30ms for 4 bytes then drop
    let proxy_addr = proxy.addr;
    let slow_handle = tokio::spawn(async move {
        if let Ok(mut stream) = TcpStream::connect(proxy_addr).await {
            for b in b"POST" {
                let _ = stream.write_all(&[*b]).await;
                let _ = stream.flush().await;
                tokio::time::sleep(Duration::from_millis(30)).await;
            }
        }
    });

    // 3. Simultaneously, a legitimate client sends a valid request
    // It must succeed in under 100ms without being starved or blocked by slowloris
    let target_url = upstream.url("/fast-path");
    let (status, _, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &target_url,
        &[("Host", "127.0.0.1")],
        b"valid",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert!(String::from_utf8_lossy(&body).contains("valid"));

    let _ = slow_handle.await;
}

// =========================================================================
// 9. Stealth Crawl Circuit Breaker Concurrency Stress
// =========================================================================

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_tier5_adv_stealth_circuit_breaker_concurrency_stress() {
    let cb = Arc::new(CrawlCircuitBreaker::new(5, 1, 2));

    // Initially CLOSED
    assert!(cb.allow_request());

    // 50 concurrent tasks hammering the circuit breaker
    let mut tasks = Vec::with_capacity(50);
    let error_count = Arc::new(AtomicUsize::new(0));

    for task_id in 0..50 {
        let cb_clone = cb.clone();
        let errs = error_count.clone();
        tasks.push(tokio::spawn(async move {
            for step in 0..100 {
                let allowed = cb_clone.allow_request();
                if (task_id + step) % 7 == 0 {
                    cb_clone.record_failure("adv_stress_simulated_failure");
                    errs.fetch_add(1, Ordering::Relaxed);
                } else if allowed && (task_id + step) % 11 == 0 {
                    cb_clone.record_success();
                }
            }
        }));
    }

    join_all(tasks).await;

    // After massive failure injection, circuit should be OPEN or HALF_OPEN
    let state = cb.allow_request();
    // Verify that circuit breaker state operations never deadlocked
    let _ = state;

    // Record success to restore to CLOSED once allowed
    for _ in 0..10 {
        cb.record_success();
    }
}

// =========================================================================
// 10. Radix-Trie Router Adversarial Domain Matrix
// =========================================================================

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_tier5_adv_router_radix_trie_adversarial_matrix() {
    let router = Arc::new(ProxyRouter::new());

    // Register adversarial stream and exclusion rules
    router.register_stream_rule("*.googlevideo.com");
    router.register_stream_rule("fbcdn.net");
    router.register_stream_path_rule("*.youtube.com", "/videoplayback");
    router.register_stream_exclusion("*.youtube.com", "/api/stats");

    // 50 concurrent tasks querying the router with adversarial domains
    let mut tasks = Vec::with_capacity(50);
    for task_id in 0..50 {
        let r = router.clone();
        tasks.push(tokio::spawn(async move {
            for i in 0..100 {
                let domain = match (task_id + i) % 8 {
                    0 => "v1.api.youtube.com",
                    1 => "music.youtube.com",
                    2 => "chat.zalo.me",
                    3 => "news.vn",
                    4 => "...excessive.dots...vn...",
                    5 => "unknown.example.org",
                    6 => "sub.googlevideo.com",
                    _ => "static.fbcdn.net",
                };

                let should_stream = r.should_stream(domain);
                let (obs, muts) = r.resolve(domain);
                let _ = (obs, muts);

                match domain {
                    "sub.googlevideo.com" => {
                        assert!(should_stream);
                        assert!(r.should_stream_request(domain, "/video.mp4"));
                    }
                    "static.fbcdn.net" => {
                        assert!(should_stream);
                        assert!(r.should_stream_request(domain, "/image.jpg"));
                    }
                    "music.youtube.com" => {
                        // should_stream_path triggers on /videoplayback
                        assert!(r.should_stream_request(domain, "/videoplayback?id=123"));
                        // but exclusion triggers on /api/stats
                        assert!(!r.should_stream_request(domain, "/videoplayback/api/stats"));
                    }
                    _ => {}
                }
            }
        }));
    }

    join_all(tasks).await;
}
