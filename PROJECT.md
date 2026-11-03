# Project: Proxify — Architecture & Performance Optimization

## Architecture
Proxify is a high-performance network proxy engine written in pure Rust (workspace v2.0), featuring TLS MITM interception, dynamic CA generation, stream routing, extension hooks, and a real-time dashboard.

### Layer Hierarchy
```
┌────────────────────────────────────────────────────────┐
│                   Presentation Layer                   │
│   crates/proxify-server (CLI, Axum REST, WebSocket)    │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                    Application Layer                   │
│   Extension Plugins: ext-youtube, ext-facebook,        │
│   ext-zalo (Domain Observers, Mutators, Harvesters)    │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                       Domain Layer                     │
│   crates/proxify-sdk (FlowRequest, FlowResponse,       │
│   traits: RequestObserver, ResponseMutator, Storage)   │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                  Infrastructure Layer                  │
│   crates/proxify-core:                                 │
│   - Network/Data Plane (Hyper, Tokio, Rustls, Ring)   │
│   - CA & Cert Engine (rcgen, DashMap LRU cache)        │
│   - Storage Engine (deadpool-postgres, batch flush)    │
│   - Event Bus & Router (tokio::sync, radix trie)       │
└────────────────────────────────────────────────────────┘
```

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | TLS MITM Passthrough Fix | Remove `facebook.com` / `fb.com` from `passthrough_suffixes` to restore Facebook HTTPS interception | M1 | explorer_survey_correctness |
| 2 | WebSocket Stream Framing Fix | Replace single `.read()` with stream buffer accumulator until `\r\n\r\n` boundary | M1 | explorer_survey_correctness |
| 3 | Multi-Value Header Retention | Eliminate `HashMap<String, String>` overwrites for duplicate headers (`Set-Cookie`, `Accept`) | M1 | explorer_survey_correctness |
| 4 | DNS Single-Flight Deduplication | Add single-flight synchronization to `Ipv4PreferredDnsResolver` to prevent thundering herd | M1 | explorer_survey_correctness |
| 5 | Graceful Process Shutdown | Implement signal handling (`tokio::signal::ctrl_c`) to flush in-flight storage records cleanly | M1 | explorer_survey_correctness |
| 6 | Clippy Warnings Cleanup | Fix all 6 `cargo clippy --all-targets` warnings across all workspace crates | M1 | explorer_survey_correctness |
| 7 | Formatting Harmonization | Format entire codebase to standard style with `cargo fmt` | M1 | explorer_survey_correctness |
| 8 | Asynchronous TLS Leaf Signing | Offload `rcgen::signed_by` from Tokio reactor worker threads to `spawn_blocking` with single-flight | M2 | explorer_survey_perf |
| 9 | Zero-Copy Flow Buffers | Migrate `FlowRequest`/`FlowResponse` payload buffers to `bytes::Bytes` with zero-copy refcounting | M2 | explorer_survey_perf |
| 10 | Header Map Zero-Copy Pipeline | Directly bridge Hyper `HeaderMap` and `http::HeaderMap` to eliminate 120-150 string allocations/req | M2 | explorer_survey_perf |
| 11 | Lock-Free / Pre-normalized Router | Eliminate `format!(".{}", d)` allocations and pre-normalize stream suffixes in `ProxyRouter` | M2 | explorer_survey_perf |
| 12 | Vectorized Database Batch Flush | Convert sequential row-by-row queries in `flush_batch` to single multi-row `INSERT` / `UNNEST` | M2 | explorer_survey_perf |
| 13 | Release Profile & Mimalloc | Enable `lto = "fat"`, `codegen-units = 1`, and high-performance allocator `mimalloc` | M2 | explorer_survey_perf |
| 14 | Vendor Logic Core Decoupling | Decouple hardcoded Zalo and YouTube streaming paths from `proxy.rs::should_stream_request` | M3 | explorer_survey_arch |
| 15 | Generic GraphQL & Stealth Rules | Remove Facebook-specific parameter names from `graphql.rs` and vendor error codes from `stealth.rs` | M3 | explorer_survey_arch |
| 16 | SDK Concrete Types Abstraction | Encapsulate `deadpool_postgres::Pool` and `axum::Router` in `proxify-sdk`, fix `on_Init` naming smell | M3 | explorer_survey_arch |
| 17 | Auto-Documentation in docs/ | Generate comprehensive Vietnamese documentation for all modified modules per auto_doc rule | M1-M3 | project_rule |
| 18 | 4-Tier E2E Test Suite | Comprehensive opaque-box test suite (Tiers 1-4) testing proxy, protocols, extensions, edge cases | TRACK_E2E | user_request |
| 19 | Micro & Macro Benchmark Suite | Criterion microbenchmarks + macro throughput/latency load test harness measuring before vs after | TRACK_E2E | user_request |
| 20 | Final Integration & E2E Test Pass | Pass 100% of the 4-Tier E2E test suite with 0 regressions | M4 | user_request |
| 21 | Adversarial Hardening (Tier 5) | Challenger-led stress tests (500+ QPS, buffer boundaries, slowloris, packet segmentation) | M4 | project_pattern |
| 22 | Forensic Integrity Audit | Independent verification by `teamwork_auditor` confirming genuine logic and zero cheating | M4 | project_pattern |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| TRACK_E2E | E2E Testing & Benchmark Suite | Opaque-box 4-tier test harness + Criterion & Macro benchmark suite | None | DONE |
| M1 | Protocol Correctness & Linter Baseline | Facebook passthrough fix, WebSocket framing, multi-value headers, DNS single-flight, graceful shutdown, clippy & fmt | None | DONE |
| M2 | Performance Engine & Zero-Copy Pipeline | Async CA signing (`spawn_blocking`), `bytes::Bytes` buffers, HeaderMap zero-copy, vectorized DB flush, release profile + mimalloc | M1 | DONE |
| M3 | Architecture Decoupling & Clean Layering | Decouple vendor logic from core (`proxy.rs`, `graphql.rs`, `stealth.rs`), encapsulate SDK infrastructure types, auto-docs in `docs/` | M2 | DONE |
| M4 | Final Integration, E2E Pass & Hardening | Pass 100% E2E tests, measure benchmark delta, Tier 5 adversarial stress testing, Forensic Integrity Audit | TRACK_E2E, M3 | DONE |

---

## Interface Contracts

### 1. External CLI & Config Compatibility
- Binary: `proxify-server`
- CLI Flags:
  - `--port`, `-p`: Proxy listen port (default: 8080)
  - `--dash-port`: Dashboard listen port (default: 8081)
  - `--host`: Proxy listen host (default: 0.0.0.0)
- Config: Environment variables (`DATABASE_URL`, `PROXY_PORT`, `DASH_PORT`) and root `config.json` compatibility.

### 2. Public REST & WebSocket Dashboard APIs
- `GET /api/requests`: Paginated list of intercepted requests.
- `GET /api/requests/:id`: Request details including payload.
- `GET /api/stats`: Real-time throughput, active connections, total requests.
- `WS /ws/telemetry`: Real-time streaming events of new requests and status updates.

### 3. Public SDK Trait Boundaries (`proxify-sdk`)
- `RequestObserver`: `async fn on_request(&self, req: &mut FlowRequest) -> Result<(), ExtensionError>`
- `ResponseMutator`: `async fn on_response(&self, req: &FlowRequest, resp: &mut FlowResponse) -> Result<(), ExtensionError>`
- `Extension`: Lifecycle trait. `async fn on_init(...)` with backward-compatible alias.

### 4. Database Schema
- Table `requests`: id, method, host, path, status, duration_ms, request_size, response_size, created_at.
- Table `raw_payloads`: request_id, request_body, response_body.

---

## Code Layout
```
c:\Users\Administrator\Desktop\MyAim\Proxify\
├── Cargo.toml                      # Workspace manifest and compiler profiles
├── benches/                        # Microbenchmarks (Criterion)
│   ├── router_bench.rs
│   ├── header_bench.rs
│   └── cert_bench.rs
├── crates/
│   ├── proxify-core/               # Infrastructure & Data Plane
│   │   ├── src/
│   │   │   ├── proxy.rs            # Forwarding, TLS MITM, WebSocket upgrade
│   │   │   ├── ca.rs               # Dynamic certificate signing & caching
│   │   │   ├── router.rs           # Radix trie routing & stream rule resolution
│   │   │   ├── storage.rs          # Postgres buffer queue & batch flush
│   │   │   ├── eventbus.rs         # Async event publication
│   │   │   ├── stealth.rs          # Anti-fingerprint header normalization
│   │   │   └── graphql.rs          # Generic GraphQL request parser
│   ├── proxify-sdk/                # Domain & Plugin Contracts
│   │   ├── src/lib.rs              # FlowRequest, FlowResponse, Extension traits
│   ├── proxify-server/             # Presentation & Host Entrypoint
│   │   ├── src/
│   │   │   ├── main.rs             # CLI args, graceful shutdown, server startup
│   │   │   └── dashboard.rs        # Axum REST & WebSocket telemetry handlers
│   ├── ext-youtube/                # Application Extension
│   ├── ext-facebook/               # Application Extension
│   └── ext-zalo/                   # Application Extension
├── tests/                          # Integration & Opaque-box E2E test suites
│   ├── e2e_proxy_tests.rs
│   ├── e2e_websocket_tests.rs
│   └── e2e_extension_tests.rs
└── docs/                           # Vietnamese architecture & module documentation
```
