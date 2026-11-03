//! Shared test harness utilities for 4-Tier opaque-box integration tests.

use bytes::Bytes;
use http_body_util::{combinators::BoxBody, BodyExt, Full};
use hyper::body::Incoming;
use hyper::service::service_fn;
use hyper::{Request, Response, StatusCode};
use hyper_util::rt::{TokioExecutor, TokioIo};
use parking_lot::Mutex;
use proxify_core::ca::CertificateAuthority;
use proxify_core::proxy::MitmProxyServer;
use proxify_core::router::ProxyRouter;
use proxify_core::storage::{create_pg_pool, RequestStorage};
use proxify_sdk::EventPublisher;
use serde_json::Value;
use std::collections::HashMap;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

/// In-memory mock event bus capturing published events for assertions
#[derive(Default)]
pub struct MockEventBus {
    pub events: Mutex<Vec<(String, Value)>>,
    pub ws_broadcasts: Mutex<Vec<(String, Value)>>,
}

impl MockEventBus {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get_events(&self, topic: &str) -> Vec<Value> {
        let guard = self.events.lock();
        guard
            .iter()
            .filter(|(t, _)| t == topic)
            .map(|(_, v)| v.clone())
            .collect()
    }

    pub fn has_event_topic(&self, topic: &str) -> bool {
        let guard = self.events.lock();
        guard.iter().any(|(t, _)| t == topic)
    }

    pub fn get_ws_broadcasts(&self, event_type: &str) -> Vec<Value> {
        let guard = self.ws_broadcasts.lock();
        guard
            .iter()
            .filter(|(et, _)| et == event_type)
            .map(|(_, v)| v.clone())
            .collect()
    }
}

impl EventPublisher for MockEventBus {
    fn publish(&self, topic: &str, payload: Value) -> bool {
        self.events.lock().push((topic.to_string(), payload));
        true
    }

    fn broadcast_ws(&self, event_type: &str, data: Value) {
        self.ws_broadcasts
            .lock()
            .push((event_type.to_string(), data));
    }
}

/// Managed test instance of MitmProxyServer bound to an ephemeral port
pub struct TestProxyServer {
    pub addr: SocketAddr,
    pub ca: Arc<CertificateAuthority>,
    pub router: Arc<ProxyRouter>,
    pub storage: Arc<RequestStorage>,
    pub event_bus: Arc<MockEventBus>,
    pub server: Arc<MitmProxyServer>,
}

impl TestProxyServer {
    pub async fn start() -> Self {
        let _ = rustls::crypto::ring::default_provider().install_default();

        let temp_dir =
            std::env::temp_dir().join(format!("proxify_test_ca_{}", uuid::Uuid::new_v4()));
        let _ = std::fs::create_dir_all(&temp_dir);

        let ca = CertificateAuthority::load_or_generate(&temp_dir)
            .expect("Failed to initialize test Certificate Authority");

        let router = Arc::new(ProxyRouter::new());
        let pool = create_pg_pool("postgresql://dummy:dummy@127.0.0.1:5432/dummy", 1)
            .expect("Pool creation");
        let storage = RequestStorage::new(pool);
        storage.set_saving(false); // Isolated: do not write to PostgreSQL

        let event_bus = Arc::new(MockEventBus::new());

        let server = MitmProxyServer::new(
            ca.clone(),
            router.clone(),
            storage.clone(),
            event_bus.clone(),
        );

        // Bind ephemeral port
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("Failed to find free port");
        let addr = listener.local_addr().expect("Local addr");
        drop(listener);

        let srv_clone = server.clone();
        tokio::spawn(async move {
            let _ = srv_clone.run(addr).await;
        });

        // Wait for proxy port to become ready
        let mut ready = false;
        for _ in 0..50 {
            tokio::time::sleep(Duration::from_millis(20)).await;
            if TcpStream::connect(addr).await.is_ok() {
                ready = true;
                break;
            }
        }
        assert!(ready, "Test proxy server failed to start on {}", addr);

        Self {
            addr,
            ca,
            router,
            storage,
            event_bus,
            server,
        }
    }

    pub fn proxy_url(&self) -> String {
        format!("http://{}", self.addr)
    }
}

/// Recorded request from mock upstream
#[derive(Debug, Clone)]
pub struct RecordedRequest {
    pub method: String,
    pub uri: String,
    pub headers: HashMap<String, String>,
    pub body: Vec<u8>,
}

type MockHandler = Arc<
    dyn Fn(
            Request<Incoming>,
        ) -> std::pin::Pin<
            Box<dyn std::future::Future<Output = Response<BoxBody<Bytes, Infallible>>> + Send>,
        > + Send
        + Sync,
>;

/// Mock HTTP Upstream server on an ephemeral port
pub struct MockHttpUpstream {
    pub addr: SocketAddr,
    pub requests: Arc<Mutex<Vec<RecordedRequest>>>,
    #[allow(dead_code)]
    handler: MockHandler,
}

impl MockHttpUpstream {
    pub async fn start_with_handler<F, Fut>(handler_fn: F) -> Self
    where
        F: Fn(Request<Incoming>) -> Fut + Send + Sync + 'static,
        Fut: std::future::Future<Output = Response<BoxBody<Bytes, Infallible>>> + Send + 'static,
    {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("Failed to bind mock upstream");
        let addr = listener.local_addr().expect("Local addr");
        let requests = Arc::new(Mutex::new(Vec::new()));

        let reqs_clone = requests.clone();
        let h_arc: MockHandler = Arc::new(move |req| Box::pin(handler_fn(req)));
        let handler_clone = h_arc.clone();

        tokio::spawn(async move {
            loop {
                let (stream, _) = match listener.accept().await {
                    Ok(p) => p,
                    Err(_) => break,
                };
                let reqs = reqs_clone.clone();
                let handler = handler_clone.clone();

                tokio::spawn(async move {
                    let io = TokioIo::new(stream);
                    let svc = service_fn(move |req: Request<Incoming>| {
                        let reqs = reqs.clone();
                        let handler = handler.clone();
                        async move {
                            let method = req.method().to_string();
                            let uri = req.uri().to_string();
                            let mut headers = HashMap::new();
                            for (k, v) in req.headers() {
                                if let Ok(s) = v.to_str() {
                                    headers.insert(k.to_string(), s.to_string());
                                }
                            }
                            let resp = handler(req).await;
                            reqs.lock().push(RecordedRequest {
                                method,
                                uri,
                                headers,
                                body: Vec::new(),
                            });
                            Ok::<_, Infallible>(resp)
                        }
                    });

                    let _ = hyper_util::server::conn::auto::Builder::new(TokioExecutor::new())
                        .serve_connection(io, svc)
                        .await;
                });
            }
        });

        Self {
            addr,
            requests,
            handler: h_arc,
        }
    }

    pub async fn start_simple_echo() -> Self {
        Self::start_with_handler(|req| async move {
            let path = req.uri().path().to_string();
            let body_bytes = req.into_body().collect().await.unwrap().to_bytes();
            let body_text = String::from_utf8_lossy(&body_bytes);
            let resp_text = format!("Echo from {}: {}", path, body_text);

            Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "text/plain")
                .header("X-Upstream-Echo", "true")
                .body(Full::new(Bytes::from(resp_text)).boxed())
                .unwrap()
        })
        .await
    }

    pub fn url(&self, path: &str) -> String {
        format!("http://127.0.0.1:{}{}", self.addr.port(), path)
    }

    pub fn recorded_requests(&self) -> Vec<RecordedRequest> {
        self.requests.lock().clone()
    }
}

/// Raw HTTP client sending absolute-form request via HTTP Proxy
pub async fn send_raw_proxy_request(
    proxy_addr: SocketAddr,
    method: &str,
    target_url: &str,
    headers: &[(&str, &str)],
    body: &[u8],
) -> (StatusCode, HashMap<String, Vec<String>>, Vec<u8>) {
    let mut stream = TcpStream::connect(proxy_addr)
        .await
        .expect("Failed to connect to proxy");

    let mut req_str = format!("{} {} HTTP/1.1\r\n", method, target_url);
    for (k, v) in headers {
        req_str.push_str(&format!("{}: {}\r\n", k, v));
    }
    if !headers
        .iter()
        .any(|(k, _)| k.eq_ignore_ascii_case("content-length"))
    {
        req_str.push_str(&format!("content-length: {}\r\n", body.len()));
    }
    req_str.push_str("connection: close\r\n\r\n");

    stream.write_all(req_str.as_bytes()).await.unwrap();
    if !body.is_empty() {
        stream.write_all(body).await.unwrap();
    }
    stream.flush().await.unwrap();

    let mut resp_bytes = Vec::new();
    stream.read_to_end(&mut resp_bytes).await.unwrap();

    parse_raw_http_response(&resp_bytes)
}

/// Helper parsing raw HTTP response bytes into status, multi-headers, and body
pub fn parse_raw_http_response(raw: &[u8]) -> (StatusCode, HashMap<String, Vec<String>>, Vec<u8>) {
    let mut headers_map: HashMap<String, Vec<String>> = HashMap::new();

    let header_end = raw
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .unwrap_or(raw.len());

    let header_bytes = &raw[..header_end];
    let body_bytes = if header_end + 4 <= raw.len() {
        raw[header_end + 4..].to_vec()
    } else {
        Vec::new()
    };

    let header_str = String::from_utf8_lossy(header_bytes);
    let mut lines = header_str.lines();

    let status_line = lines.next().unwrap_or("");
    let status_code = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|c| c.parse::<u16>().ok())
        .and_then(|code| StatusCode::from_u16(code).ok())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);

    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            let key = k.trim().to_lowercase();
            let val = v.trim().to_string();
            headers_map.entry(key).or_default().push(val);
        }
    }

    (status_code, headers_map, body_bytes)
}

/// Compute Sec-WebSocket-Accept key per RFC 6455
pub fn compute_websocket_accept(key: &str) -> String {
    use sha1::{Digest, Sha1};
    let mut hasher = Sha1::new();
    hasher.update(key.trim().as_bytes());
    hasher.update(b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11");
    let hash = hasher.finalize();
    base64::Engine::encode(&base64::engine::general_purpose::STANDARD, hash)
}
