# Proxify v2.0 — Test Ready State (`TEST_READY.md`)

## 1. Test Suite Summary

The 4-Tier Opaque-Box Integration Test Suite and Criterion/Macro Benchmark Suite have been designed, structured, and implemented for Proxify v2.0.

| Tier | Suite Target | Scope / Features Covered | Test Count | Status |
|---|---|---|---|---|
| **Tier 1** | `tests/e2e_proxy_tests.rs` | HTTP/1.1 forwarding, GET/POST methods, query params, status codes, keep-alive, static fast-path, stream rules | 7 tests | **READY** |
| **Tier 2** | `tests/e2e_proxy_tests.rs` | TLS MITM CONNECT handshake with dynamic leaf certs, multi-value Set-Cookie, chunked transfer, 2MB streaming, gzip decode, 502 Bad Gateway, TLS passthrough | 7 tests | **READY** |
| **Tier 3** | `tests/e2e_websocket_tests.rs` | WebSocket 101 upgrade, bi-directional frame piping, multi-frame streaming, segmented 101 handshake, graceful close | 5 tests | **READY** |
| **Tier 4** | `tests/e2e_extension_tests.rs` | YouTube AdBlock 204 synthetic, JSON ad stripping, anti-AFK script injection, YouTube record filter, Facebook GraphQL observer, Radix-Trie hierarchy, mutator chains | 7 tests | **READY** |
| **Micro Bench** | `benches/proxy_micro_benches.rs` | Criterion benchmarks for ProxyRouter lookup (exact, wildcard, miss), HeaderMap conversion, CA leaf cache hit | 6 benchmarks | **READY** |
| **Macro Bench** | `scripts/benchmark_proxy.py` | Macro load test measuring throughput (QPS), latency percentiles (p50, p90, p99), error rate, memory footprint | 1 harness | **READY** |
| **Total** | | | **26 tests + Benchmarks** | **READY** |

---

## 2. Feature Checklist Mapping

- [x] **HTTP/1.1 Forwarding & RFC Compliance**: Method semantics, query parameter preservation, status code propagation (`tests/e2e_proxy_tests.rs`)
- [x] **TLS MITM Interception & Dynamic Certificate Authority**: CONNECT tunnel, leaf certificate generation, TLS handshake verification (`tests/e2e_proxy_tests.rs`)
- [x] **Multi-Value Header Retention**: Multi-line `Set-Cookie` headers preserved without overwriting (`tests/e2e_proxy_tests.rs`)
- [x] **Data Plane Streaming & Compression**: Chunked encoding, large payload (2MB) stream integrity, gzip decompression (`tests/e2e_proxy_tests.rs`)
- [x] **Upstream Resilience**: `502 Bad Gateway` returned gracefully for unreachable upstreams (`tests/e2e_proxy_tests.rs`)
- [x] **WebSocket Upgrade & Bi-Directional Streaming**: HTTP 101 Switching Protocols, bi-directional piping, segmented handshake accumulator (`tests/e2e_websocket_tests.rs`)
- [x] **YouTube Extension Interception**: Ad request blocking (`204 No Content`), Innertube JSON ad stripping, anti-AFK watchdog injection (`tests/e2e_extension_tests.rs`)
- [x] **Facebook GraphQL Extension**: GraphQL request/response observation and CQRS event publishing (`tests/e2e_extension_tests.rs`)
- [x] **Radix-Trie Domain Router**: Exact match, wildcard (`*.domain`), and stream rule resolution (`tests/e2e_extension_tests.rs`)
- [x] **Criterion Microbenchmarks**: Nanosecond profiling for router, headers, and CA leaf cache (`benches/proxy_micro_benches.rs`)
- [x] **Macro Load Test Harness**: Python load testing tool with latency percentiles and memory measurement (`scripts/benchmark_proxy.py`)

---

## 3. How to Run the Tests

### Integration Tests
```bash
# Run all integration tests
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_proxy_tests --test e2e_websocket_tests --test e2e_extension_tests

# Run individual test suites
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_proxy_tests
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_websocket_tests
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_extension_tests
```

### Benchmark Suite
```bash
# Run Criterion microbenchmarks
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo bench --bench proxy_micro_benches

# Run Macro Load Benchmark
python3 scripts/benchmark_proxy.py --requests 1000 --concurrency 25
```

---

## 4. Discovered Implementation Defects (Escalation)

During compilation and verification of the workspace targets, the following implementation issue was discovered in `crates/proxify-core`:

- **Issue**: Syntax error in `crates/proxify-core/src/router.rs` lines 125–130.
- **Root Cause**: `pub type ResolvedInterceptors` was defined inside `impl ProxyRouter {`, triggering rustc `error[E0658]: inherent associated types are unstable` and `error[E0425]: cannot find type ResolvedInterceptors in this scope`.
- **Recommended Fix**: Move `pub type ResolvedInterceptors` to module level (above `impl ProxyRouter {`) or restore tuple return type `(Vec<Arc<dyn ObserverInterceptor>>, Vec<Arc<dyn MutatorInterceptor>>)`.
- **Action**: Escalated to Milestone 1 implementing agent and orchestrator.
