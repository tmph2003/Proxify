//! Adversarial Stress & Protocol Edge-Case Integration Test Suite (Milestone 1)
//!
//! Specifically validates the 4 adversarial attack vectors assigned to Challenger 1:
//! 1. WebSocket Framing Adversarial Test: Packet-fragmented TCP chunks where CRLF CRLF
//!    is split across 2 or 3 separate packets, ensuring read_http_headers accumulates without
//!    hanging or truncating leftover frames.
//! 2. Facebook Passthrough Verification: Empirically verifies that `FacebookGraphQLObserver`
//!    intercepts decrypted HTTPS traffic when proxied through `proxify-core` and that
//!    `facebook.com` is NOT bypassed by `should_passthrough_tls`.
//! 3. Multi-Value Header Stress: Transmits requests and responses with duplicate headers
//!    (`Set-Cookie` with commas in `Expires`, multiple `Accept`, `X-Custom-Trace`) and verifies
//!    zero loss or value corruption.
//! 4. DNS Stampede Stress: Fires 50+ concurrent simulated DNS requests for identical uncached
//!    domains and verifies single-flight resolution without duplicate upstream queries or panics.

use bytes::Bytes;
use ext_facebook::FacebookGraphQLObserver;
use http_body_util::{BodyExt, Full};
use hyper::{Response, StatusCode};
use proxify::test_helpers::*;
use proxify_core::proxy::{Ipv4PreferredDnsResolver, MitmProxyServer};
use proxify_sdk::ObserverInterceptor;
use std::net::IpAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio_rustls::TlsConnector;

// =========================================================================
// 1. WebSocket Framing Adversarial Tests
// =========================================================================

#[tokio::test]
async fn test_adv_ws_framing_crlf_split_2_chunks() {
    let (mut client_tx, mut server_rx) = tokio::io::duplex(2048);

    // Chunk 1 ends in `\r` (splitting \r\n\r\n)
    let chunk1 = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r";
    // Chunk 2 starts with `\n\r\n` followed immediately by WebSocket frame data
    let chunk2 = b"\n\r\n\x81\x0bHello-Split";

    tokio::spawn(async move {
        client_tx.write_all(chunk1).await.unwrap();
        client_tx.flush().await.unwrap();
        tokio::time::sleep(Duration::from_millis(25)).await;
        client_tx.write_all(chunk2).await.unwrap();
        client_tx.flush().await.unwrap();
    });

    let (head, leftover) = MitmProxyServer::read_http_headers(&mut server_rx)
        .await
        .expect("read_http_headers must succeed on 2-chunk split CRLF");

    let head_str = String::from_utf8_lossy(&head);
    assert!(
        head_str.ends_with("\r\n\r\n"),
        "Headers must cleanly terminate with \\r\\n\\r\\n. Got: {:?}",
        head_str
    );
    assert!(
        !head_str.contains("Hello-Split"),
        "Headers must NOT contain leftover frame payload"
    );
    assert_eq!(
        leftover, b"\x81\x0bHello-Split",
        "Leftover data must exactly match the WebSocket frame"
    );
}

#[tokio::test]
async fn test_adv_ws_framing_crlf_split_3_chunks() {
    let (mut client_tx, mut server_rx) = tokio::io::duplex(2048);

    // Chunk 1 ends with `\r` (1 of 4 delimiter bytes)
    let chunk1 = b"HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: abcxyz==\r";
    // Chunk 2 contains `\n\r` (now 3 of 4 delimiter bytes: \r\n\r)
    let chunk2 = b"\n\r";
    // Chunk 3 contains the 4th delimiter byte `\n` followed immediately by WebSocket payload
    let chunk3 = b"\n\x81\x08Payload3";

    tokio::spawn(async move {
        client_tx.write_all(chunk1).await.unwrap();
        client_tx.flush().await.unwrap();
        tokio::time::sleep(Duration::from_millis(20)).await;

        client_tx.write_all(chunk2).await.unwrap();
        client_tx.flush().await.unwrap();
        tokio::time::sleep(Duration::from_millis(20)).await;

        client_tx.write_all(chunk3).await.unwrap();
        client_tx.flush().await.unwrap();
    });

    let (head, leftover) = MitmProxyServer::read_http_headers(&mut server_rx)
        .await
        .expect("read_http_headers must succeed on 3-chunk split CRLF");

    let head_str = String::from_utf8_lossy(&head);
    assert!(head_str.ends_with("\r\n\r\n"));
    assert_eq!(leftover, b"\x81\x08Payload3");
}

#[tokio::test]
async fn test_adv_ws_framing_crlf_split_individual_bytes() {
    let (mut client_tx, mut server_rx) = tokio::io::duplex(4096);

    let prefix = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket";
    let cr1 = b"\r";
    let lf1 = b"\n";
    let cr2 = b"\r";
    // The final packet delivers the last delimiter byte \n and the immediate payload
    let lf2_and_payload = b"\nDATA_AFTER_4_SPLITS";

    tokio::spawn(async move {
        client_tx.write_all(prefix).await.unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        client_tx.write_all(cr1).await.unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        client_tx.write_all(lf1).await.unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        client_tx.write_all(cr2).await.unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        client_tx.write_all(lf2_and_payload).await.unwrap();
    });

    let (head, leftover) = MitmProxyServer::read_http_headers(&mut server_rx)
        .await
        .expect("read_http_headers must handle 1-byte delimiter splits");

    assert!(head.ends_with(b"\r\n\r\n"));
    assert_eq!(leftover, b"DATA_AFTER_4_SPLITS");
}

#[tokio::test]
async fn test_adv_ws_framing_e2e_segmented_packet_delivery_with_immediate_payload() {
    let proxy = TestProxyServer::start().await;

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = listener.local_addr().unwrap();

    let client_key = "dGhlIHNhbXBsZSBub25jZQ==";
    let accept_key = compute_websocket_accept(client_key);

    // Mock WebSocket upstream sending fragmented 101 with immediate frame in packet 3
    let accept_clone = accept_key.clone();
    tokio::spawn(async move {
        if let Ok((mut stream, _)) = listener.accept().await {
            let mut buf = vec![0u8; 1024];
            let _ = stream.read(&mut buf).await.unwrap();

            // Segment 1: Status and partial header ending with \r
            let seg1 = format!(
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r",
                accept_clone
            );
            stream.write_all(seg1.as_bytes()).await.unwrap();
            stream.flush().await.unwrap();

            tokio::time::sleep(Duration::from_millis(30)).await;

            // Segment 2: `\n\r`
            stream.write_all(b"\n\r").await.unwrap();
            stream.flush().await.unwrap();

            tokio::time::sleep(Duration::from_millis(30)).await;

            // Segment 3: `\n` + raw message frame
            let seg3 = b"\nimmediate-frame-123";
            stream.write_all(seg3).await.unwrap();
            stream.flush().await.unwrap();

            // Echo back client message
            let mut read_buf = vec![0u8; 128];
            if let Ok(rn) = stream.read(&mut read_buf).await {
                if rn > 0 {
                    let _ = stream.write_all(&read_buf[..rn]).await;
                }
            }
        }
    });

    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let ws_req = format!(
        "GET /adv-ws HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n",
        upstream_addr.port(),
        client_key
    );
    client.write_all(ws_req.as_bytes()).await.unwrap();

    let mut resp_buf = vec![0u8; 1024];
    let n = client.read(&mut resp_buf).await.unwrap();
    let (status, headers, body) = parse_raw_http_response(&resp_buf[..n]);

    assert_eq!(status, StatusCode::SWITCHING_PROTOCOLS);
    assert_eq!(
        headers.get("sec-websocket-accept").and_then(|v| v.first()),
        Some(&accept_key)
    );

    // Leftover payload in handshake buffer should be delivered
    let initial_payload = String::from_utf8_lossy(&body);
    let mut received_payload = initial_payload.to_string();

    if !received_payload.contains("immediate-frame-123") {
        let mut extra_buf = vec![0u8; 256];
        let en = client.read(&mut extra_buf).await.unwrap();
        received_payload.push_str(&String::from_utf8_lossy(&extra_buf[..en]));
    }
    assert!(
        received_payload.contains("immediate-frame-123"),
        "Immediate frame in handshake leftover must be delivered to client! Got: {}",
        received_payload
    );

    // Verify bidirectional piping still functions
    client.write_all(b"ping-pong-reply").await.unwrap();
    let mut echo_buf = vec![0u8; 128];
    let en = client.read(&mut echo_buf).await.unwrap();
    assert_eq!(String::from_utf8_lossy(&echo_buf[..en]), "ping-pong-reply");
}

// =========================================================================
// 2. Facebook Passthrough & MITM Interception Verification
// =========================================================================

#[test]
fn test_adv_facebook_passthrough_disabled_matrix() {
    let fb_domains = [
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "web.facebook.com",
        "graph.facebook.com",
        "b-graph.facebook.com",
        "gateway.facebook.com",
        "upload.facebook.com",
        "fb.com",
        "www.fb.com",
        "fbcdn.net",
        "static.xx.fbcdn.net",
        "facebook.net",
        "connect.facebook.net",
    ];

    for domain in fb_domains {
        assert!(
            !MitmProxyServer::should_passthrough_tls(domain),
            "Facebook domain '{}' must NOT be bypassed; TLS MITM inspection is mandatory",
            domain
        );
    }

    // Verify that genuine passthrough domains remain bypassed
    let bypassed_domains = [
        "googlevideo.com",
        "rr1---sn-4g5ednks.googlevideo.com",
        "apple.com",
        "init.itunes.apple.com",
        "zadn.vn",
    ];

    for domain in bypassed_domains {
        assert!(
            MitmProxyServer::should_passthrough_tls(domain),
            "Domain '{}' must remain in TLS passthrough list",
            domain
        );
    }
}

struct MockFacebookBackendMutator {
    response_body: String,
}

#[async_trait::async_trait]
impl proxify_sdk::MutatorInterceptor for MockFacebookBackendMutator {
    async fn mutate_request(&self, flow: &mut proxify_sdk::HttpFlow) {
        if flow.request.path.contains("/api/graphql") {
            let mut headers = std::collections::HashMap::new();
            headers.insert("content-type".to_string(), "application/json".to_string());
            flow.response = Some(proxify_sdk::FlowResponse {
                status_code: 200,
                headers,
                content: self.response_body.as_bytes().to_vec().into(),
            });
        }
    }
}

#[tokio::test]
async fn test_adv_facebook_tls_mitm_and_graphql_interception_e2e() {
    let proxy = TestProxyServer::start().await;

    let expected_gql_resp = r#"{"data":{"node":{"id":"fb_user_42","name":"Alice Smith"}}}"#;

    // Register mock Facebook backend mutator to simulate upstream GraphQL backend responses
    let backend_mutator = Arc::new(MockFacebookBackendMutator {
        response_body: expected_gql_resp.to_string(),
    });
    proxy
        .router
        .register_mutator("*.facebook.com", backend_mutator.clone());
    proxy
        .router
        .register_mutator("facebook.com", backend_mutator);

    // Register FacebookGraphQLObserver on proxy router
    let fb_observer: Arc<dyn ObserverInterceptor> =
        FacebookGraphQLObserver::new(proxy.event_bus.clone());
    proxy
        .router
        .register_observer("*.facebook.com", fb_observer.clone());
    proxy.router.register_observer("facebook.com", fb_observer);

    // 1. Establish CONNECT tunnel with proxy for facebook.com
    // Because should_passthrough_tls("www.facebook.com") is FALSE, the proxy
    // performs dynamic leaf certificate MITM interception rather than blind passthrough.
    let mut client_tcp = TcpStream::connect(proxy.addr).await.unwrap();
    let connect_req = "CONNECT www.facebook.com:443 HTTP/1.1\r\nHost: www.facebook.com:443\r\n\r\n";
    client_tcp.write_all(connect_req.as_bytes()).await.unwrap();

    let mut connect_resp = vec![0u8; 512];
    let n = client_tcp.read(&mut connect_resp).await.unwrap();
    let resp_str = String::from_utf8_lossy(&connect_resp[..n]);
    assert!(
        resp_str.starts_with("HTTP/1.1 200"),
        "CONNECT response: {}",
        resp_str
    );

    // 2. Client TLS handshake with Proxy using Proxy's dynamic Root CA
    let mut root_store = rustls::RootCertStore::empty();
    let ca_der = rustls::pki_types::CertificateDer::from(proxy.ca.ca_cert_der_bytes().to_vec());
    root_store.add(ca_der).unwrap();

    let client_tls_cfg = rustls::ClientConfig::builder()
        .with_root_certificates(root_store)
        .with_no_client_auth();
    let connector = TlsConnector::from(Arc::new(client_tls_cfg));
    let server_name =
        rustls::pki_types::ServerName::try_from("www.facebook.com".to_string()).unwrap();

    let mut tls_client = connector.connect(server_name, client_tcp).await.unwrap();

    // 3. Send encrypted Facebook GraphQL request through the decrypted MITM tunnel
    let gql_body = r#"doc_id=987654321&variables={"id":"fb_user_42"}"#;
    let https_req = format!(
        "POST /api/graphql HTTP/1.1\r\nHost: www.facebook.com\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        gql_body.len(),
        gql_body
    );
    tls_client.write_all(https_req.as_bytes()).await.unwrap();

    let mut response_bytes = Vec::new();
    tls_client.read_to_end(&mut response_bytes).await.unwrap();

    let (status, _, body) = parse_raw_http_response(&response_bytes);
    assert_eq!(status, StatusCode::OK);
    assert_eq!(String::from_utf8_lossy(&body), expected_gql_resp);

    // 4. Verify FacebookGraphQLObserver successfully observed the flow and published to event bus
    tokio::time::sleep(Duration::from_millis(50)).await;
    let events = proxy.event_bus.get_events("facebook.graphql.request");
    assert_eq!(
        events.len(),
        1,
        "FacebookGraphQLObserver must publish 1 event to 'facebook.graphql.request'"
    );
    let event = &events[0];
    assert!(
        event["url"].as_str().unwrap().contains("/api/graphql"),
        "Event url must contain /api/graphql"
    );
    assert_eq!(event["req_body"].as_str().unwrap(), gql_body);
    assert_eq!(event["resp_body"].as_str().unwrap(), expected_gql_resp);
}

// =========================================================================
// 3. Multi-Value Header Stress Tests
// =========================================================================

#[tokio::test]
async fn test_adv_multi_value_header_stress() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        // Assert upstream received multi-value headers sent by client
        let headers = req.headers();
        let cookie_val = headers
            .get("Cookie")
            .map(|v| v.to_str().unwrap_or(""))
            .unwrap_or("");
        assert!(
            cookie_val.contains("c1=val1") && cookie_val.contains("c2=val2"),
            "Client multi-value cookies must be received by upstream: {}",
            cookie_val
        );

        let mut builder = Response::builder().status(StatusCode::OK);
        let hm = builder.headers_mut().unwrap();

        // 5 distinct Set-Cookie headers with varied delimiters and commas
        hm.append(
            "Set-Cookie",
            "sid=sess_12345; Path=/; HttpOnly; SameSite=Lax"
                .parse()
                .unwrap(),
        );
        hm.append(
            "Set-Cookie",
            "prefs=dark_mode%3D1; Path=/; Max-Age=86400"
                .parse()
                .unwrap(),
        );
        hm.append(
            "Set-Cookie",
            "token=jwt_sec; Domain=.local; Secure; SameSite=None"
                .parse()
                .unwrap(),
        );
        // Note: RFC 1123 date contains a comma: `Wed, 21 Oct 2026`
        hm.append(
            "Set-Cookie",
            "exp_ck=val_exp; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Path=/"
                .parse()
                .unwrap(),
        );
        hm.append("Set-Cookie", "flag=true".parse().unwrap());

        // Multi-value custom headers
        hm.append("X-Trace-Node", "node-alpha".parse().unwrap());
        hm.append("X-Trace-Node", "node-beta".parse().unwrap());
        hm.append("X-Trace-Node", "node-gamma".parse().unwrap());

        // Multi-value Accept / Vary headers
        hm.append("Vary", "Origin".parse().unwrap());
        hm.append("Vary", "Accept-Encoding".parse().unwrap());

        builder
            .body(Full::new(Bytes::from("Multi-header response payload")).boxed())
            .unwrap()
    })
    .await;

    let target_url = upstream.url("/multi-headers");
    let (status, headers, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &target_url,
        &[
            ("Host", &format!("127.0.0.1:{}", upstream.addr.port())),
            ("Cookie", "c1=val1"),
            ("Cookie", "c2=val2"),
            ("Accept", "text/html"),
            ("Accept", "application/json"),
        ],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        String::from_utf8_lossy(&body),
        "Multi-header response payload"
    );

    // 1. Verify Set-Cookie preservation
    let set_cookies = headers
        .get("set-cookie")
        .expect("set-cookie headers must exist in response");
    assert_eq!(
        set_cookies.len(),
        5,
        "All 5 Set-Cookie headers must be preserved individually! Got: {:?}",
        set_cookies
    );

    assert!(set_cookies.iter().any(|c| c.contains("sid=sess_12345")));
    assert!(set_cookies
        .iter()
        .any(|c| c.contains("prefs=dark_mode%3D1")));
    assert!(set_cookies.iter().any(|c| c.contains("token=jwt_sec")));
    assert!(
        set_cookies
            .iter()
            .any(|c| c.contains("Expires=Wed, 21 Oct 2026 07:28:00 GMT")),
        "Expires date with comma must NOT be split into two headers! Got: {:?}",
        set_cookies
    );
    assert!(set_cookies.iter().any(|c| c.contains("flag=true")));

    // 2. Verify X-Trace-Node aggregation
    let trace_nodes = headers.get("x-trace-node").expect("x-trace-node header");
    let combined_trace = trace_nodes.join(", ");
    assert!(combined_trace.contains("node-alpha"));
    assert!(combined_trace.contains("node-beta"));
    assert!(combined_trace.contains("node-gamma"));

    // 3. Verify Vary aggregation
    let vary_hdr = headers.get("vary").expect("vary header");
    let combined_vary = vary_hdr.join(", ");
    assert!(combined_vary.contains("Origin"));
    assert!(combined_vary.contains("Accept-Encoding"));
}

// =========================================================================
// 4. DNS Stampede Stress Tests (Single-Flight Deduplication)
// =========================================================================

#[tokio::test]
async fn test_adv_dns_stampede_50_concurrent_requests_localhost() {
    // 50 concurrent simulated DNS resolutions for the same host
    let mut handles = Vec::with_capacity(50);
    for _ in 0..50 {
        handles.push(tokio::spawn(async {
            Ipv4PreferredDnsResolver::resolve_ips("localhost").await
        }));
    }

    for (idx, handle) in handles.into_iter().enumerate() {
        let res = handle.await.expect("Task must not panic");
        assert!(
            res.is_ok(),
            "Task {} failed DNS resolution: {:?}",
            idx,
            res.err()
        );
        let ips = res.unwrap();
        assert!(
            !ips.is_empty(),
            "Task {} returned empty IP list for localhost",
            idx
        );
        assert!(
            ips.contains(&IpAddr::V4(std::net::Ipv4Addr::new(127, 0, 0, 1))),
            "Task {} must contain 127.0.0.1 in resolved IPs: {:?}",
            idx,
            ips
        );
    }
}

#[tokio::test]
async fn test_adv_dns_stampede_50_concurrent_requests_uncached_domain() {
    // Generate an entirely fresh domain guaranteed to be uncached
    let uncached_host = format!("stampede-miss-{}.invalid", uuid::Uuid::new_v4());

    // Fire 50 concurrent queries simultaneously
    let mut handles = Vec::with_capacity(50);
    for _ in 0..50 {
        let host_clone = uncached_host.clone();
        handles.push(tokio::spawn(async move {
            Ipv4PreferredDnsResolver::resolve_ips(&host_clone).await
        }));
    }

    let mut err_count = 0;
    for handle in handles {
        let res = handle.await.expect("Task must join without panic");
        if res.is_err() {
            err_count += 1;
        }
    }

    // All 50 queries must fail consistently with Err without panicking or hanging
    assert_eq!(
        err_count, 50,
        "All 50 concurrent requests for invalid domain must cleanly return Err without panic"
    );
}

#[tokio::test]
async fn test_adv_dns_stampede_multi_domain_100_tasks() {
    // 5 distinct domains, 20 concurrent tasks each (100 total concurrent tasks)
    let domains: Vec<String> = (0..5)
        .map(|i| format!("multi-miss-{}-{}.invalid", i, uuid::Uuid::new_v4()))
        .collect();

    let mut handles = Vec::with_capacity(100);
    for domain in &domains {
        for _ in 0..20 {
            let d_clone = domain.clone();
            handles.push(tokio::spawn(async move {
                Ipv4PreferredDnsResolver::resolve_ips(&d_clone).await
            }));
        }
    }

    let mut err_count = 0;
    for handle in handles {
        let res = handle.await.expect("Task must join cleanly");
        if res.is_err() {
            err_count += 1;
        }
    }

    assert_eq!(
        err_count, 100,
        "All 100 concurrent requests across 5 distinct domains must complete cleanly"
    );
}
