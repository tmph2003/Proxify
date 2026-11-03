use bytes::Bytes;
use chrono::{DateTime, Utc};
use dashmap::DashMap;
use flate2::read::{DeflateDecoder, GzDecoder};
use flate2::write::GzEncoder;
use flate2::Compression;
use futures_util::StreamExt;
use http_body_util::{combinators::BoxBody, BodyExt, Full, StreamBody};
use hyper::body::{Frame, Incoming};
use hyper::service::service_fn;
use hyper::{Method, Request, Response, StatusCode};
use hyper_util::rt::{TokioExecutor, TokioIo};
use once_cell::sync::Lazy;
use proxify_sdk::{EventPublisher, FlowRequest, FlowResponse, HttpFlow};
use serde_json::json;
use std::collections::HashMap;
use std::convert::Infallible;
use std::io::{Read, Write};
use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::{TcpListener, TcpStream};
use tokio_rustls::TlsAcceptor;
use tracing::{debug, error, info, warn};

use crate::ca::CertificateAuthority;
use crate::graphql::GraphQLParser;
use crate::router::ProxyRouter;
use crate::storage::{RequestRecord, RequestStorage};

static DNS_CACHE: Lazy<DashMap<String, (Vec<IpAddr>, Instant)>> = Lazy::new(DashMap::new);
type DnsLookupSender = tokio::sync::broadcast::Sender<Result<Vec<IpAddr>, String>>;
static IN_FLIGHT_DNS: Lazy<DashMap<String, DnsLookupSender>> = Lazy::new(DashMap::new);
const DNS_CACHE_TTL: Duration = Duration::from_secs(60);

type ProxyBody = BoxBody<Bytes, Infallible>;

fn full_body(bytes: Bytes) -> ProxyBody {
    Full::new(bytes).boxed()
}

/// Custom DNS resolver with 60s TTL cache that prefers IPv4 addresses over IPv6 to prevent
/// unreachable IPv6 socket hangs inside Docker bridge networks and avoid per-request getaddrinfo blocking.
/// Implements single-flight deduplication to prevent thundering herd on concurrent cache misses.
pub struct Ipv4PreferredDnsResolver;

impl Ipv4PreferredDnsResolver {
    #[cfg(test)]
    pub fn clear_cache() {
        DNS_CACHE.clear();
        IN_FLIGHT_DNS.clear();
    }

    pub async fn resolve_ips(host: &str) -> std::io::Result<Vec<IpAddr>> {
        let key = host.trim().to_lowercase();
        if let Some(entry) = DNS_CACHE.get(&key) {
            let (ips, ts) = entry.value();
            if ts.elapsed() < DNS_CACHE_TTL && !ips.is_empty() {
                return Ok(ips.clone());
            }
        }

        // Single-flight deduplication: synchronize concurrent lookups for the same key
        let (is_leader, mut rx) = {
            use dashmap::mapref::entry::Entry;
            match IN_FLIGHT_DNS.entry(key.clone()) {
                Entry::Occupied(entry) => (false, entry.get().subscribe()),
                Entry::Vacant(entry) => {
                    let (tx, rx) = tokio::sync::broadcast::channel(1);
                    entry.insert(tx);
                    (true, rx)
                }
            }
        };

        if !is_leader {
            match rx.recv().await {
                Ok(Ok(ips)) => return Ok(ips),
                Ok(Err(err_msg)) => {
                    return Err(std::io::Error::other(err_msg));
                }
                Err(_) => {
                    // In-flight channel closed or lagged; fallback check on cache
                    if let Some(entry) = DNS_CACHE.get(&key) {
                        let (ips, ts) = entry.value();
                        if ts.elapsed() < DNS_CACHE_TTL && !ips.is_empty() {
                            return Ok(ips.clone());
                        }
                    }
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::NotFound,
                        "DNS resolution failed or canceled",
                    ));
                }
            }
        }

        // RAII drop guard for IN_FLIGHT_DNS cleanup on future cancellation
        struct DnsInFlightGuard<'a> {
            key: &'a str,
            completed: bool,
        }
        impl<'a> Drop for DnsInFlightGuard<'a> {
            fn drop(&mut self) {
                if !self.completed {
                    IN_FLIGHT_DNS.remove(self.key);
                }
            }
        }
        let mut guard = DnsInFlightGuard {
            key: &key,
            completed: false,
        };

        let lookup_res = tokio::net::lookup_host((key.as_str(), 0)).await;
        let final_res = match lookup_res {
            Ok(lookup) => {
                let mut v4 = Vec::new();
                let mut v6 = Vec::new();
                for addr in lookup {
                    match addr.ip() {
                        IpAddr::V4(ip) => {
                            if !v4.contains(&IpAddr::V4(ip)) {
                                v4.push(IpAddr::V4(ip));
                            }
                        }
                        IpAddr::V6(ip) => {
                            if !v6.contains(&IpAddr::V6(ip)) {
                                v6.push(IpAddr::V6(ip));
                            }
                        }
                    }
                }
                let result = if !v4.is_empty() { v4 } else { v6 };
                if !result.is_empty() {
                    if DNS_CACHE.len() > 4096 {
                        DNS_CACHE.retain(|_, (_, ts)| ts.elapsed() < DNS_CACHE_TTL);
                    }
                    DNS_CACHE.insert(key.clone(), (result.clone(), Instant::now()));
                    Ok(result)
                } else {
                    Err("No IP addresses found".to_string())
                }
            }
            Err(e) => Err(e.to_string()),
        };

        guard.completed = true;
        // Notify all waiting tasks and remove in-flight entry
        if let Some((_, tx)) = IN_FLIGHT_DNS.remove(&key) {
            let _ = tx.send(final_res.clone());
        }

        match final_res {
            Ok(ips) => Ok(ips),
            Err(err_msg) => Err(std::io::Error::other(err_msg)),
        }
    }
}

impl reqwest::dns::Resolve for Ipv4PreferredDnsResolver {
    fn resolve(&self, name: reqwest::dns::Name) -> reqwest::dns::Resolving {
        let host = name.as_str().to_string();
        Box::pin(async move {
            let ips = Self::resolve_ips(&host).await?;
            let addrs: reqwest::dns::Addrs =
                Box::new(ips.into_iter().map(|ip| SocketAddr::new(ip, 0)));
            Ok(addrs)
        })
    }
}

pub struct MitmProxyServer {
    pub ca: Arc<CertificateAuthority>,
    pub router: Arc<ProxyRouter>,
    pub storage: Arc<RequestStorage>,
    pub event_bus: Arc<dyn EventPublisher>,
    pub upstream_client: reqwest::Client,
    pub stream_client: reqwest::Client,
}

/// Matches Chromium's HTTP/2 `SETTINGS_MAX_HEADER_LIST_SIZE` (256 KiB).
/// Modern edge servers (e.g. Google ESF on `www.youtube.com`) return ~19–32 KiB
/// of response headers (`connection-allowlist-report-only`, `permissions-policy`, etc.)
/// to Chrome 156+ User-Agents, which exceeds `h2`'s 16 KiB default limit.
pub const HTTP2_MAX_HEADER_LIST_SIZE: u32 = 256 * 1024;

impl MitmProxyServer {
    pub fn new(
        ca: Arc<CertificateAuthority>,
        router: Arc<ProxyRouter>,
        storage: Arc<RequestStorage>,
        event_bus: Arc<dyn EventPublisher>,
    ) -> Arc<Self> {
        let dns_resolver = Arc::new(Ipv4PreferredDnsResolver);

        let upstream_client = reqwest::Client::builder()
            .dns_resolver(dns_resolver.clone())
            .danger_accept_invalid_certs(true)
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(30))
            .pool_idle_timeout(Duration::from_secs(20))
            .pool_max_idle_per_host(64)
            .tcp_keepalive(Duration::from_secs(15))
            .tcp_nodelay(true)
            .http2_adaptive_window(true)
            .http2_max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE)
            .http2_keep_alive_interval(Duration::from_secs(15))
            .http2_keep_alive_timeout(Duration::from_secs(10))
            .http2_keep_alive_while_idle(true)
            .no_proxy()
            .build()
            .unwrap_or_else(|e| {
                error!("[Proxy] Failed to build custom upstream_client: {}", e);
                reqwest::Client::new()
            });

        let stream_client = reqwest::Client::builder()
            .dns_resolver(dns_resolver)
            .danger_accept_invalid_certs(true)
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .pool_idle_timeout(Duration::from_secs(20))
            .pool_max_idle_per_host(64)
            .tcp_keepalive(Duration::from_secs(15))
            .tcp_nodelay(true)
            .http2_adaptive_window(true)
            .http2_max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE)
            .http2_keep_alive_interval(Duration::from_secs(15))
            .http2_keep_alive_timeout(Duration::from_secs(10))
            .http2_keep_alive_while_idle(true)
            .no_gzip()
            .no_brotli()
            .no_deflate()
            .no_proxy()
            .build()
            .unwrap_or_else(|e| {
                error!("[Proxy] Failed to build custom stream_client: {}", e);
                reqwest::Client::new()
            });

        Arc::new(Self {
            ca,
            router,
            storage,
            event_bus,
            upstream_client,
            stream_client,
        })
    }

    fn format_reqwest_error(err: &reqwest::Error) -> String {
        use std::error::Error as StdError;
        let mut msg = err.to_string();
        let mut current = err.source();
        while let Some(cause) = current {
            msg.push_str(": ");
            msg.push_str(&cause.to_string());
            current = cause.source();
        }
        msg
    }

    pub async fn run(self: Arc<Self>, addr: SocketAddr) -> Result<(), String> {
        let listener = TcpListener::bind(addr)
            .await
            .map_err(|e| format!("Failed to bind MITM proxy on {}: {}", addr, e))?;
        info!("[Proxy] MITM Proxy listening on http://{}", addr);

        loop {
            let (stream, peer_addr) = match listener.accept().await {
                Ok(pair) => pair,
                Err(e) => {
                    error!("[Proxy] TCP accept error: {}", e);
                    continue;
                }
            };

            let proxy = self.clone();
            tokio::spawn(async move {
                let io = TokioIo::new(stream);
                let svc = service_fn(move |req: Request<Incoming>| {
                    let p = proxy.clone();
                    async move { p.handle_client_request(req, "http", None).await }
                });

                let mut conn_builder =
                    hyper_util::server::conn::auto::Builder::new(TokioExecutor::new());
                conn_builder
                    .http2()
                    .max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE);

                if let Err(e) = conn_builder.serve_connection_with_upgrades(io, svc).await {
                    debug!("[Proxy] Connection closed from {}: {}", peer_addr, e);
                }
            });
        }
    }

    async fn handle_client_request(
        self: Arc<Self>,
        req: Request<Incoming>,
        default_scheme: &str,
        tls_host: Option<String>,
    ) -> Result<Response<ProxyBody>, hyper::Error> {
        if req.method() == Method::CONNECT {
            return self.handle_connect(req).await;
        }
        self.handle_http_request(req, default_scheme, tls_host)
            .await
    }

    fn should_stream_request(_host: &str, path: &str) -> bool {
        let p = path.split('?').next().unwrap_or("").to_lowercase();

        const STREAM_EXTENSIONS: &[&str] = &[
            ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif", ".woff", ".woff2",
            ".ttf", ".eot", ".otf", ".mp4", ".mp3", ".wav", ".ogg", ".webm", ".avi", ".mkv",
            ".flv", ".m4s", ".ts", ".css", ".map", ".wasm", ".pdf", ".zip", ".gz", ".br", ".zst",
            ".js", ".mjs",
        ];

        STREAM_EXTENSIONS.iter().any(|ext| p.ends_with(*ext))
    }

    fn should_stream_response_headers(content_type: &str, content_length: Option<u64>) -> bool {
        let ct = content_type.to_lowercase();
        if ct.starts_with("video/")
            || ct.starts_with("audio/")
            || ct.starts_with("image/")
            || ct.starts_with("font/")
            || ct.starts_with("text/css")
            || ct.starts_with("text/event-stream")
            || ct.contains("javascript")
            || ct.contains("application/wasm")
            || ct.contains("application/vnd.yt-ump")
            || ct.contains("application/x-protobuf")
            || ct.contains("application/octet-stream")
        {
            return true;
        }
        if let Some(len) = content_length {
            if len > 2 * 1024 * 1024 {
                return true;
            }
        }
        false
    }

    async fn stream_upstream_direct(&self, req: &FlowRequest) -> Response<ProxyBody> {
        let method =
            reqwest::Method::from_bytes(req.method.as_bytes()).unwrap_or(reqwest::Method::GET);

        let mut last_err = String::new();
        for attempt in 0..2 {
            let mut builder = self.stream_client.request(method.clone(), &req.url);
            for (k, v) in &req.headers {
                let k_low = k.to_lowercase();
                if matches!(
                    k_low.as_str(),
                    "host"
                        | "content-length"
                        | "connection"
                        | "keep-alive"
                        | "proxy-connection"
                        | "upgrade"
                        | "te"
                ) {
                    continue;
                }
                builder = builder.header(k, v);
            }
            if !req.content.is_empty() {
                builder = builder.body(req.content.clone());
            }

            match builder.send().await {
                Ok(resp) => {
                    return Self::convert_reqwest_to_stream_response(resp, false);
                }
                Err(e) => {
                    last_err = Self::format_reqwest_error(&e);
                    if attempt == 0 {
                        warn!(
                            "[Proxy] Stream upstream retry (attempt 1) for {} {}: {}",
                            req.method,
                            &req.url[..req.url.len().min(100)],
                            last_err
                        );
                        continue;
                    }
                }
            }
        }

        Response::builder()
            .status(StatusCode::BAD_GATEWAY)
            .header("Content-Type", "text/plain; charset=utf-8")
            .body(full_body(Bytes::from(format!(
                "Proxify Upstream Error: {}",
                last_err
            ))))
            .unwrap()
    }

    fn convert_reqwest_to_stream_response(
        resp: reqwest::Response,
        strip_encoding: bool,
    ) -> Response<ProxyBody> {
        let status = StatusCode::from_u16(resp.status().as_u16()).unwrap_or(StatusCode::OK);
        let mut builder = Response::builder().status(status);

        if let Some(headers_mut) = builder.headers_mut() {
            for (k, v) in resp.headers() {
                let k_low = k.as_str().to_lowercase();
                if matches!(
                    k_low.as_str(),
                    "transfer-encoding"
                        | "connection"
                        | "keep-alive"
                        | "proxy-connection"
                        | "upgrade"
                        | "http2-settings"
                        | "te"
                        | "alt-svc"
                ) {
                    continue;
                }
                if strip_encoding && matches!(k_low.as_str(), "content-length" | "content-encoding")
                {
                    continue;
                }
                if let (Ok(name), Ok(val)) = (
                    hyper::header::HeaderName::from_bytes(k.as_str().as_bytes()),
                    hyper::header::HeaderValue::from_bytes(v.as_bytes()),
                ) {
                    headers_mut.append(name, val);
                }
            }
        }

        let byte_stream = resp
            .bytes_stream()
            .map(|res| Ok::<Frame<Bytes>, Infallible>(Frame::data(res.unwrap_or_default())));
        let body = BodyExt::boxed(StreamBody::new(byte_stream));

        builder
            .body(body)
            .unwrap_or_else(|_| Response::new(full_body(Bytes::new())))
    }

    async fn handle_http_request(
        self: Arc<Self>,
        req: Request<Incoming>,
        default_scheme: &str,
        tls_host: Option<String>,
    ) -> Result<Response<ProxyBody>, hyper::Error> {
        let start = Instant::now();
        let timestamp = Utc::now().timestamp_millis() as f64 / 1000.0;
        let method = req.method().as_str().to_string();

        let host_header = req
            .headers()
            .get(hyper::header::HOST)
            .and_then(|v| v.to_str().ok())
            .unwrap_or_default()
            .to_string();

        let (scheme, host, port, path) =
            Self::extract_url_parts(&req, default_scheme, tls_host.as_deref(), &host_header);
        let full_url = if (scheme == "http" && port == 80) || (scheme == "https" && port == 443) {
            format!("{}://{}{}", scheme, host, path)
        } else {
            format!("{}://{}:{}{}", scheme, host, port, path)
        };

        if host == "mitm.it" || host == "proxify.ca" {
            return Ok(self.serve_mitm_it(&path));
        }

        if Self::is_websocket_upgrade(&req) {
            return self
                .handle_websocket_upgrade(req, &host, port, default_scheme == "https")
                .await;
        }

        let mut req_headers = HashMap::with_capacity(req.headers().len());
        for (k, v) in req.headers() {
            if let Ok(val_str) = v.to_str() {
                let key = k.as_str().to_string();
                req_headers
                    .entry(key)
                    .and_modify(|existing: &mut String| {
                        if k.as_str().eq_ignore_ascii_case("cookie") {
                            existing.push_str("; ");
                        } else if k.as_str().eq_ignore_ascii_case("set-cookie") {
                            existing.push('\n');
                        } else {
                            existing.push_str(", ");
                        }
                        existing.push_str(val_str);
                    })
                    .or_insert_with(|| val_str.to_string());
            }
        }

        let req_body_bytes = match req.into_body().collect().await {
            Ok(collected) => collected.to_bytes(),
            Err(_) => Bytes::new(),
        };

        let mut flow = HttpFlow {
            request: FlowRequest {
                method: method.clone(),
                url: full_url.clone(),
                host: host.clone(),
                port,
                path: path.clone(),
                scheme: scheme.clone(),
                headers: req_headers,
                content: req_body_bytes,
                timestamp_start: timestamp,
            },
            response: None,
        };

        let (observers, mutators) = self.router.resolve(&flow.request.host);
        for m in &mutators {
            m.mutate_request(&mut flow).await;
        }

        // Fast-path zero-decompression streaming for stream_rules, stream_path_rules, static assets, JS bundles
        let is_stream_excluded = self.router.is_stream_excluded(&host, &path);
        let should_stream = !is_stream_excluded
            && (self.router.should_stream(&host)
                || self.router.should_stream_path(&host, &path)
                || Self::should_stream_request(&host, &path));

        if flow.response.is_none() && should_stream {
            return Ok(self.stream_upstream_direct(&flow.request).await);
        }

        if flow.response.is_none() {
            match self.forward_upstream(&flow.request).await {
                Ok(upstream_resp) => {
                    flow.response = Some(upstream_resp);
                }
                Err(stream_resp) => {
                    return Ok(*stream_resp);
                }
            }
        }

        for m in &mutators {
            m.mutate_response(&mut flow).await;
        }

        let mut resp = flow.response.take().unwrap_or_else(|| FlowResponse {
            status_code: 502,
            headers: HashMap::new(),
            content: Bytes::from_static(b"Bad Gateway"),
        });

        // Strip Alt-Svc to prevent HTTP/3 QUIC bypass
        resp.headers
            .retain(|k, _| !k.eq_ignore_ascii_case("alt-svc"));

        let duration_ms = start.elapsed().as_secs_f64() * 1000.0;
        flow.response = Some(resp);

        let should_rec = self.router.should_record(&flow);
        let has_observers = !observers.is_empty();
        let mut resp = flow.response.take().unwrap();

        if has_observers || should_rec {
            let need_body_clone = has_observers
                || (should_rec && self.storage.should_save_domain(&flow.request.host));
            let cloned_resp = FlowResponse {
                status_code: resp.status_code,
                headers: resp.headers.clone(),
                content: if need_body_clone {
                    resp.content.clone()
                } else {
                    Bytes::new()
                },
            };
            let resp_size_bytes = resp.content.len() as i32;
            flow.response = Some(cloned_resp);
            let proxy_clone = self.clone();
            let flow_clone = flow;
            tokio::spawn(async move {
                proxy_clone
                    .observe_and_record(flow_clone, duration_ms, resp_size_bytes, should_rec)
                    .await;
            });
        }

        let mut builder = Response::builder()
            .status(StatusCode::from_u16(resp.status_code).unwrap_or(StatusCode::OK));

        let mut set_cookies: Vec<String> = Vec::new();
        let sc_keys: Vec<String> = resp
            .headers
            .keys()
            .filter(|k| k.eq_ignore_ascii_case("set-cookie"))
            .cloned()
            .collect();
        for key in sc_keys {
            if let Some(sc_str) = resp.headers.remove(&key) {
                for line in sc_str.split('\n') {
                    let trimmed = line.trim();
                    if !trimmed.is_empty() {
                        set_cookies.push(trimmed.to_string());
                    }
                }
            }
        }

        let body_bytes = resp.content;
        if let Some(headers_mut) = builder.headers_mut() {
            for (k, v) in &resp.headers {
                let k_low = k.to_lowercase();
                if matches!(
                    k_low.as_str(),
                    "transfer-encoding"
                        | "content-length"
                        | "content-encoding"
                        | "connection"
                        | "keep-alive"
                        | "proxy-connection"
                        | "upgrade"
                        | "http2-settings"
                        | "te"
                        | "alt-svc"
                ) {
                    continue;
                }
                if let Ok(name) = hyper::header::HeaderName::from_bytes(k.as_bytes()) {
                    for line in v.split('\n') {
                        let trimmed = line.trim();
                        if !trimmed.is_empty() {
                            if let Ok(val) = hyper::header::HeaderValue::from_str(trimmed) {
                                headers_mut.append(name.clone(), val);
                            }
                        }
                    }
                }
            }
            for sc in set_cookies {
                if let Ok(val) = hyper::header::HeaderValue::from_str(&sc) {
                    headers_mut.append(hyper::header::SET_COOKIE, val);
                }
            }
            headers_mut.insert(
                hyper::header::CONTENT_LENGTH,
                hyper::header::HeaderValue::from(body_bytes.len()),
            );
        }

        Ok(builder
            .body(full_body(body_bytes))
            .unwrap_or_else(|_| Response::new(full_body(Bytes::new()))))
    }

    async fn connect_ipv4_preferred(host: &str, port: u16) -> std::io::Result<TcpStream> {
        let ips = Ipv4PreferredDnsResolver::resolve_ips(host).await?;
        for ip in ips {
            let addr = SocketAddr::new(ip, port);
            if let Ok(Ok(stream)) =
                tokio::time::timeout(Duration::from_secs(3), TcpStream::connect(addr)).await
            {
                let _ = stream.set_nodelay(true);
                return Ok(stream);
            }
        }
        Err(std::io::Error::new(
            std::io::ErrorKind::TimedOut,
            format!("Failed to connect to {}:{}", host, port),
        ))
    }

    async fn handle_connect(
        self: Arc<Self>,
        req: Request<Incoming>,
    ) -> Result<Response<ProxyBody>, hyper::Error> {
        let authority = req
            .uri()
            .authority()
            .map(|a| a.as_str().to_string())
            .unwrap_or_default();
        let (host, port) = Self::parse_authority(&authority, 443);

        let bypass_mitm = Self::should_passthrough_tls(&host);
        let proxy = self.clone();

        tokio::spawn(async move {
            match hyper::upgrade::on(req).await {
                Ok(upgraded) => {
                    let mut client_io = TokioIo::new(upgraded);
                    if bypass_mitm {
                        if let Ok(mut server_stream) =
                            Self::connect_ipv4_preferred(&host, port).await
                        {
                            let _ =
                                tokio::io::copy_bidirectional(&mut client_io, &mut server_stream)
                                    .await;
                        }
                        return;
                    }

                    let server_cfg = match proxy.ca.server_config_for_host_async(&host).await {
                        Ok(cfg) => cfg,
                        Err(e) => {
                            error!("[Proxy] Failed to generate leaf cert for {}: {}", host, e);
                            return;
                        }
                    };

                    let acceptor = TlsAcceptor::from(server_cfg);
                    match acceptor.accept(client_io).await {
                        Ok(tls_stream) => {
                            let io = TokioIo::new(tls_stream);
                            let host_for_svc = host.clone();
                            let svc = service_fn(move |inner_req: Request<Incoming>| {
                                let p = proxy.clone();
                                let h = host_for_svc.clone();
                                async move { p.handle_http_request(inner_req, "https", Some(h)).await }
                            });

                            let mut conn_builder =
                                hyper_util::server::conn::auto::Builder::new(TokioExecutor::new());
                            conn_builder
                                .http2()
                                .max_header_list_size(HTTP2_MAX_HEADER_LIST_SIZE);
                            let _ = conn_builder.serve_connection_with_upgrades(io, svc).await;
                        }
                        Err(e) => {
                            debug!("[Proxy] TLS handshake failed for {}: {}", host, e);
                        }
                    }
                }
                Err(e) => {
                    debug!("[Proxy] CONNECT upgrade error for {}: {}", host, e);
                }
            }
        });

        Ok(Response::builder()
            .status(StatusCode::OK)
            .body(full_body(Bytes::new()))
            .unwrap())
    }

    async fn handle_websocket_upgrade(
        &self,
        mut req: Request<Incoming>,
        host: &str,
        port: u16,
        is_tls: bool,
    ) -> Result<Response<ProxyBody>, hyper::Error> {
        let path = req
            .uri()
            .path_and_query()
            .map(|pq| pq.as_str().to_string())
            .unwrap_or_else(|| "/".to_string());

        let mut raw_req = format!("{} {} HTTP/1.1\r\n", req.method(), path);
        for (k, v) in req.headers() {
            if let Ok(s) = v.to_str() {
                raw_req.push_str(&format!("{}: {}\r\n", k.as_str(), s));
            }
        }
        raw_req.push_str("\r\n");

        let tcp = match Self::connect_ipv4_preferred(host, port).await {
            Ok(s) => s,
            Err(_) => {
                return Ok(Response::builder()
                    .status(StatusCode::BAD_GATEWAY)
                    .body(full_body(Bytes::from_static(
                        b"WebSocket upstream connect failed",
                    )))
                    .unwrap());
            }
        };

        if is_tls {
            let mut root_store = rustls::RootCertStore::empty();
            root_store.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
            let client_cfg = rustls::ClientConfig::builder()
                .with_root_certificates(root_store)
                .with_no_client_auth();
            let connector = tokio_rustls::TlsConnector::from(Arc::new(client_cfg));
            let server_name = match rustls::pki_types::ServerName::try_from(host.to_string()) {
                Ok(sn) => sn,
                Err(_) => {
                    return Ok(Response::builder()
                        .status(StatusCode::BAD_GATEWAY)
                        .body(full_body(Bytes::from_static(b"Invalid SNI")))
                        .unwrap());
                }
            };
            let mut tls_upstream = match connector.connect(server_name, tcp).await {
                Ok(s) => s,
                Err(_) => {
                    return Ok(Response::builder()
                        .status(StatusCode::BAD_GATEWAY)
                        .body(full_body(Bytes::from_static(b"Upstream TLS failed")))
                        .unwrap());
                }
            };

            use tokio::io::AsyncWriteExt;
            let _ = tls_upstream.write_all(raw_req.as_bytes()).await;
            let (resp_head, leftover) = Self::read_http_headers(&mut tls_upstream)
                .await
                .unwrap_or_else(|_| (Vec::new(), Vec::new()));

            let (status, resp_headers) = Self::parse_raw_http_response(&resp_head);
            tokio::spawn(async move {
                if let Ok(upgraded) = hyper::upgrade::on(&mut req).await {
                    let mut client_io = TokioIo::new(upgraded);
                    if !leftover.is_empty() {
                        let _ = client_io.write_all(&leftover).await;
                    }
                    let _ = tokio::io::copy_bidirectional(&mut client_io, &mut tls_upstream).await;
                }
            });

            let mut builder = Response::builder().status(status);
            if let Some(hm) = builder.headers_mut() {
                for (k, v) in resp_headers {
                    if let (Ok(hn), Ok(hv)) = (
                        hyper::header::HeaderName::from_bytes(k.as_bytes()),
                        hyper::header::HeaderValue::from_str(&v),
                    ) {
                        hm.append(hn, hv);
                    }
                }
            }
            Ok(builder.body(full_body(Bytes::new())).unwrap())
        } else {
            let mut tcp_upstream = tcp;
            use tokio::io::AsyncWriteExt;
            let _ = tcp_upstream.write_all(raw_req.as_bytes()).await;
            let (resp_head, leftover) = Self::read_http_headers(&mut tcp_upstream)
                .await
                .unwrap_or_else(|_| (Vec::new(), Vec::new()));

            let (status, resp_headers) = Self::parse_raw_http_response(&resp_head);
            tokio::spawn(async move {
                if let Ok(upgraded) = hyper::upgrade::on(&mut req).await {
                    let mut client_io = TokioIo::new(upgraded);
                    if !leftover.is_empty() {
                        let _ = client_io.write_all(&leftover).await;
                    }
                    let _ = tokio::io::copy_bidirectional(&mut client_io, &mut tcp_upstream).await;
                }
            });

            let mut builder = Response::builder().status(status);
            if let Some(hm) = builder.headers_mut() {
                for (k, v) in resp_headers {
                    if let (Ok(hn), Ok(hv)) = (
                        hyper::header::HeaderName::from_bytes(k.as_bytes()),
                        hyper::header::HeaderValue::from_str(&v),
                    ) {
                        hm.append(hn, hv);
                    }
                }
            }
            Ok(builder.body(full_body(Bytes::new())).unwrap())
        }
    }

    async fn forward_upstream(
        &self,
        req: &FlowRequest,
    ) -> Result<FlowResponse, Box<Response<ProxyBody>>> {
        let method =
            reqwest::Method::from_bytes(req.method.as_bytes()).unwrap_or(reqwest::Method::GET);

        let mut last_err = String::new();
        for attempt in 0..2 {
            let mut builder = self.upstream_client.request(method.clone(), &req.url);
            for (k, v) in &req.headers {
                let k_low = k.to_lowercase();
                if matches!(
                    k_low.as_str(),
                    "host"
                        | "content-length"
                        | "connection"
                        | "keep-alive"
                        | "proxy-connection"
                        | "upgrade"
                        | "te"
                        | "accept-encoding"
                ) {
                    continue;
                }
                builder = builder.header(k, v);
            }
            builder = builder.header("Accept-Encoding", "gzip, deflate, br");

            if !req.content.is_empty() {
                builder = builder.body(req.content.clone());
            }

            match builder.send().await {
                Ok(resp) => {
                    let ct = resp
                        .headers()
                        .get(reqwest::header::CONTENT_TYPE)
                        .and_then(|v| v.to_str().ok())
                        .unwrap_or("");
                    let cl = resp.content_length();

                    // If response is media, binary stream, SSE, or >2MB, stream it directly without buffering in RAM
                    if !self.router.is_stream_excluded(&req.host, &req.path)
                        && Self::should_stream_response_headers(ct, cl)
                    {
                        return Err(Box::new(Self::convert_reqwest_to_stream_response(
                            resp, false,
                        )));
                    }

                    let status_code = resp.status().as_u16();
                    let mut headers: HashMap<String, String> =
                        HashMap::with_capacity(resp.headers().len());
                    let mut content_encoding = String::new();
                    for (k, v) in resp.headers() {
                        if let Ok(val_str) = v.to_str() {
                            if k.as_str().eq_ignore_ascii_case("content-encoding") {
                                content_encoding = val_str.to_lowercase();
                            } else if k.as_str().eq_ignore_ascii_case("set-cookie") {
                                headers
                                    .entry("set-cookie".to_string())
                                    .and_modify(|existing| {
                                        existing.push('\n');
                                        existing.push_str(val_str);
                                    })
                                    .or_insert_with(|| val_str.to_string());
                            } else {
                                headers
                                    .entry(k.as_str().to_string())
                                    .and_modify(|existing| {
                                        existing.push('\n');
                                        existing.push_str(val_str);
                                    })
                                    .or_insert_with(|| val_str.to_string());
                            }
                        }
                    }

                    let raw_bytes = resp.bytes().await.unwrap_or_default();
                    let decoded = if !content_encoding.is_empty() {
                        if raw_bytes.len() > 32 * 1024 {
                            let enc = content_encoding;
                            let raw_clone = raw_bytes.clone();
                            tokio::task::spawn_blocking(move || {
                                Self::decompress_body(&raw_clone, &enc)
                            })
                            .await
                            .unwrap_or(raw_bytes)
                        } else {
                            Self::decompress_body(&raw_bytes, &content_encoding)
                        }
                    } else {
                        raw_bytes
                    };

                    return Ok(FlowResponse {
                        status_code,
                        headers,
                        content: decoded,
                    });
                }
                Err(e) => {
                    last_err = Self::format_reqwest_error(&e);
                    if attempt == 0 {
                        warn!(
                            "[Proxy] Upstream send retry (attempt 1) for {} {}: {}",
                            req.method,
                            &req.url[..req.url.len().min(100)],
                            last_err
                        );
                        continue;
                    }
                }
            }
        }

        Ok(FlowResponse {
            status_code: 502,
            headers: HashMap::from([(
                "content-type".to_string(),
                "text/plain; charset=utf-8".to_string(),
            )]),
            content: Bytes::from(format!("Proxify Upstream Error: {}", last_err)),
        })
    }

    fn decompress_body(raw: &[u8], encoding: &str) -> Bytes {
        if raw.is_empty() {
            return Bytes::new();
        }
        if encoding.contains("gzip") {
            let mut decoder = GzDecoder::new(raw);
            let mut out = Vec::with_capacity(raw.len() * 3);
            if decoder.read_to_end(&mut out).is_ok() {
                return Bytes::from(out);
            }
        } else if encoding.contains("deflate") {
            let mut decoder = DeflateDecoder::new(raw);
            let mut out = Vec::with_capacity(raw.len() * 3);
            if decoder.read_to_end(&mut out).is_ok() {
                return Bytes::from(out);
            }
        } else if encoding.contains("br") {
            let mut out = Vec::with_capacity(raw.len() * 3);
            if brotli::BrotliDecompress(&mut std::io::Cursor::new(raw), &mut out).is_ok() {
                return Bytes::from(out);
            }
        } else if encoding.contains("zstd") {
            if let Ok(out) = zstd::stream::decode_all(std::io::Cursor::new(raw)) {
                return Bytes::from(out);
            }
        }
        Bytes::copy_from_slice(raw)
    }

    pub fn compress_gzip(data: &[u8]) -> Vec<u8> {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        let _ = encoder.write_all(data);
        encoder.finish().unwrap_or_else(|_| data.to_vec())
    }

    async fn observe_and_record(
        &self,
        mut flow: HttpFlow,
        duration_ms: f64,
        size_bytes: i32,
        should_rec: bool,
    ) {
        let (observers, _) = self.router.resolve(&flow.request.host);
        for obs in observers {
            obs.observe_response(&flow).await;
        }

        if !should_rec {
            return;
        }

        let content_type = flow
            .response_content_type()
            .split(';')
            .next()
            .unwrap_or("")
            .trim()
            .to_string();

        let req_ct = flow.request_content_type();
        let resp = match flow.response.take() {
            Some(r) => r,
            None => return,
        };

        let gql_info = GraphQLParser::parse(
            &flow.request.url,
            &flow.request.method,
            &req_ct,
            Some(&flow.request.content),
        );

        let is_graphql = if gql_info.is_some() { 1 } else { 0 };
        let (gql_op, gql_query, gql_vars) = match gql_info {
            Some(info) => (info.operation_name, info.query, info.variables),
            None => (None, None, None),
        };

        let req_uuid = uuid::Uuid::new_v4().to_string();
        let dt =
            DateTime::<Utc>::from_timestamp_millis((flow.request.timestamp_start * 1000.0) as i64)
                .map(|d| d.to_rfc3339())
                .unwrap_or_default();

        self.event_bus.broadcast_ws(
            "new_request",
            json!({
                "id": 0,
                "req_uuid": req_uuid,
                "timestamp": dt,
                "timestamp_epoch": flow.request.timestamp_start,
                "datetime": dt,
                "method": flow.request.method,
                "url": flow.request.url,
                "domain": flow.request.host,
                "host": flow.request.host,
                "path": flow.request.path,
                "status_code": resp.status_code,
                "content_type": content_type,
                "response_content_type": content_type,
                "duration_ms": (duration_ms * 100.0).round() / 100.0,
                "is_graphql": is_graphql != 0,
                "graphql_operation": gql_op,
                "response_size": size_bytes,
                "size_bytes": size_bytes,
            }),
        );

        if !self.storage.should_save_domain(&flow.request.host) {
            return;
        }

        let record = RequestRecord {
            id: None,
            timestamp: flow.request.timestamp_start,
            method: flow.request.method,
            url: flow.request.url,
            host: flow.request.host,
            path: flow.request.path,
            status_code: Some(resp.status_code as i32),
            request_headers: serde_json::to_string(&flow.request.headers)
                .unwrap_or_else(|_| "{}".to_string()),
            request_body: if flow.request.content.is_empty() {
                None
            } else {
                Some(flow.request.content)
            },
            response_headers: Some(
                serde_json::to_string(&resp.headers).unwrap_or_else(|_| "{}".to_string()),
            ),
            response_body: if resp.content.is_empty() {
                None
            } else {
                Some(resp.content)
            },
            content_type: if content_type.is_empty() {
                None
            } else {
                Some(content_type)
            },
            duration_ms: Some((duration_ms * 100.0).round() / 100.0),
            is_graphql,
            graphql_operation: gql_op,
            graphql_query: gql_query,
            graphql_variables: gql_vars,
            size_bytes,
        };

        self.storage.enqueue_tracked(record, req_uuid);
    }

    fn serve_mitm_it(&self, path: &str) -> Response<ProxyBody> {
        if path.contains("cert/pem") || path.ends_with(".pem") || path.ends_with(".crt") {
            return Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "application/x-x509-ca-cert")
                .header(
                    "Content-Disposition",
                    "attachment; filename=\"mitmproxy-ca-cert.pem\"",
                )
                .body(full_body(Bytes::from(
                    self.ca.ca_cert_pem().as_bytes().to_vec(),
                )))
                .unwrap();
        }
        if path.contains("cert/cer") || path.ends_with(".cer") || path.ends_with(".der") {
            return Response::builder()
                .status(StatusCode::OK)
                .header("Content-Type", "application/x-x509-ca-cert")
                .header(
                    "Content-Disposition",
                    "attachment; filename=\"mitmproxy-ca-cert.cer\"",
                )
                .body(full_body(Bytes::from(self.ca.ca_cert_der_bytes().to_vec())))
                .unwrap();
        }

        let html = r#"<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Proxify Rust MITM CA</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
.card{background:#1e293b;padding:2rem;border-radius:12px;max-width:480px;text-align:center;box-shadow:0 10px 25px rgba(0,0,0,.4)}
a.btn{display:inline-block;margin:.5rem;padding:.75rem 1.25rem;background:#3b82f6;color:#fff;text-decoration:none;border-radius:8px;font-weight:600}</style>
</head>
<body><div class="card">
<h2>Proxify Rust MITM Certificate Portal</h2>
<p>Install the Root CA certificate to inspect HTTPS traffic seamlessly:</p>
<a class="btn" href="/cert/pem">Download PEM / CRT (Windows / macOS / Linux)</a>
<a class="btn" href="/cert/cer">Download DER / CER</a>
</div></body></html>"#;

        Response::builder()
            .status(StatusCode::OK)
            .header("Content-Type", "text/html; charset=utf-8")
            .body(full_body(Bytes::from_static(html.as_bytes())))
            .unwrap()
    }

    pub fn should_passthrough_tls(host: &str) -> bool {
        let h = host.to_lowercase();
        let passthrough_suffixes = [
            "googlevideo.com",
            "c.youtube.com",
            "accounts.youtube.com",
            "signaler-pa.youtube.com",
            "accounts.google.com",
            "clients6.google.com",
            "client-channel.google.com",
            "gvt1.com",
            "gvt2.com",
            "gvt3.com",
            "ytimg.com",
            "ggpht.com",
            "gstatic.com",
            "fbsbx.com",
            "messenger.com",
            "instagram.com",
            "cdninstagram.com",
            "whatsapp.com",
            "whatsapp.net",
            "zadn.vn",
            "zdn.vn",
            "apple.com",
            "icloud.com",
            "githubassets.com",
            "githubusercontent.com",
            "1e100.net",
            "nel.goog",
            "msftncsi.com",
            "windowsupdate.com",
        ];
        passthrough_suffixes
            .iter()
            .any(|s| h == *s || h.ends_with(&format!(".{}", s)))
    }

    fn extract_url_parts(
        req: &Request<Incoming>,
        default_scheme: &str,
        tls_host: Option<&str>,
        host_header: &str,
    ) -> (String, String, u16, String) {
        let uri = req.uri();
        let scheme = uri.scheme_str().unwrap_or(default_scheme).to_lowercase();
        let default_port = if scheme == "https" { 443 } else { 80 };

        let authority = uri
            .authority()
            .map(|a| a.as_str())
            .filter(|a| !a.is_empty())
            .or(if !host_header.is_empty() {
                Some(host_header)
            } else {
                tls_host
            })
            .unwrap_or("localhost");

        let (host, port) = Self::parse_authority(authority, default_port);
        let path = uri
            .path_and_query()
            .map(|pq| pq.as_str().to_string())
            .unwrap_or_else(|| "/".to_string());

        (scheme, host, port, path)
    }

    fn parse_authority(authority: &str, default_port: u16) -> (String, u16) {
        if let Some((h, p_str)) = authority.rsplit_once(':') {
            if let Ok(p) = p_str.parse::<u16>() {
                return (h.to_lowercase(), p);
            }
        }
        (authority.to_lowercase(), default_port)
    }

    fn is_websocket_upgrade(req: &Request<Incoming>) -> bool {
        req.headers()
            .get(hyper::header::UPGRADE)
            .and_then(|v| v.to_str().ok())
            .map(|s| s.eq_ignore_ascii_case("websocket"))
            .unwrap_or(false)
    }

    pub fn find_header_end(buf: &[u8]) -> Option<usize> {
        buf.windows(4)
            .position(|w| w == b"\r\n\r\n")
            .map(|pos| pos + 4)
    }

    pub async fn read_http_headers<S>(stream: &mut S) -> std::io::Result<(Vec<u8>, Vec<u8>)>
    where
        S: tokio::io::AsyncRead + Unpin,
    {
        use tokio::io::AsyncReadExt;
        let mut buf = Vec::with_capacity(4096);
        let mut temp = [0u8; 1024];
        loop {
            if let Some(pos) = Self::find_header_end(&buf) {
                let leftover = buf.split_off(pos);
                return Ok((buf, leftover));
            }
            let n = stream.read(&mut temp).await?;
            if n == 0 {
                let len = buf.len();
                let pos = Self::find_header_end(&buf).unwrap_or(len);
                let leftover = buf.split_off(pos);
                return Ok((buf, leftover));
            }
            buf.extend_from_slice(&temp[..n]);
            if buf.len() > 64 * 1024 {
                let pos = Self::find_header_end(&buf).unwrap_or(buf.len());
                let leftover = buf.split_off(pos);
                return Ok((buf, leftover));
            }
        }
    }

    pub fn parse_raw_http_response(head: &[u8]) -> (StatusCode, Vec<(String, String)>) {
        let text = String::from_utf8_lossy(head);
        let mut lines = text.lines();
        let status_line = lines.next().unwrap_or("HTTP/1.1 101 Switching Protocols");
        let code = status_line
            .split_whitespace()
            .nth(1)
            .and_then(|s| s.parse::<u16>().ok())
            .and_then(|c| StatusCode::from_u16(c).ok())
            .unwrap_or(StatusCode::SWITCHING_PROTOCOLS);

        let mut headers = Vec::new();
        for line in lines {
            if let Some((k, v)) = line.split_once(':') {
                headers.push((k.trim().to_string(), v.trim().to_string()));
            }
        }
        (code, headers)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_facebook_tls_passthrough_disabled() {
        // Facebook domains must NOT be in passthrough suffixes so MITM interception works
        assert!(!MitmProxyServer::should_passthrough_tls("facebook.com"));
        assert!(!MitmProxyServer::should_passthrough_tls("www.facebook.com"));
        assert!(!MitmProxyServer::should_passthrough_tls("facebook.net"));
        assert!(!MitmProxyServer::should_passthrough_tls("fb.com"));
        assert!(!MitmProxyServer::should_passthrough_tls("m.fb.com"));
        assert!(!MitmProxyServer::should_passthrough_tls("fbcdn.net"));
        assert!(!MitmProxyServer::should_passthrough_tls(
            "static.xx.fbcdn.net"
        ));

        // Other passthrough suffixes must still pass through
        assert!(MitmProxyServer::should_passthrough_tls("googlevideo.com"));
        assert!(MitmProxyServer::should_passthrough_tls(
            "rr1---sn-oxunx-g5pe.googlevideo.com"
        ));
        assert!(MitmProxyServer::should_passthrough_tls("windowsupdate.com"));
    }

    #[test]
    fn test_find_header_end_detection() {
        let headers_only = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n";
        assert_eq!(
            MitmProxyServer::find_header_end(headers_only),
            Some(headers_only.len())
        );

        let headers_with_body =
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\nEXTRA_FRAME_BYTES";
        let expected_pos = headers_with_body.len() - "EXTRA_FRAME_BYTES".len();
        assert_eq!(
            MitmProxyServer::find_header_end(headers_with_body),
            Some(expected_pos)
        );

        let incomplete = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n";
        assert_eq!(MitmProxyServer::find_header_end(incomplete), None);
    }

    #[test]
    fn test_parse_raw_http_response() {
        let raw = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n";
        let (status, headers) = MitmProxyServer::parse_raw_http_response(raw);
        assert_eq!(status, StatusCode::SWITCHING_PROTOCOLS);
        assert_eq!(headers.len(), 3);
        assert_eq!(headers[0], ("Upgrade".to_string(), "websocket".to_string()));
        assert_eq!(
            headers[1],
            ("Connection".to_string(), "Upgrade".to_string())
        );
        assert_eq!(
            headers[2],
            (
                "Sec-WebSocket-Accept".to_string(),
                "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=".to_string()
            )
        );
    }

    #[tokio::test]
    async fn test_read_http_headers_stream_accumulation() {
        use std::io::Cursor;
        let mut data = Cursor::new(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\nleftover_data",
        );
        let (head, leftover) = MitmProxyServer::read_http_headers(&mut data).await.unwrap();
        assert_eq!(
            String::from_utf8_lossy(&head),
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n"
        );
        assert_eq!(leftover, b"leftover_data");
    }

    #[tokio::test]
    async fn test_dns_single_flight_and_cache() {
        Ipv4PreferredDnsResolver::clear_cache();

        // Concurrently resolve 10 requests for the same host
        let mut handles = Vec::new();
        for _ in 0..10 {
            handles.push(tokio::spawn(async {
                Ipv4PreferredDnsResolver::resolve_ips("127.0.0.1").await
            }));
        }

        for h in handles {
            let res = h.await.unwrap();
            assert!(res.is_ok());
            let ips = res.unwrap();
            assert!(!ips.is_empty());
            assert_eq!(ips[0], IpAddr::V4(std::net::Ipv4Addr::new(127, 0, 0, 1)));
        }
    }
}
