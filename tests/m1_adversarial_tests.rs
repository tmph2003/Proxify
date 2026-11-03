//! Adversarial Hardening & Boundary Stress Tests for Milestone 1
//!
//! Evaluates:
//! 1. Shutdown race conditions & busy storage queue flushing without data loss or deadlocks.
//! 2. Buffer extremes & large payload streams (10MB+) with Content-Length preservation.
//! 3. Chunked large streams without Content-Length.
//! 4. Client abrupt disconnect mid-stream memory and panic safety.
//! 5. Fragmented WebSocket 101 Switching Protocols accumulation.
//! 6. DNS resolver single-flight thundering herd stress.

use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::{Response, StatusCode};
use proxify::test_helpers::*;
use proxify_core::proxy::Ipv4PreferredDnsResolver;
use proxify_core::storage::{create_pg_pool, init_core_schemas, RequestRecord, RequestStorage};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

fn make_test_record(host: &str, path: &str) -> RequestRecord {
    let now_ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);

    RequestRecord {
        id: None,
        timestamp: now_ts,
        method: "GET".to_string(),
        url: format!("http://{}{}", host, path),
        host: host.to_string(),
        path: path.to_string(),
        status_code: Some(200),
        request_headers: "{}".to_string(),
        request_body: None,
        response_headers: Some("{}".to_string()),
        response_body: None,
        content_type: Some("text/plain".to_string()),
        duration_ms: Some(15.2),
        is_graphql: 0,
        graphql_operation: None,
        graphql_query: None,
        graphql_variables: None,
        size_bytes: 128,
    }
}

// =========================================================================
// 1. Shutdown Race Conditions & Storage Flushing
// =========================================================================

#[tokio::test]
async fn test_adv_storage_shutdown_flushes_under_high_backlog() {
    let db_url = std::env::var("DATABASE_URL").unwrap_or_else(|_| {
        "postgresql://proxify_user:proxify_pass@proxify_db:5432/proxify_db".to_string()
    });

    // Attempt real database connection if available in the testing environment
    let is_db_available = if let Ok(pool) = create_pg_pool(&db_url, 5) {
        init_core_schemas(&pool).await.is_ok()
    } else {
        false
    };

    let pool = if is_db_available {
        create_pg_pool(&db_url, 5).expect("Valid pool")
    } else {
        create_pg_pool("postgresql://dummy:dummy@127.0.0.1:5432/dummy", 1).expect("Dummy pool")
    };

    let storage = RequestStorage::new(pool.clone());
    if is_db_available {
        storage.set_saving(true);
    } else {
        storage.set_saving(false);
    }

    let initial_count = if is_db_available {
        if let Ok(client) = pool.get().await {
            let row = client
                .query_one("SELECT COUNT(*) FROM public.requests", &[])
                .await
                .expect("Count query");
            row.get::<_, i64>(0)
        } else {
            0
        }
    } else {
        0
    };

    // Burst 150 records into the storage queue concurrently
    let test_tag = format!("test_host_{}.com", uuid::Uuid::new_v4());
    let records_count = 150;
    for i in 0..records_count {
        let record = make_test_record(&test_tag, &format!("/item/{}", i));
        storage.enqueue(record);
    }

    // Trigger shutdown while the queue is busy
    let shutdown_fut = storage.shutdown();
    let result = tokio::time::timeout(Duration::from_secs(10), shutdown_fut).await;
    assert!(
        result.is_ok(),
        "storage.shutdown() deadlocked or timed out under high backlog!"
    );

    // If real database was connected, verify all 150 records were flushed into PostgreSQL
    if is_db_available {
        let client = pool.get().await.expect("DB client after shutdown");
        let row = client
            .query_one("SELECT COUNT(*) FROM public.requests", &[])
            .await
            .expect("Final count query");
        let final_count: i64 = row.get(0);
        assert_eq!(
            final_count,
            initial_count + records_count as i64,
            "All pending batches must be flushed to DB without data loss!"
        );
    }
}

#[tokio::test]
async fn test_adv_storage_concurrent_multi_shutdown_deadlock_safety() {
    let pool =
        create_pg_pool("postgresql://dummy:dummy@127.0.0.1:5432/dummy", 1).expect("Dummy pool");
    let storage = RequestStorage::new(pool);
    storage.set_saving(false);

    // Concurrently call flush and shutdown from 10 tasks to test barrier races
    let mut tasks = Vec::new();
    for i in 0..10 {
        let st = storage.clone();
        tasks.push(tokio::spawn(async move {
            if i % 2 == 0 {
                st.shutdown().await;
            } else {
                st.flush().await;
            }
        }));
    }

    let timeout_res = tokio::time::timeout(Duration::from_secs(5), async {
        for t in tasks {
            t.await.expect("Task panic");
        }
    })
    .await;

    assert!(
        timeout_res.is_ok(),
        "Concurrent multi-shutdown/flush deadlocked!"
    );
}

// =========================================================================
// 2. Buffer Overflows & Large Payload Streaming (2MB+, 10MB)
// =========================================================================

#[tokio::test]
async fn test_adv_large_payload_streaming_10mb_preserves_content_length() {
    let proxy = TestProxyServer::start().await;

    let payload_size = 10 * 1024 * 1024; // 10 MB payload
    let mut raw_data = Vec::with_capacity(payload_size);
    for i in 0..payload_size {
        raw_data.push(((i ^ (i >> 8)) & 0xFF) as u8);
    }
    let data_clone = raw_data.clone();

    let upstream = MockHttpUpstream::start_with_handler(move |_| {
        let data = data_clone.clone();
        async move {
            Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "application/octet-stream")
                .header("Content-Length", data.len().to_string())
                .body(Full::new(Bytes::from(data)).boxed())
                .unwrap()
        }
    })
    .await;

    let (status, headers, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &upstream.url("/blob/10mb"),
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    let cl_header = headers.get("content-length").and_then(|v| v.first());
    assert_eq!(
        cl_header,
        Some(&payload_size.to_string()),
        "Content-Length must be strictly preserved on large payload stream!"
    );
    assert_eq!(
        body.len(),
        payload_size,
        "Body length received must match 10MB exactly"
    );
    assert_eq!(
        body[..1024],
        raw_data[..1024],
        "Payload data must match verbatim without corruption"
    );
    assert_eq!(
        body[payload_size - 1024..],
        raw_data[payload_size - 1024..],
        "Payload tail must match verbatim"
    );
}

fn decode_chunked_body(mut data: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    while !data.is_empty() {
        let pos = match data.windows(2).position(|w| w == b"\r\n") {
            Some(p) => p,
            None => break,
        };
        let hex_str = std::str::from_utf8(&data[..pos]).unwrap_or("0");
        let chunk_size = usize::from_str_radix(hex_str.trim(), 16).unwrap_or(0);
        if chunk_size == 0 {
            break;
        }
        data = &data[pos + 2..];
        if data.len() < chunk_size {
            out.extend_from_slice(data);
            break;
        }
        out.extend_from_slice(&data[..chunk_size]);
        data = &data[chunk_size..];
        if data.starts_with(b"\r\n") {
            data = &data[2..];
        }
    }
    out
}

#[tokio::test]
async fn test_adv_large_payload_streaming_chunked_no_content_length() {
    let proxy = TestProxyServer::start().await;

    let payload_size = 5 * 1024 * 1024; // 5 MB chunked payload
    let test_bytes = vec![0xAB; payload_size];
    let test_bytes_clone = test_bytes.clone();

    let upstream = MockHttpUpstream::start_with_handler(move |_| {
        let data = test_bytes_clone.clone();
        async move {
            // No Content-Length to trigger chunked HTTP/1.1 transfer
            Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "application/octet-stream")
                .header("Transfer-Encoding", "chunked")
                .body(Full::new(Bytes::from(data)).boxed())
                .unwrap()
        }
    })
    .await;

    let (status, headers, body) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &upstream.url("/chunked/5mb"),
        &[("Host", &format!("127.0.0.1:{}", upstream.addr.port()))],
        b"",
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    let te = headers
        .get("transfer-encoding")
        .and_then(|v| v.first())
        .map(|s| s.as_str());
    assert_eq!(
        te,
        Some("chunked"),
        "Transfer-Encoding must be chunked when Content-Length is absent"
    );
    let decoded = decode_chunked_body(&body);
    assert_eq!(
        decoded.len(),
        payload_size,
        "Chunked 5MB payload must be completely received when de-chunked"
    );
    assert_eq!(&decoded[..10], &[0xAB; 10]);
}

#[tokio::test]
async fn test_adv_large_stream_client_abrupt_disconnect_safety() {
    let proxy = TestProxyServer::start().await;

    // Upstream sends 10MB payload with small chunks and delay
    let upstream_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = upstream_listener.local_addr().unwrap();

    tokio::spawn(async move {
        while let Ok((mut stream, _)) = upstream_listener.accept().await {
            tokio::spawn(async move {
                let mut buf = vec![0u8; 1024];
                let _ = stream.read(&mut buf).await;
                let header = "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 10485760\r\n\r\n";
                if stream.write_all(header.as_bytes()).await.is_err() {
                    return;
                }
                let chunk = vec![b'X'; 65536];
                for _ in 0..160 {
                    if stream.write_all(&chunk).await.is_err() {
                        break;
                    }
                    tokio::time::sleep(Duration::from_millis(5)).await;
                }
            });
        }
    });

    // Client connects and abruptly disconnects after reading 64KB
    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let req = format!(
        "GET http://127.0.0.1:{}/abrupt HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
        upstream_addr.port(),
        upstream_addr.port()
    );
    client.write_all(req.as_bytes()).await.unwrap();

    let mut buf = vec![0u8; 65536];
    let n = client.read(&mut buf).await.unwrap_or(0);
    assert!(n > 0, "Client must have read initial chunk");
    drop(client); // Force TCP RST / FIN

    // Verify proxy is still healthy and responsive
    tokio::time::sleep(Duration::from_millis(50)).await;
    let (status, _, _) = send_raw_proxy_request(
        proxy.addr,
        "GET",
        &format!("http://127.0.0.1:{}/subsequent", upstream_addr.port()),
        &[("Host", &format!("127.0.0.1:{}", upstream_addr.port()))],
        b"",
    )
    .await;
    assert_eq!(
        status,
        StatusCode::OK,
        "Proxy must recover and serve subsequent requests after client abrupt disconnect"
    );
}

// =========================================================================
// 3. WebSocket Handshake & Accumulation Torture
// =========================================================================

#[tokio::test]
async fn test_adv_websocket_fragmented_handshake_accumulation() {
    let proxy = TestProxyServer::start().await;

    // Upstream server delivering 101 Switching Protocols response byte-by-byte
    let ws_upstream = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = ws_upstream.local_addr().unwrap();

    tokio::spawn(async move {
        if let Ok((mut stream, _)) = ws_upstream.accept().await {
            let mut buf = vec![0u8; 1024];
            let _ = stream.read(&mut buf).await;

            let response_str = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n";
            // Deliver in fragmented 3-byte chunks to test stream accumulator
            for chunk in response_str.as_bytes().chunks(3) {
                let _ = stream.write_all(chunk).await;
                tokio::time::sleep(Duration::from_millis(2)).await;
            }

            // Immediately send an unmasked WebSocket text frame ("adversarial_ok")
            let payload = b"adversarial_ok";
            let mut frame = vec![0x81, payload.len() as u8];
            frame.extend_from_slice(payload);
            let _ = stream.write_all(&frame).await;
        }
    });

    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let upgrade_req = format!(
        "GET http://127.0.0.1:{}/ws HTTP/1.1\r\n\
         Host: 127.0.0.1:{}\r\n\
         Upgrade: websocket\r\n\
         Connection: Upgrade\r\n\
         Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\
         Sec-WebSocket-Version: 13\r\n\r\n",
        upstream_addr.port(),
        upstream_addr.port()
    );
    client.write_all(upgrade_req.as_bytes()).await.unwrap();

    let mut buf = vec![0u8; 1024];
    let n = client.read(&mut buf).await.unwrap();
    let resp_str = String::from_utf8_lossy(&buf[..n]);
    assert!(
        resp_str.starts_with("HTTP/1.1 101 Switching Protocols"),
        "Fragmented handshake must be accumulated into valid 101 response: {}",
        resp_str
    );
}

// =========================================================================
// 4. DNS Single-Flight Concurrency Torture
// =========================================================================

#[tokio::test]
async fn test_adv_dns_single_flight_thundering_herd() {
    let mut handles = Vec::new();

    for _ in 0..50 {
        handles.push(tokio::spawn(async move {
            Ipv4PreferredDnsResolver::resolve_ips("127.0.0.1")
                .await
                .expect("DNS resolution")
        }));
    }

    let results = futures_util::future::join_all(handles).await;
    for r in results {
        let ips = r.expect("Join handle failed");
        assert!(
            ips.iter().any(|ip| ip.is_ipv4()),
            "Resolver must return valid IPv4 address under concurrency"
        );
    }
}
