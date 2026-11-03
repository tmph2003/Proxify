//! Microbenchmarks for Proxify Critical Data Plane Components
//!
//! Measures:
//! 1. ProxyRouter Radix-Trie Domain Lookup (Exact, Wildcard, Miss, ShouldStream)
//! 2. HeaderMap Conversion & Multi-value Set-Cookie Processing
//! 3. CertificateAuthority CA Leaf Cache Hit vs Leaf Signing Generation

use criterion::{black_box, criterion_group, criterion_main, Criterion};
use hyper::header::{HeaderMap, HeaderName, HeaderValue};
use proxify_core::ca::CertificateAuthority;
use proxify_core::router::ProxyRouter;
use std::collections::HashMap;
use std::sync::Arc;

fn bench_router_resolution(c: &mut Criterion) {
    let mut group = c.benchmark_group("ProxyRouter");

    let router = ProxyRouter::new();
    // Populate router with rules
    router.register_stream_rule("*.googlevideo.com");
    router.register_stream_rule("*.zadn.vn");
    router.register_stream_rule("*.fbcdn.net");

    struct DummyMutator;
    #[async_trait::async_trait]
    impl proxify_sdk::MutatorInterceptor for DummyMutator {}
    let m = Arc::new(DummyMutator);

    router.register_mutator("*.youtube.com", m.clone());
    router.register_mutator("chat.zalo.me", m.clone());
    router.register_mutator("*.facebook.com", m);

    group.bench_function("resolve_exact_match", |b| {
        b.iter(|| {
            let res = router.resolve(black_box("chat.zalo.me"));
            black_box(res);
        })
    });

    group.bench_function("resolve_wildcard_match", |b| {
        b.iter(|| {
            let res = router.resolve(black_box("sub.music.youtube.com"));
            black_box(res);
        })
    });

    group.bench_function("resolve_unmatched_miss", |b| {
        b.iter(|| {
            let res = router.resolve(black_box("unknown-domain-not-in-rules.org"));
            black_box(res);
        })
    });

    group.bench_function("should_stream_check", |b| {
        b.iter(|| {
            let s = router.should_stream(black_box("rr1.googlevideo.com"));
            black_box(s);
        })
    });

    group.bench_function("router_match_lookup", |b| {
        b.iter(|| {
            let res = router.resolve(black_box("chat.zalo.me"));
            black_box(res);
        })
    });

    group.finish();
}

fn bench_headermap_conversion(c: &mut Criterion) {
    let mut group = c.benchmark_group("HeaderProcessing");

    let mut headers = HeaderMap::new();
    headers.insert(
        HeaderName::from_static("host"),
        HeaderValue::from_static("api.example.com"),
    );
    headers.insert(
        HeaderName::from_static("user-agent"),
        HeaderValue::from_static("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
    );
    headers.insert(
        HeaderName::from_static("accept"),
        HeaderValue::from_static("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    );
    headers.insert(
        HeaderName::from_static("accept-language"),
        HeaderValue::from_static("en-US,en;q=0.9,vi;q=0.8"),
    );
    headers.insert(
        HeaderName::from_static("accept-encoding"),
        HeaderValue::from_static("gzip, deflate, br, zstd"),
    );
    headers.insert(
        HeaderName::from_static("connection"),
        HeaderValue::from_static("keep-alive"),
    );
    headers.insert(
        HeaderName::from_static("upgrade-insecure-requests"),
        HeaderValue::from_static("1"),
    );
    headers.insert(
        HeaderName::from_static("sec-fetch-dest"),
        HeaderValue::from_static("document"),
    );
    headers.insert(
        HeaderName::from_static("sec-fetch-mode"),
        HeaderValue::from_static("navigate"),
    );
    headers.insert(
        HeaderName::from_static("sec-fetch-site"),
        HeaderValue::from_static("none"),
    );
    headers.insert(
        HeaderName::from_static("sec-fetch-user"),
        HeaderValue::from_static("?1"),
    );
    headers.insert(
        HeaderName::from_static("x-forwarded-for"),
        HeaderValue::from_static("10.0.0.1, 192.168.1.1"),
    );
    headers.insert(
        HeaderName::from_static("x-trace-id"),
        HeaderValue::from_static("trace-9876543210-abcdef"),
    );

    group.bench_function("convert_hyper_to_hashmap", |b| {
        b.iter(|| {
            let mut map: HashMap<String, String> = HashMap::with_capacity(headers.len());
            for (k, v) in headers.iter() {
                if let Ok(val) = v.to_str() {
                    map.insert(k.as_str().to_string(), val.to_string());
                }
            }
            black_box(map);
        })
    });

    let multi_cookie_str = "session_id=abcdef123456\ntheme=dark\nauth_token=jwt_xyz_890\npreference=grid_view\nlocale=vi-VN";
    group.bench_function("parse_multivalue_cookies", |b| {
        b.iter(|| {
            let mut cookies = Vec::with_capacity(5);
            for line in multi_cookie_str.split('\n') {
                let trimmed = line.trim();
                if !trimmed.is_empty() {
                    cookies.push(trimmed);
                }
            }
            black_box(cookies);
        })
    });

    group.bench_function("header_map_transformation", |b| {
        b.iter(|| {
            let cloned = headers.clone();
            black_box(cloned);
        })
    });

    group.finish();
}

fn bench_flow_buffer_zero_copy(c: &mut Criterion) {
    let mut group = c.benchmark_group("FlowBuffer");
    const PAYLOAD_SIZE: usize = 64 * 1024; // 64 KiB
    group.throughput(criterion::Throughput::Bytes(PAYLOAD_SIZE as u64));

    let bytes_buf = bytes::Bytes::from(vec![0x42u8; PAYLOAD_SIZE]);
    let vec_buf = vec![0x42u8; PAYLOAD_SIZE];

    group.bench_function("flow_buffer_zero_copy_clone", |b| {
        b.iter(|| {
            let cloned = bytes_buf.clone();
            black_box(cloned);
        })
    });

    group.bench_function("flow_buffer_deep_copy_clone", |b| {
        b.iter(|| {
            let cloned = vec_buf.clone();
            black_box(cloned);
        })
    });

    group.finish();
}

fn bench_ca_signing(c: &mut Criterion) {
    let _ = rustls::crypto::ring::default_provider().install_default();
    let mut group = c.benchmark_group("CertificateSigning");
    group.sample_size(20);

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_bench_ca_sign_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca = CertificateAuthority::load_or_generate(&temp_dir).unwrap();

    let mut sync_counter = 0u64;
    group.bench_function("tls_cert_signing_sync", |b| {
        b.iter(|| {
            sync_counter += 1;
            let host = format!("sync-{}.bench.test", sync_counter);
            let cfg = ca.server_config_for_host(&host).unwrap();
            black_box(cfg);
        })
    });

    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .worker_threads(4)
        .build()
        .unwrap();

    let mut async_counter = 0u64;
    group.bench_function("tls_cert_signing_async", |b| {
        b.iter(|| {
            async_counter += 1;
            let host = format!("async-{}.bench.test", async_counter);
            let ca_ref = ca.clone();
            rt.block_on(async {
                let cfg = ca_ref.server_config_for_host_async(&host).await.unwrap();
                black_box(cfg);
            })
        })
    });

    group.finish();
}

fn bench_ca_leaf_cache(c: &mut Criterion) {
    let _ = rustls::crypto::ring::default_provider().install_default();
    let mut group = c.benchmark_group("CertificateAuthority");

    let temp_dir = std::env::temp_dir().join(format!("proxify_bench_ca_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca = CertificateAuthority::load_or_generate(&temp_dir).unwrap();

    // Warm-up cache
    let cached_host = "cached-target.bench.local";
    let _ = ca.server_config_for_host(cached_host).unwrap();

    group.bench_function("leaf_cache_hit", |b| {
        b.iter(|| {
            let cfg = ca.server_config_for_host(black_box(cached_host)).unwrap();
            black_box(cfg);
        })
    });

    group.finish();
}

criterion_group!(
    benches,
    bench_router_resolution,
    bench_headermap_conversion,
    bench_flow_buffer_zero_copy,
    bench_ca_leaf_cache,
    bench_ca_signing
);
criterion_main!(benches);
