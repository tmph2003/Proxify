//! Tier 3 Opaque-Box Integration Tests: WebSocket Upgrade & Bi-Directional Streaming
//!
//! Covers:
//! - Standard HTTP/1.1 101 Switching Protocols upgrade handshake
//! - Bi-directional payload frame piping across the proxy tunnel
//! - Multi-frame high-frequency message exchange
//! - Segmented 101 Switching Protocols handshake (fragmented TCP packet delivery)
//! - Clean connection termination

use hyper::StatusCode;
use proxify::test_helpers::*;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

#[tokio::test]
async fn test_tier3_websocket_upgrade_handshake() {
    let proxy = TestProxyServer::start().await;

    // Upstream mock WebSocket server
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = listener.local_addr().unwrap();

    let client_key = "dGhlIHNhbXBsZSBub25jZQ==";
    let expected_accept = compute_websocket_accept(client_key);
    let accept_clone = expected_accept.clone();

    tokio::spawn(async move {
        if let Ok((mut stream, _)) = listener.accept().await {
            let mut buf = vec![0u8; 2048];
            let n = stream.read(&mut buf).await.unwrap();
            let req = String::from_utf8_lossy(&buf[..n]);

            assert!(req.contains("Upgrade: websocket") || req.contains("upgrade: websocket"));
            assert!(
                req.contains("Connection: Upgrade")
                    || req.contains("connection: Upgrade")
                    || req.contains("connection: upgrade")
            );

            let resp = format!(
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
                accept_clone
            );
            let _ = stream.write_all(resp.as_bytes()).await;
        }
    });

    // Client connects to proxy and requests WebSocket upgrade
    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let ws_req = format!(
        "GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n",
        upstream_addr.port(),
        client_key
    );
    client.write_all(ws_req.as_bytes()).await.unwrap();

    let mut resp_buf = vec![0u8; 1024];
    let n = client.read(&mut resp_buf).await.unwrap();
    let (status, headers, _) = parse_raw_http_response(&resp_buf[..n]);

    assert_eq!(status, StatusCode::SWITCHING_PROTOCOLS);
    assert_eq!(
        headers
            .get("upgrade")
            .and_then(|v| v.first())
            .map(|s| s.to_lowercase()),
        Some("websocket".to_string())
    );
    assert_eq!(
        headers.get("sec-websocket-accept").and_then(|v| v.first()),
        Some(&expected_accept)
    );
}

#[tokio::test]
async fn test_tier3_websocket_bidirectional_frame_piping() {
    let proxy = TestProxyServer::start().await;

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = listener.local_addr().unwrap();

    let client_key = "x3JJHMbDL1EzLkh9GBhXDw==";
    let accept_key = compute_websocket_accept(client_key);

    tokio::spawn(async move {
        if let Ok((mut stream, _)) = listener.accept().await {
            let mut buf = vec![0u8; 2048];
            let n = stream.read(&mut buf).await.unwrap();
            let _ = &buf[..n];

            let resp = format!(
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
                accept_key
            );
            stream.write_all(resp.as_bytes()).await.unwrap();

            // Read message from client through proxy tunnel
            let mut frame_buf = vec![0u8; 512];
            let fn_read = stream.read(&mut frame_buf).await.unwrap();
            let received_msg = String::from_utf8_lossy(&frame_buf[..fn_read]);

            // Echo back with prefix
            let echo = format!("Echo: {}", received_msg);
            stream.write_all(echo.as_bytes()).await.unwrap();
        }
    });

    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let ws_req = format!(
        "GET /chat HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n",
        upstream_addr.port(),
        client_key
    );
    client.write_all(ws_req.as_bytes()).await.unwrap();

    // Read 101 Switching Protocols handshake
    let mut resp_buf = vec![0u8; 512];
    let n = client.read(&mut resp_buf).await.unwrap();
    let (status, _, _) = parse_raw_http_response(&resp_buf[..n]);
    assert_eq!(status, StatusCode::SWITCHING_PROTOCOLS);

    // Send payload through upgraded tunnel
    let test_payload = "ping-through-proxy-websocket-tunnel";
    client.write_all(test_payload.as_bytes()).await.unwrap();

    // Read echoed payload
    let mut echo_buf = vec![0u8; 512];
    let echo_n = client.read(&mut echo_buf).await.unwrap();
    let echo_str = String::from_utf8_lossy(&echo_buf[..echo_n]);

    assert_eq!(echo_str, format!("Echo: {}", test_payload));
}

#[tokio::test]
async fn test_tier3_websocket_multiframe_streaming() {
    let proxy = TestProxyServer::start().await;

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = listener.local_addr().unwrap();

    let client_key = "sN8Y0Gk7wR9f3u1m2o5q==";
    let accept_key = compute_websocket_accept(client_key);

    tokio::spawn(async move {
        if let Ok((mut stream, _)) = listener.accept().await {
            let mut buf = vec![0u8; 1024];
            let _ = stream.read(&mut buf).await.unwrap();

            let resp = format!(
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
                accept_key
            );
            stream.write_all(resp.as_bytes()).await.unwrap();

            // Echo loop for 5 frames
            for _ in 0..5 {
                let mut frame = vec![0u8; 256];
                let n = stream.read(&mut frame).await.unwrap();
                if n == 0 {
                    break;
                }
                stream.write_all(&frame[..n]).await.unwrap();
            }
        }
    });

    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let ws_req = format!(
        "GET /stream HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n",
        upstream_addr.port(),
        client_key
    );
    client.write_all(ws_req.as_bytes()).await.unwrap();

    let mut handshake_buf = vec![0u8; 512];
    let n = client.read(&mut handshake_buf).await.unwrap();
    let (status, _, _) = parse_raw_http_response(&handshake_buf[..n]);
    assert_eq!(status, StatusCode::SWITCHING_PROTOCOLS);

    for i in 1..=5 {
        let msg = format!("frame-seq-{}", i);
        client.write_all(msg.as_bytes()).await.unwrap();

        let mut read_buf = vec![0u8; 256];
        let rn = client.read(&mut read_buf).await.unwrap();
        assert_eq!(String::from_utf8_lossy(&read_buf[..rn]), msg);
    }
}

#[tokio::test]
async fn test_tier3_websocket_segmented_101_handshake() {
    let proxy = TestProxyServer::start().await;

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = listener.local_addr().unwrap();

    let client_key = "seg_test_key_1234567==";
    let accept_key = compute_websocket_accept(client_key);

    // Mock upstream that delivers 101 response in two distinct TCP segments
    let accept_key_clone = accept_key.clone();
    tokio::spawn(async move {
        if let Ok((mut stream, _)) = listener.accept().await {
            let mut buf = vec![0u8; 1024];
            let _ = stream.read(&mut buf).await.unwrap();

            // Segment 1: Status line only
            let seg1 = "HTTP/1.1 101 Switching Protocols\r\n";
            stream.write_all(seg1.as_bytes()).await.unwrap();
            stream.flush().await.unwrap();

            // Delay between packets
            tokio::time::sleep(Duration::from_millis(30)).await;

            // Segment 2: Remaining headers and double CRLF boundary
            let seg2 = format!(
                "Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
                accept_key_clone
            );
            stream.write_all(seg2.as_bytes()).await.unwrap();
            stream.flush().await.unwrap();
        }
    });

    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let ws_req = format!(
        "GET /segmented-ws HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n",
        upstream_addr.port(),
        client_key
    );
    client.write_all(ws_req.as_bytes()).await.unwrap();

    let mut resp_buf = vec![0u8; 1024];
    let n = client.read(&mut resp_buf).await.unwrap();
    let (status, headers, _) = parse_raw_http_response(&resp_buf[..n]);

    // Verify proxy properly accumulated segmented headers or returned 101
    assert_eq!(status, StatusCode::SWITCHING_PROTOCOLS);
    assert_eq!(
        headers.get("sec-websocket-accept").and_then(|v| v.first()),
        Some(&accept_key)
    );
}

#[tokio::test]
async fn test_tier3_websocket_graceful_close() {
    let proxy = TestProxyServer::start().await;

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let upstream_addr = listener.local_addr().unwrap();

    let client_key = "close_test_key_xyz==";
    let accept_key = compute_websocket_accept(client_key);

    tokio::spawn(async move {
        if let Ok((mut stream, _)) = listener.accept().await {
            let mut buf = vec![0u8; 1024];
            let _ = stream.read(&mut buf).await.unwrap();

            let resp = format!(
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
                accept_key
            );
            stream.write_all(resp.as_bytes()).await.unwrap();

            // Wait for client to close connection
            let mut close_buf = vec![0u8; 64];
            let _ = stream.read(&mut close_buf).await;
        }
    });

    let mut client = TcpStream::connect(proxy.addr).await.unwrap();
    let ws_req = format!(
        "GET /close-test HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n",
        upstream_addr.port(),
        client_key
    );
    client.write_all(ws_req.as_bytes()).await.unwrap();

    let mut resp_buf = vec![0u8; 512];
    let n = client.read(&mut resp_buf).await.unwrap();
    let (status, _, _) = parse_raw_http_response(&resp_buf[..n]);
    assert_eq!(status, StatusCode::SWITCHING_PROTOCOLS);

    // Shutdown client write half
    client.shutdown().await.unwrap();
}
