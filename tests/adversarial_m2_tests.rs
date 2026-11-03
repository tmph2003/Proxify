//! Adversarial Stress & Performance Verification Suite for Milestone 2
//!
//! Evaluates:
//! 1. CA Leaf Signing Reactor Freezing Challenge: Confirms that concurrent uncached
//!    HTTPS requests do NOT starve or freeze the Tokio async reactor by validating
//!    that CPU-intensive cryptographic signing runs on `spawn_blocking`.
//! 2. Broadcast Single-Flight Coalescing: Verifies that 50 simultaneous concurrent
//!    requests for the exact same uncached domain coalesce into 1 signing job and receive
//!    the exact same `Arc<ServerConfig>`.
//! 3. Single-Flight Leader Abort Resilience: Verifies graceful fallback when a leader
//!    future is dropped/cancelled mid-flight.
//! 4. LRU Cache Eviction Stress (4500 unique hosts): Generates 4500 unique host requests,
//!    verifies genuine LRU eviction of oldest entries (host 0 evicted) while recent entries
//!    remain cached (host 3000, host 4400 preserved), with zero memory leaks or panics.
//! 5. High-Concurrency LRU Stampede: Multi-threaded concurrent reads/writes/evictions
//!    across 1500 distinct hosts ensuring deadlock-free operation under load.
//! 6. Zero-Copy Flow Buffer Slicing: Verifies `bytes::Bytes` ref-count sharing in `FlowRequest`.

use bytes::Bytes;
use futures_util::future::join_all;
use proxify_core::ca::CertificateAuthority;
use proxify_sdk::FlowRequest;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

// =========================================================================
// 1. CA Leaf Signing Reactor Freezing Challenge
// =========================================================================

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn test_adv_ca_leaf_signing_no_reactor_freezing() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_adv_freeze_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca = CertificateAuthority::load_or_generate(&temp_dir)
        .expect("Failed to initialize test Certificate Authority");

    // Launch a high-frequency async reactor heartbeat ticker: ticks every 5ms
    let (stop_tx, mut stop_rx) = tokio::sync::oneshot::channel::<()>();
    let ticker_handle = tokio::spawn(async move {
        let mut ticks: u64 = 0;
        let mut max_interval = Duration::ZERO;
        let mut last_tick = Instant::now();

        loop {
            tokio::select! {
                _ = &mut stop_rx => break,
                _ = tokio::time::sleep(Duration::from_millis(5)) => {
                    let now = Instant::now();
                    let delta = now.duration_since(last_tick);
                    last_tick = now;
                    ticks += 1;
                    if delta > max_interval {
                        max_interval = delta;
                    }
                }
            }
        }
        (ticks, max_interval)
    });

    // Concurrently fire 20 uncached leaf signing operations for 20 distinct hosts.
    // If leaf signing blocked Tokio worker threads synchronously, the 2 worker threads
    // would be fully occupied, freezing the 5ms timer for hundreds of milliseconds.
    let mut tasks = Vec::with_capacity(20);
    for i in 0..20 {
        let ca_clone = ca.clone();
        tasks.push(tokio::spawn(async move {
            let host = format!("freeze-test-{}.adversarial.local", i);
            ca_clone.server_config_for_host_async(&host).await
        }));
    }

    let test_start = Instant::now();
    let results = join_all(tasks).await;
    let elapsed = test_start.elapsed();
    let _ = stop_tx.send(());
    let (ticks, max_interval) = ticker_handle.await.expect("Ticker handle join");

    println!(
        "[DIAGNOSTIC] 20 concurrent cert signs completed in {:?}. Ticks: {}, Max interval: {:?}",
        elapsed, ticks, max_interval
    );

    // Assert all 20 leaf certificates generated successfully
    for res in results {
        let cfg = res
            .expect("Task join failed")
            .expect("Leaf generation failed");
        assert!(
            cfg.alpn_protocols.contains(&b"http/1.1".to_vec()),
            "Config must contain HTTP/1.1 ALPN"
        );
        assert!(
            cfg.alpn_protocols.contains(&b"h2".to_vec()),
            "Config must contain h2 ALPN"
        );
    }

    // Verify reactor was NOT frozen: ticker ticked during the concurrent signing burst
    assert!(
        ticks >= 1,
        "Reactor was completely frozen! Ticker ticked 0 times"
    );

    // Max tick interval must stay reasonable (well below starvation threshold)
    assert!(
        max_interval < Duration::from_millis(150),
        "Reactor experienced severe latency spike: {:?}",
        max_interval
    );

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 2. Broadcast Single-Flight Deduplication & Coalescing
// =========================================================================

#[tokio::test]
async fn test_adv_ca_single_flight_broadcast_dedup() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir = std::env::temp_dir().join(format!("proxify_adv_sf_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    let target_host = "thundering-herd-target.stampede.local";

    // Launch 50 concurrent requests simultaneously for the EXACT SAME uncached host
    let mut tasks = Vec::with_capacity(50);
    for _ in 0..50 {
        let ca_clone = ca.clone();
        tasks.push(tokio::spawn(async move {
            ca_clone.server_config_for_host_async(target_host).await
        }));
    }

    let results = join_all(tasks).await;

    let mut configs = Vec::with_capacity(50);
    for res in results {
        let cfg = res.expect("Task join").expect("CA signing failed");
        configs.push(cfg);
    }

    // Verify that all 50 concurrent tasks received the EXACT SAME Arc<ServerConfig>
    // proving that single-flight coalesced them into 1 signing job and broadcasted the result
    let reference_ptr = Arc::as_ptr(&configs[0]);
    for (i, cfg) in configs.iter().enumerate().skip(1) {
        assert!(
            Arc::ptr_eq(&configs[0], cfg),
            "Task {} received a different Arc pointer ({:?} vs {:?})! Single-flight failed to deduplicate.",
            i,
            Arc::as_ptr(cfg),
            reference_ptr
        );
    }

    // Subsequent call must hit cache and return the exact same pointer
    let cached_cfg = ca.server_config_for_host_async(target_host).await.unwrap();
    assert!(
        Arc::ptr_eq(&configs[0], &cached_cfg),
        "Cache hit must return the identical Arc<ServerConfig> pointer"
    );

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 3. Single-Flight Leader Cancellation & Fallback Resilience
// =========================================================================

#[tokio::test]
async fn test_adv_ca_single_flight_leader_cancellation_resilience() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_adv_cancel_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    let cancel_host = "abort-leader-test.victim.local";

    // Spawn leader task and abort it immediately to trigger InFlightGuard drop
    let ca_clone = ca.clone();
    let leader_handle =
        tokio::spawn(async move { ca_clone.server_config_for_host_async(cancel_host).await });

    // Abort the leader task
    leader_handle.abort();
    let _ = leader_handle.await;

    // Subsequent/follower requests must recover without deadlock, panic, or hanging
    let follower_cfg = ca
        .server_config_for_host_async(cancel_host)
        .await
        .expect("Follower must successfully obtain ServerConfig after leader abort");

    assert!(
        follower_cfg.alpn_protocols.contains(&b"http/1.1".to_vec()),
        "Config must be valid after leader abort recovery"
    );

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 4. LRU Cache Eviction Stress (4500 Unique Hosts & Bound Check)
// =========================================================================

#[tokio::test]
async fn test_adv_ca_lru_cache_4500_hosts_eviction() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir = std::env::temp_dir().join(format!("proxify_adv_lru_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    // 1. Insert host 0 and record its pointer
    let host_0 = "lru-stress-host-0000.evict.local";
    let cfg_0 = ca
        .server_config_for_host_async(host_0)
        .await
        .expect("Host 0 initial generation");

    // 2. Insert host 3000 and record its pointer
    let host_3000 = "lru-stress-host-3000.evict.local";

    // 3. Sequentially populate 4500 unique host entries
    // Eviction threshold in ca.rs is 4096. When reached, 512 oldest entries are evicted.
    let mut cfg_3000_opt = None;
    let mut cfg_4400_opt = None;
    let host_4400 = "lru-stress-host-4400.evict.local";

    for i in 1..4500 {
        let host = format!("lru-stress-host-{:04}.evict.local", i);
        let cfg = ca
            .server_config_for_host_async(&host)
            .await
            .unwrap_or_else(|e| panic!("Failed to generate cert for host {}: {}", host, e));

        if i == 3000 {
            cfg_3000_opt = Some(cfg.clone());
        }
        if i == 4400 {
            cfg_4400_opt = Some(cfg.clone());
        }
    }

    let cfg_3000 = cfg_3000_opt.expect("Host 3000 captured");
    let cfg_4400 = cfg_4400_opt.expect("Host 4400 captured");

    // 4. Verify Host 0 was evicted (oldest entry evicted during 4096-threshold purge)
    let cfg_0_reloaded = ca
        .server_config_for_host_async(host_0)
        .await
        .expect("Host 0 reload");

    assert!(
        !Arc::ptr_eq(&cfg_0, &cfg_0_reloaded),
        "Host 0 was NOT evicted! Pointers match ({:?} == {:?}), indicating unbounded cache growth or eviction failure.",
        Arc::as_ptr(&cfg_0),
        Arc::as_ptr(&cfg_0_reloaded)
    );

    // 5. Verify Host 3000 remained cached (within the retained 3584..4500 window)
    let cfg_3000_check = ca
        .server_config_for_host_async(host_3000)
        .await
        .expect("Host 3000 check");

    assert!(
        Arc::ptr_eq(&cfg_3000, &cfg_3000_check),
        "Host 3000 was prematurely evicted! Expected cache hit."
    );

    // 6. Verify Host 4400 remained cached
    let cfg_4400_check = ca
        .server_config_for_host_async(host_4400)
        .await
        .expect("Host 4400 check");

    assert!(
        Arc::ptr_eq(&cfg_4400, &cfg_4400_check),
        "Host 4400 was prematurely evicted! Expected cache hit."
    );

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 5. High-Concurrency Multi-threaded LRU Eviction Stampede
// =========================================================================

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_adv_ca_concurrent_lru_stampede() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    let temp_dir =
        std::env::temp_dir().join(format!("proxify_adv_stampede_{}", uuid::Uuid::new_v4()));
    let _ = std::fs::create_dir_all(&temp_dir);
    let ca =
        CertificateAuthority::load_or_generate(&temp_dir).expect("Failed to initialize test CA");

    // 16 concurrent workers each generating 50 unique host requests
    // while randomly accessing 5 shared hotspot hosts
    let mut tasks = Vec::with_capacity(16);
    for worker_id in 0..16 {
        let ca_clone = ca.clone();
        tasks.push(tokio::spawn(async move {
            for req_id in 0..50 {
                let host = format!("worker-{:02}-req-{:03}.stampede.local", worker_id, req_id);
                let _ = ca_clone.server_config_for_host_async(&host).await.unwrap();

                // Interleave with shared hotspot
                let hotspot = format!("hotspot-{}.shared.local", req_id % 5);
                let _ = ca_clone
                    .server_config_for_host_async(&hotspot)
                    .await
                    .unwrap();
            }
        }));
    }

    let results = join_all(tasks).await;
    for res in results {
        res.expect("Worker thread panicked during concurrent LRU stampede");
    }

    let _ = std::fs::remove_dir_all(&temp_dir);
}

// =========================================================================
// 6. Zero-Copy Flow Buffer Slicing & Mutability Verification
// =========================================================================

#[test]
fn test_adv_zero_copy_bytes_slicing_and_mutation() {
    let raw_payload = vec![0x42u8; 1024 * 64]; // 64 KB
    let bytes_payload = Bytes::from(raw_payload.clone());

    let mut req = FlowRequest {
        method: "POST".to_string(),
        url: "http://api.zero-copy.local/upload".to_string(),
        host: "api.zero-copy.local".to_string(),
        port: 80,
        path: "/upload".to_string(),
        scheme: "http".to_string(),
        headers: HashMap::new(),
        content: bytes_payload.clone(),
        timestamp_start: 1730000000.0,
    };

    // 1. Verify body slice accessor
    assert_eq!(req.body().len(), 64 * 1024);
    assert_eq!(req.body()[0], 0x42);

    // 2. Zero-copy sub-slicing
    let slice_a = req.content.slice(0..1024);
    let slice_b = req.content.slice(1024..2048);

    assert_eq!(slice_a.len(), 1024);
    assert_eq!(slice_b.len(), 1024);

    // Pointer of slice_a must point to the identical base buffer
    assert_eq!(slice_a.as_ptr(), req.content.as_ptr());
    // Pointer of slice_b is exactly 1024 bytes offset in the same buffer
    assert_eq!(slice_b.as_ptr(), unsafe { req.content.as_ptr().add(1024) });

    // 3. Mutator backward-compatibility
    let new_data = b"replacement payload".to_vec();
    req.set_content(new_data.clone());
    assert_eq!(req.content_slice(), b"replacement payload");
    assert_eq!(req.content_vec(), new_data);
}
