# Proxify v2.0 (Rust) — E2E Test & Benchmark Infrastructure Specification (`TEST_INFRA.md`)

## 1. Testing Philosophy & Architecture

The Proxify test infrastructure follows an **opaque-box, requirement-driven, and progressively testable** methodology:

### 1.1 Opaque-Box Black-Box Principle
- Tests interact with the proxy exclusively across standard network protocols (HTTP/1.1, TLS CONNECT, WebSocket 101 Switching Protocols).
- No test monkey-patches internal functions or asserts on private struct state.
- All verification uses observable behavior: HTTP status codes, exact header retention, payload hash/integrity, WebSocket echo frames, and synthetic error responses.

### 1.2 Requirement-Driven & Authoritative Expected Outputs
Every test has an authoritative expected output derived from network RFCs and `PROJECT.md` contracts:
- **RFC 7230 / RFC 7231**: Standard HTTP/1.1 method semantics, status code propagation, and header forwarding.
- **RFC 2817 / RFC 5246**: HTTP CONNECT tunneling and TLS MITM interception with dynamic X.509 certificate generation.
- **RFC 6455**: WebSocket upgrade handshake (`Sec-WebSocket-Accept = Base64(SHA1(Key + GUID))`) and bi-directional frame streaming.
- **Multi-Value Header Specification**: Preservation of multiple `Set-Cookie` lines without collision.
- **Extension Contracts**: Synthetic `204 No Content` for blocked ad networks; CSP nonce preservation for anti-AFK scripts; CQRS topic dispatching.

### 1.3 Progressive Testability & Isolation
- Each test runs against **isolated ephemeral ports** (`127.0.0.1:0`) and ephemeral directories.
- Zero dependency on external running databases: storage persistence is mocked or decoupled during transport layer tests.
- Zero inter-test state leakage: independent instances of `TestProxyServer` and mock upstreams are created per test.

---

## 2. 4-Tier Test Suite Structure

The test suite is organized into 4 distinct functional tiers spanning 20+ dedicated integration test cases:

```
tests/
├── e2e_proxy_tests.rs       # Tier 1 (7 tests) + Tier 2 (8 tests) = 15 tests
├── e2e_websocket_tests.rs   # Tier 3 (5 tests)
└── e2e_extension_tests.rs   # Tier 4 (7 tests)
```

### Tier 1: Core Protocol & Baseline Forwarding
| Test Function | Description | Verification Method |
|---|---|---|
| `test_tier1_http11_simple_get_forwarding` | Basic HTTP/1.1 GET request forwarding | Upstream receives request; client gets 200 OK + payload |
| `test_tier1_http11_post_with_body_and_headers` | HTTP POST forwarding with headers and body | Payload and `X-Client-Trace` header validated at upstream |
| `test_tier1_query_params_and_url_preservation` | Query string preservation | Deep queries (`?query=rust+proxy&page=3`) intact |
| `test_tier1_status_code_propagation` | Upstream error status code propagation | 400 Bad Request, 404 Not Found, 500 Internal Error |
| `test_tier1_keep_alive_connection_reuse` | Single TCP connection pipelining | 3 sequential requests over one keep-alive socket |
| `test_tier1_static_stream_fastpath` | Fast-path streaming for `.png`, `.css`, `.js` | Direct streaming via stream client without RAM buffering |
| `test_tier1_domain_stream_rule` | Domain stream rules in `ProxyRouter` | `should_stream` resolution for exact and subdomains |

### Tier 2: Advanced Protocols & Transport Edge Cases
| Test Function | Description | Verification Method |
|---|---|---|
| `test_tier2_tls_mitm_connect_interception` | HTTPS CONNECT handshake & dynamic leaf CA signing | Client validates leaf cert against proxy CA, sends TLS GET |
| `test_tier2_multi_value_set_cookie_preservation` | Retention of multiple `Set-Cookie` headers | 3 distinct cookies preserved without overwriting |
| `test_tier2_chunked_transfer_encoding` | Upstream chunked stream handling | Complete body reassembled and delivered without truncation |
| `test_tier2_large_payload_streaming` | High-volume payload streaming (2 MB) | Byte-for-byte stream integrity verification |
| `test_tier2_gzip_decompression_handling` | Gzip decompress in proxy data plane | `Content-Encoding: gzip` decoded for flow inspection |
| `test_tier2_upstream_connection_failure_502` | Unreachable upstream target | Immediate `502 Bad Gateway` response |
| `test_tier2_tls_passthrough_whitelisted_domain` | Passthrough for whitelisted domains | Raw TCP tunnel established without TLS decryption |

### Tier 3: Stateful Streaming & WebSocket Bi-directional Piping
| Test Function | Description | Verification Method |
|---|---|---|
| `test_tier3_websocket_upgrade_handshake` | HTTP/1.1 101 Switching Protocols upgrade | `Upgrade: websocket` & RFC 6455 `Sec-WebSocket-Accept` |
| `test_tier3_websocket_bidirectional_frame_piping` | Bi-directional frame relay across proxy tunnel | Client payload echoed back through proxy |
| `test_tier3_websocket_multiframe_streaming` | High-frequency multi-frame message transfer | 5 sequential frames delivered and echoed in order |
| `test_tier3_websocket_segmented_101_handshake` | Fragmented TCP packets during 101 upgrade | Proxy handles segmented headers without stream hang |
| `test_tier3_websocket_graceful_close` | Clean WebSocket connection termination | Clean half-close shutdown without socket leak |

### Tier 4: Application Extensions & Interceptors
| Test Function | Description | Verification Method |
|---|---|---|
| `test_tier4_youtube_adblock_request_interception` | YouTube AdBlock synthetic response | `204 No Content` with CORS headers returned immediately |
| `test_tier4_youtube_json_ad_stripping_and_anti_afk` | Innertube JSON ad stripping & lact neutralize | Ad placements removed; `lactThresholdMs` reset |
| `test_tier4_youtube_anti_afk_watchdog_injection` | HTML watch page watchdog script injection | Script injected with matching CSP nonce |
| `test_tier4_youtube_record_filter` | Media chunk and noise filtering | Video playback & ad requests dropped from recording |
| `test_tier4_facebook_graphql_observer_interception` | Facebook `/api/graphql` interception | Observer captures payload and dispatches CQRS event |
| `test_tier4_radix_trie_domain_routing_hierarchy` | Exact vs wildcard vs global domain dispatch | Trie node traversal matches expected observer sets |
| `test_tier4_custom_mutator_chain_transformation` | Sequential mutator pipeline execution | Headers injected and body rewritten in-flight |

---

## 3. Benchmark Suite Specification

### 3.1 Criterion Microbenchmarks (`benches/proxy_micro_benches.rs`)
Criterion benchmark suite measuring low-level nanosecond/microsecond bottlenecks:
1. **`ProxyRouter` Domain Resolution**:
   - `resolve_exact_match`: Exact hostname trie lookup (`chat.zalo.me`).
   - `resolve_wildcard_match`: Multi-label wildcard lookup (`sub.music.youtube.com`).
   - `resolve_unmatched_miss`: Non-matching domain miss penalty.
   - `should_stream_check`: Stream domain suffix resolution.
2. **`HeaderProcessing` Conversion**:
   - `convert_hyper_to_hashmap`: Conversion of 13-header `HeaderMap` to `HashMap<String, String>`.
   - `parse_multivalue_cookies`: Zero-copy newline splitting of multi-cookie headers.
3. **`CertificateAuthority` Leaf Cache**:
   - `leaf_cache_hit`: Sub-microsecond cache hit retrieval from `DashMap` LRU cache.

### 3.2 Macro Load Benchmark Harness (`scripts/benchmark_proxy.py` & `scripts/bench.sh`)
- Measures end-to-end system throughput under load:
  - Throughput in Requests Per Second (QPS).
  - Latency percentiles: Min, Average, p50, p90, p95, p99, Max.
  - Success/Failure rate and status code distribution.
  - Process memory footprint delta (MB).

---

## 4. Execution Commands

### 4.1 Running Integration Tests (Containerized)
```bash
# Run all integration test suites
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_proxy_tests --test e2e_websocket_tests --test e2e_extension_tests

# Run individual test suites
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_proxy_tests
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_websocket_tests
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo test --test e2e_extension_tests
```

### 4.2 Running Microbenchmarks
```bash
# Run Criterion microbenchmarks in container
docker run --rm -v "${PWD}:/workspace" -w /workspace rust:slim-bookworm cargo bench --bench proxy_micro_benches
```

### 4.3 Running Macro Load Test Harness
```bash
# Run macro load benchmark (25 concurrency, 1000 requests)
python3 scripts/benchmark_proxy.py --requests 1000 --concurrency 25

# Or execute full benchmark suite script
bash scripts/bench.sh
```
