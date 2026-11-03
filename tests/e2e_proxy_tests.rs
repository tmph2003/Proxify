//! Tier 1 & Tier 2 Opaque-Box Integration Tests for Proxify Proxy Data Plane
//!
//! Covers:
//! - Tier 1: Baseline HTTP/1.1 forwarding, GET/POST methods, query params, status codes,
//!   keep-alive, fastpath static assets, and stream rules.
//! - Tier 2: TLS MITM CONNECT handshake with dynamic leaf certs, multi-value Set-Cookie retention,
//!   chunked transfer encoding, large body streaming, gzip decompression, 502 Bad Gateway handling,
//!   and TLS passthrough.

use bytes::Bytes;
use flate2::write::GzEncoder;
use flate2::Compression;
use http_body_util::{BodyExt, Full};
use hyper::{Response, StatusCode};
use proxify::test_helpers::*;
use proxify_core::ca::CertificateAuthority;
use std::io::Write;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio_rustls::TlsConnector;

// =========================================================================
// TIER 1: Core Protocol & Baseline Forwarding
// =========================================================================

#[tokio::test]
async fn test_tier1_http11_simple_get_forwarding() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        assert_eq!(req.uri().path(), "/api/v1/resource");
        Response::builder()
            .status(StatusCode::OK)
            .header("Content-Type", "application/json")
            .body(Full::new(Bytes::from(r#"{"status":"success","data":"tier1_ok"}"#)).boxed())
            .unwrap()
    })
    .await;

    let target_url = upstream.url("/api/v1/resource");
    let (status, headers, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &target_url,
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get("content-type").and_then(|v| v.first()),
        Some(&"application/json".to_string())
    );
    assert_eq!(
        String::from_utf8_lossy(&body),
        r#"{"status":"success","data":"tier1_ok"}"#
    );
}

#[tokio::test]
async fn test_tier1_http11_post_with_body_and_headers() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        let body_bytes = req.into_body().collect().await.unwrap().to_bytes();
        let body_str = String::from_utf8_lossy(&body_bytes);
        assert_eq!(body_str, r#"{"msg":"hello proxify"}"#);

        Response::builder()
            .status(StatusCode::CREATED)
            .header("X-Custom-Echo", "verified")
            .body(Full::new(Bytes::from(r#"{"created":true}"#)).boxed())
            .unwrap()
    })
    .await;

    let target_url = upstream.url("/api/items");
    let req_body = br#"{"msg":"hello proxify"}"#;

    let (status, headers, body) = send_raw_proxy_request(
        proxy.addr,
        "POST",
        &target_url,
        &[
            ("Host", &format!("127.0.0.1:{}", upstream.addr.port())),
            ("Content-Type", "application/json"),
            ("X-Client-Trace", "trace-xyz-123"),
        ],
        req_body,
    )
    .await;

    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(
        headers.get("x-custom-echo").and_then(|v| v.first()),
        Some(&"verified".to_string())
    );
    assert_eq!(String::from_utf8_lossy(&body), r#"{"created":true}"#);
}

#[tokio::test]
async fn test_tier1_query_params_and_url_preservation() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        let pq = req.uri().path_and_query().unwrap().as_str().to_string();
        Response::builder()
            .status(StatusCode::OK)
            .body(Full::new(Bytes::from(pq)).boxed())
            .unwrap()
    })
    .await;

    let target_url = upstream.url("/search?query=rust+proxy&page=3&sort=asc&tag=network");
    let (status, _, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &target_url,
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        String::from_utf8_lossy(&body),
        "/search?query=rust+proxy&page=3&sort=asc&tag=network"
    );
}

#[tokio::test]
async fn test_tier1_status_code_propagation() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        match req.uri().path() {
            "/bad" => Response::builder()
                .status(StatusCode::BAD_REQUEST)
                .body(Full::new(Bytes::from("Bad Client Input")).boxed())
                .unwrap(),
            "/missing" => Response::builder()
                .status(StatusCode::NOT_FOUND)
                .body(Full::new(Bytes::from("Item Not Found")).boxed())
                .unwrap(),
            "/error" => Response::builder()
                .status(StatusCode::INTERNAL_SERVER_ERROR)
                .body(Full::new(Bytes::from("Upstream Crash")).boxed())
                .unwrap(),
            _ => Response::builder()
                .status(StatusCode::OK)
                .body(Full::new(Bytes::new()).boxed())
                .unwrap(),
        }
    })
    .await;

    for (path, expected_status) in [
        ("/bad", StatusCode::BAD_REQUEST),
        ("/missing", StatusCode::NOT_FOUND),
        ("/error", StatusCode::INTERNAL_SERVER_ERROR),
    ] {
        let (status, _, _) = send_raw_proxy_request(
            proxy.addr,
            "GET",
            &upstream.url(path),
            &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
            b"",
        )
        .await;
        assert_eq!(status, expected_status);
    }
}

#[tokio::test]
async fn test_tier1_keep_alive_connection_reuse() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|req| async move {
        let path = req.uri().path().to_string();
        Response::builder()
            .status(StatusCode::OK)
            .body(Full::new(Bytes::from(format!("Res: {}", path))).boxed())
            .unwrap()
    })
    .await;

    let mut stream = TcpStream::connect(proxy.addr).await.unwrap();

    for i in 1..=3 {
        let req_str = format!(
            "GET {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: keep-alive\r\n\r\n",
            upstream.url(&format!("/req-{}", i)),
            upstream.addr.port()
        );
        stream.write_all(req_str.as_bytes()).await.unwrap();

        let mut buf = vec![0u8; 2048];
        let n = stream.read(&mut buf).await.unwrap();
        let (status, _, body) = parse_raw_http_response(&buf[..n]);
        assert_eq!(status, StatusCode::OK);
        assert_eq!(String::from_utf8_lossy(&body), format!("Res: /req-{}", i));
    }
}

#[tokio::test]
async fn test_tier1_static_stream_fastpath() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|_| async move {
        Response::builder()
            .status(StatusCode::OK)
            .header("Content-Type", "image/png")
            .body(Full::new(Bytes::from_static(b"\x89PNG\r\n\x1a\nfake_image_data")).boxed())
            .unwrap()
    })
    .await;

    // Requests ending in .png trigger fast-path streaming
    let (status, headers, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &upstream.url("/static/logo.png"),
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get("content-type").and_then(|v| v.first()),
        Some(&"image/png".to_string())
    );
    assert_eq!(body, b"\x89PNG\r\n\x1a\nfake_image_data");
}

#[tokio::test]
async fn test_tier1_domain_stream_rule() {
    let proxy = TestProxyServer::start().await;
    proxy.router.register_stream_rule("custom-stream.local");

    assert!(proxy.router.should_stream("custom-stream.local"));
    assert!(proxy.router.should_stream("sub.custom-stream.local"));
    assert!(!proxy.router.should_stream("normal.local"));
}

// =========================================================================
// TIER 2: Advanced Protocols & Transport Edge Cases
// =========================================================================

#[tokio::test]
async fn test_tier2_multi_value_set_cookie_preservation() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|_| async move {
        let mut builder = Response::builder().status(StatusCode::OK);
        let hm = builder.headers_mut().unwrap();
        hm.append(
            "Set-Cookie",
            "session_id=abc123456; Path=/; HttpOnly".parse().unwrap(),
        );
        hm.append(
            "Set-Cookie",
            "theme=dark; Path=/; Max-Age=3600".parse().unwrap(),
        );
        hm.append(
            "Set-Cookie",
            "auth_token=jwt_xyz; Secure; SameSite=Strict"
                .parse()
                .unwrap(),
        );
        builder
            .body(Full::new(Bytes::from("Cookies set")).boxed())
            .unwrap()
    })
    .await;

    let (status, headers, _) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &upstream.url("/login"),
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    let cookies = headers
        .get("set-cookie")
        .expect("set-cookie headers must exist");
    assert!(
        cookies.len() >= 3,
        "All 3 Set-Cookie headers must be preserved without overwriting! Found: {:?}",
        cookies
    );
    assert!(cookies.iter().any(|c| c.contains("session_id=abc123456")));
    assert!(cookies.iter().any(|c| c.contains("theme=dark")));
    assert!(cookies.iter().any(|c| c.contains("auth_token=jwt_xyz")));
}

#[tokio::test]
async fn test_tier2_chunked_transfer_encoding() {
    let proxy = TestProxyServer::start().await;

    let upstream = MockHttpUpstream::start_with_handler(|_| async move {
        // Return response without content-length to trigger chunked transfer in HTTP/1.1
        Response::builder()
            .status(StatusCode::OK)
            .header("Transfer-Encoding", "chunked")
            .body(Full::new(Bytes::from("Chunked Content Received Successfully")).boxed())
            .unwrap()
    })
    .await;

    let (status, _, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &upstream.url("/stream"),
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        String::from_utf8_lossy(&body),
        "Chunked Content Received Successfully"
    );
}

#[tokio::test]
async fn test_tier2_large_payload_streaming() {
    let proxy = TestProxyServer::start().await;

    let size = 2 * 1024 * 1024; // 2 MB
    let large_data = vec![b'P'; size];
    let large_data_clone = large_data.clone();

    let upstream = MockHttpUpstream::start_with_handler(move |_| {
        let data = large_data_clone.clone();
        async move {
            Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "application/octet-stream")
                .body(Full::new(Bytes::from(data)).boxed())
                .unwrap()
        }
    })
    .await;

    let (status, _, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &upstream.url("/large-blob"),
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body.len(), size);
    assert_eq!(&body[..10], b"PPPPPPPPPP");
}

#[tokio::test]
async fn test_tier2_gzip_decompression_handling() {
    let proxy = TestProxyServer::start().await;

    let original_text =
        "This is compressed text that should be decompressed by Proxify MITM core engine.";
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(original_text.as_bytes()).unwrap();
    let gzipped_bytes = encoder.finish().unwrap();

    let upstream = MockHttpUpstream::start_with_handler(move |_| {
        let gzb = gzipped_bytes.clone();
        async move {
            Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "text/plain")
                .header("Content-Encoding", "gzip")
                .body(Full::new(Bytes::from(gzb)).boxed())
                .unwrap()
        }
    })
    .await;

    let (status, _, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &upstream.url("/compressed"),
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(String::from_utf8_lossy(&body), original_text);
}

#[tokio::test]
async fn test_tier2_upstream_connection_failure_502() {
    let proxy = TestProxyServer::start().await;

    // Connect to an unallocated port where no service is listening
    let unreachable_url = "http://127.0.0.1:59999/unreachable";

    let (status, _, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        unreachable_url,
        &[("Host", "127.0.0.1:59999")],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::BAD_GATEWAY);
    let body_str = String::from_utf8_lossy(&body);
    assert!(
        body_str.contains("Bad Gateway") || body_str.contains("Proxify Upstream Error"),
        "Body was: {}",
        body_str
    );
}

#[tokio::test]
async fn test_tier2_tls_mitm_connect_interception() {
    let proxy = TestProxyServer::start().await;

    // Upstream HTTPS server on ephemeral port
    let upstream_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = upstream_listener.local_addr().unwrap();

    // Setup TLS Server config for mock upstream
    let ca_temp = std::env::temp_dir().join(format!("mock_upstream_ca_{}", uuid::Uuid::new_v4()));
    let upstream_ca = CertificateAuthority::load_or_generate(&ca_temp).unwrap();
    let upstream_cfg = upstream_ca
        .server_config_for_host("mock.test.local")
        .unwrap();
    let acceptor = tokio_rustls::TlsAcceptor::from(upstream_cfg);

    tokio::spawn(async move {
        while let Ok((tcp, _)) = upstream_listener.accept().await {
            let acc = acceptor.clone();
            tokio::spawn(async move {
                if let Ok(mut tls) = acc.accept(tcp).await {
                    let mut buf = vec![0u8; 1024];
                    let n = tls.read(&mut buf).await.unwrap_or(0);
                    if n > 0 {
                        let resp = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 15\r\n\r\nHello from TLS!";
                        let _ = tls.write_all(resp).await;
                    }
                }
            });
        }
    });

    // 1. Client connects to proxy and issues CONNECT request
    let mut client_tcp = TcpStream::connect(proxy.addr).await.unwrap();
    let connect_req = format!(
        "CONNECT 127.0.0.1:{} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n\r\n",
        upstream_addr.port(),
        upstream_addr.port()
    );
    client_tcp.write_all(connect_req.as_bytes()).await.unwrap();

    let mut connect_resp = vec![0u8; 512];
    let n = client_tcp.read(&mut connect_resp).await.unwrap();
    let resp_str = String::from_utf8_lossy(&connect_resp[..n]);
    assert!(
        resp_str.starts_with("HTTP/1.1 200"),
        "CONNECT response: {}",
        resp_str
    );

    // 2. Client TLS handshake with Proxy (trusting proxy Root CA)
    let mut root_store = rustls::RootCertStore::empty();
    let ca_der = rustls::pki_types::CertificateDer::from(proxy.ca.ca_cert_der_bytes().to_vec());
    root_store.add(ca_der).unwrap();

    let client_tls_cfg = rustls::ClientConfig::builder()
        .with_root_certificates(root_store)
        .with_no_client_auth();
    let connector = TlsConnector::from(Arc::new(client_tls_cfg));
    let server_name = rustls::pki_types::ServerName::try_from("127.0.0.1".to_string()).unwrap();

    let mut tls_client = connector.connect(server_name, client_tcp).await.unwrap();

    // 3. Send encrypted HTTPS request through the MITM tunnel
    let https_req = format!(
        "GET /test HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
        upstream_addr.port()
    );
    tls_client.write_all(https_req.as_bytes()).await.unwrap();

    let mut response_bytes = Vec::new();
    tls_client.read_to_end(&mut response_bytes).await.unwrap();

    let (status, _, body) = parse_raw_http_response(&response_bytes);
    assert_eq!(status, StatusCode::OK);
    assert_eq!(String::from_utf8_lossy(&body), "Hello from TLS!");
}

#[tokio::test]
async fn test_tier2_tls_passthrough_whitelisted_domain() {
    let proxy = TestProxyServer::start().await;

    // Upstream TCP echo server simulating raw passthrough tunnel
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();

    tokio::spawn(async move {
        if let Ok((mut stream, _)) = listener.accept().await {
            let mut buf = vec![0u8; 128];
            let n = stream.read(&mut buf).await.unwrap();
            let _ = stream.write_all(&buf[..n]).await;
        }
    });

    // Send CONNECT for apple.com which is in passthrough_suffixes
    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    // Use apple.com authority with custom port to test tunnel
    let connect_req = format!(
        "CONNECT apple.com:{} HTTP/1.1\r\nHost: apple.com:{}\r\n\r\n",
        port, port
    );
    client.write_all(connect_req.as_bytes()).await.unwrap();

    let mut buf = vec![0u8; 512];
    let n = client.read(&mut buf).await.unwrap();
    let resp = String::from_utf8_lossy(&buf[..n]);
    assert!(
        resp.starts_with("HTTP/1.1 200"),
        "Passthrough tunnel established"
    );
}

#[tokio::test]
async fn test_tier2_http2_large_response_headers_exceeding_16kib_default() {
    use hyper::body::Incoming;
    use hyper::service::service_fn;
    use hyper::{Request, Version};
    use hyper_util::rt::{TokioExecutor, TokioIo};
    use proxify_core::proxy::HTTP2_MAX_HEADER_LIST_SIZE;
    use std::convert::Infallible;

    let proxy = TestProxyServer::start().await;

    // Spin up a real TLS + ALPN h2-only upstream mimicking Google ESF on www.youtube.com
    // returning >26 KiB of response headers (exceeding h2's 16 KiB default limit).
    let upstream_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = upstream_listener.local_addr().unwrap();

    let ca_temp =
        std::env::temp_dir().join(format!("mock_h2_upstream_ca_{}", uuid::Uuid::new_v4()));
    let upstream_ca = CertificateAuthority::load_or_generate(&ca_temp).unwrap();
    let base_cfg = upstream_ca.server_config_for_host("127.0.0.1").unwrap();
    let mut h2_only_cfg = (*base_cfg).clone();
    h2_only_cfg.alpn_protocols = vec![b"h2".to_vec()];
    let acceptor = tokio_rustls::TlsAcceptor::from(Arc::new(h2_only_cfg));

    let allowlist_val = "a".repeat(16_384);
    let permissions_val = "p".repeat(8_192);
    let reporting_val = "r".repeat(2_048);

    let allowlist_expected = allowlist_val.clone();
    let permissions_expected = permissions_val.clone();

    tokio::spawn(async move {
        while let Ok((tcp, _)) = upstream_listener.accept().await {
            let acc = acceptor.clone();
            let allow_h = allowlist_val.clone();
            let perm_h = permissions_val.clone();
            let rep_h = reporting_val.clone();

            tokio::spawn(async move {
                if let Ok(tls) = acc.accept(tcp).await {
                    let io = TokioIo::new(tls);
                    let svc = service_fn(move |req: Request<Incoming>| {
                        let allow_h = allow_h.clone();
                        let perm_h = perm_h.clone();
                        let rep_h = rep_h.clone();
                        async move {
                            assert_eq!(
                                req.version(),
                                Version::HTTP_2,
                                "Upstream must negotiate HTTP/2 via ALPN h2"
                            );
                            let is_js = req.uri().path().ends_with(".js");
                            let (ct, body) = if is_js {
                                ("application/javascript", "console.log('stream-h2-ok');")
                            } else {
                                ("text/html; charset=utf-8", "<!DOCTYPE html>youtube-h2-ok")
                            };

                            let resp = Response::builder()
                                .status(StatusCode::OK)
                                .header("content-type", ct)
                                .header("connection-allowlist-report-only", allow_h)
                                .header("permissions-policy", perm_h)
                                .header("reporting-endpoints", rep_h)
                                .body(Full::new(Bytes::from_static(body.as_bytes())).boxed())
                                .unwrap();
                            Ok::<_, Infallible>(resp)
                        }
                    });

                    let mut h2_builder =
                        hyper_util::server::conn::auto::Builder::new(TokioExecutor::new());
                    h2_builder
                        .http2()
                        .max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE);
                    let _ = h2_builder.serve_connection(io, svc).await;
                }
            });
        }
    });

    let client = reqwest::Client::builder()
        .proxy(reqwest::Proxy::all(proxy.proxy_url()).unwrap())
        .danger_accept_invalid_certs(true)
        .http2_max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE)
        .build()
        .unwrap();

    let chrome_156_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36";

    // 1. Buffered MITM inspection path (`upstream_client` -> `forward_upstream`)
    let html_url = format!("https://127.0.0.1:{}/", upstream_addr.port());
    let resp_html = client
        .get(&html_url)
        .header("User-Agent", chrome_156_ua)
        .send()
        .await
        .expect("Buffered MITM request over HTTP/2 with >26 KiB headers must succeed");

    assert_eq!(resp_html.status(), reqwest::StatusCode::OK);
    assert_eq!(
        resp_html
            .headers()
            .get("connection-allowlist-report-only")
            .and_then(|v| v.to_str().ok()),
        Some(allowlist_expected.as_str())
    );
    assert_eq!(
        resp_html
            .headers()
            .get("permissions-policy")
            .and_then(|v| v.to_str().ok()),
        Some(permissions_expected.as_str())
    );
    assert_eq!(
        resp_html.text().await.unwrap(),
        "<!DOCTYPE html>youtube-h2-ok"
    );

    // 2. Direct streaming fast-path (`stream_client` -> `stream_upstream_direct` for .js)
    let js_url = format!(
        "https://127.0.0.1:{}/s/desktop/player_base.js",
        upstream_addr.port()
    );
    let resp_js = client
        .get(&js_url)
        .header("User-Agent", chrome_156_ua)
        .send()
        .await
        .expect("Streaming fast-path request over HTTP/2 with >26 KiB headers must succeed");

    assert_eq!(resp_js.status(), reqwest::StatusCode::OK);
    assert_eq!(
        resp_js
            .headers()
            .get("connection-allowlist-report-only")
            .and_then(|v| v.to_str().ok()),
        Some(allowlist_expected.as_str())
    );
    assert_eq!(
        resp_js.text().await.unwrap(),
        "console.log('stream-h2-ok');"
    );

    let _ = std::fs::remove_dir_all(&ca_temp);
}
