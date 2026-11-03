//! Adversarial Stress & Backward Compatibility Verification Suite for Milestone 3
//!
//! Evaluates:
//! 1. Stealth Dynamic Soft-Block Detection:
//!    - Accurate matching of core signatures (429, 403, 401, "Temporarily Blocked", etc.).
//!    - Accurate matching of ext-facebook custom signatures ("1357001", "is_checkpoint", etc.).
//! 2. False-Positive Immunity:
//!    - Verifies non-checkpoint error codes ("error":0, "error":100, "is_checkpoint":false)
//!      are never false-positived.
//! 3. High-Concurrency Signature Registration & Inspection Stampede:
//!    - 50 concurrent tasks performing simultaneous registrations and inspections.
//! 4. UTF-8 Multi-Byte Character Boundary Slicing Stress:
//!    - Stresses the 2000-byte chunk slice boundary with multi-byte UTF-8 sequences.
//! 5. SDK Backward Compatibility:
//!    - Verifies BaseExtension `on_Init` deprecated lifecycle execution.
//!    - Verifies ExtensionContext accessor and registration encapsulation.

use async_trait::async_trait;
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use proxify_core::stealth::StealthSessionManager;
use proxify_sdk::{BaseExtension, EventPublisher, ExtensionContext};
use serde_json::Value;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::task::JoinHandle;

struct DummyEventPublisher;
impl EventPublisher for DummyEventPublisher {
    fn publish(&self, _topic: &str, _payload: Value) -> bool {
        true
    }
    fn broadcast_ws(&self, _event_type: &str, _data: Value) {}
}

fn create_dummy_pool() -> Pool {
    let pg_config = deadpool_postgres::tokio_postgres::Config::new();
    let mgr = Manager::from_config(
        pg_config,
        deadpool_postgres::tokio_postgres::NoTls,
        ManagerConfig {
            recycling_method: RecyclingMethod::Fast,
        },
    );
    Pool::builder(mgr).max_size(1).build().unwrap()
}

// =========================================================================
// 1. Core Soft-Block Detection & False Positive Immunity
// =========================================================================

#[test]
fn test_adv_stealth_core_soft_block_detection() {
    // HTTP Status-based soft blocks
    assert!(StealthSessionManager::is_soft_blocked(429, "").is_some());
    assert!(StealthSessionManager::is_soft_blocked(403, "").is_some());
    assert!(StealthSessionManager::is_soft_blocked(401, "").is_some());

    // Core body signatures
    let res = StealthSessionManager::is_soft_blocked(
        200,
        "Your account is Temporarily Blocked due to suspicious activity.",
    );
    assert!(res.is_some());
    assert!(res.unwrap().contains("Temporarily Blocked"));

    let res = StealthSessionManager::is_soft_blocked(
        200,
        "Notice: You’re Temporarily Blocked from performing this action.",
    );
    assert!(res.is_some());
    let matched = res.unwrap();
    assert!(matched.contains("You\u{2019}re Temporarily Blocked"));

    let res = StealthSessionManager::is_soft_blocked(
        200,
        "Please perform a security check to verify your identity.",
    );
    assert!(res.is_some());
    assert!(res.unwrap().contains("security check"));
}

#[test]
fn test_adv_stealth_false_positive_rejection() {
    // Normal 200 OK responses
    assert!(StealthSessionManager::is_soft_blocked(200, "").is_none());
    assert!(StealthSessionManager::is_soft_blocked(
        200,
        "{\"data\": {\"user\": {\"id\": \"1000\"}}}"
    )
    .is_none());
    assert!(StealthSessionManager::is_soft_blocked(200, "{\"status\": \"success\"}").is_none());

    // Non-checkpoint errors
    assert!(StealthSessionManager::is_soft_blocked(
        200,
        "{\"error\": 0, \"message\": \"Success\"}"
    )
    .is_none());
    assert!(StealthSessionManager::is_soft_blocked(
        200,
        "{\"error\": 100, \"message\": \"Invalid query parameter\"}"
    )
    .is_none());
    assert!(StealthSessionManager::is_soft_blocked(
        200,
        "{\"error\": 1357000, \"message\": \"Unrelated error\"}"
    )
    .is_none());
    assert!(StealthSessionManager::is_soft_blocked(
        200,
        "{\"error\": 1357002, \"message\": \"Unrelated error\"}"
    )
    .is_none());

    // Checkpoint false-positive tests
    assert!(StealthSessionManager::is_soft_blocked(200, "{\"is_checkpoint\": false}").is_none());
    assert!(
        StealthSessionManager::is_soft_blocked(200, "{\"action\": \"checkpoint_verified\"}")
            .is_none()
    );

    // Non-soft-block HTTP status codes
    assert!(StealthSessionManager::is_soft_blocked(204, "").is_none());
    assert!(StealthSessionManager::is_soft_blocked(302, "").is_none());
    assert!(StealthSessionManager::is_soft_blocked(404, "Page Not Found").is_none());
    assert!(StealthSessionManager::is_soft_blocked(500, "Internal Server Error").is_none());
    assert!(StealthSessionManager::is_soft_blocked(502, "Bad Gateway").is_none());
}

// =========================================================================
// 2. Ext-Facebook Custom Soft-Block Signature Injection & Detection
// =========================================================================

#[test]
fn test_adv_stealth_ext_facebook_signatures() {
    const FB_CHECKPOINT_SIGNATURES: &[&str] = &[
        "\"error\":1357001",
        "\"error\":1357004",
        "\"error\":1357031",
        "\"error\":1404002",
        "\"error\":1675030",
        "\"error\":1675012",
        "\"is_checkpoint\":true",
        "/checkpoint/block",
    ];

    for sig in FB_CHECKPOINT_SIGNATURES {
        StealthSessionManager::register_soft_block_signature(sig);
    }

    // Verify detection of each signature
    for sig in FB_CHECKPOINT_SIGNATURES {
        let sample_payload = format!("{{\"response\": \"failed\", \"details\": {}}}", sig);
        let match_res = StealthSessionManager::is_soft_blocked(200, &sample_payload);
        assert!(
            match_res.is_some(),
            "Signature '{}' failed to be detected in payload: {}",
            sig,
            sample_payload
        );
        let reason = match_res.unwrap();
        assert!(
            reason.contains(sig),
            "Expected reason to mention signature '{}', got '{}'",
            sig,
            reason
        );
    }
}

// =========================================================================
// 3. High-Concurrency Registration and Inspection Stress
// =========================================================================

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_adv_stealth_high_concurrency_stampede() {
    let mut handles: Vec<JoinHandle<()>> = Vec::new();

    // 25 tasks concurrently registering custom signatures (including duplicates & whitespace)
    for worker_id in 0..25 {
        handles.push(tokio::spawn(async move {
            for i in 0..100 {
                let sig = format!("custom_block_worker_{}_{}", worker_id % 5, i % 10);
                StealthSessionManager::register_soft_block_signature(&sig);
                StealthSessionManager::register_soft_block_signature(&format!("  {}  ", sig));
                StealthSessionManager::register_soft_block_signature(""); // should be ignored
                StealthSessionManager::register_soft_block_signature("   "); // should be ignored
            }
        }));
    }

    // 25 tasks concurrently performing inspections with mixed payloads
    for worker_id in 0..25 {
        handles.push(tokio::spawn(async move {
            for i in 0..200 {
                let status = match i % 5 {
                    0 => 200,
                    1 => 429,
                    2 => 403,
                    3 => 401,
                    _ => 500,
                };
                let body = if i % 2 == 0 {
                    format!(
                        "{{\"error\":1357001, \"custom_block_worker_{}_{}\": true}}",
                        worker_id % 5,
                        i % 10
                    )
                } else {
                    format!("{{\"status\":\"normal_traffic_payload_{}\"}}", i)
                };

                let res = StealthSessionManager::is_soft_blocked(status, &body);
                if status == 429 || status == 403 || status == 401 {
                    assert!(res.is_some());
                }
            }
        }));
    }

    for h in handles {
        h.await
            .expect("Task panicked during high concurrency stealth stress");
    }
}

// =========================================================================
// 4. Multi-Byte UTF-8 Boundary Slicing Stress
// =========================================================================

#[test]
fn test_adv_stealth_utf8_boundary_slicing() {
    // Construct a payload where byte 2000 falls right inside a multi-byte UTF-8 character.
    // '🎉' is 4 bytes: [0xF0, 0x9F, 0x8E, 0x89]
    // 1999 ASCII bytes ('a') followed by '🎉' = 2003 bytes total.
    // Slicing at &body[..2000] would split the 4-byte character!
    let mut body = "a".repeat(1999);
    body.push('🎉');
    body.push_str(" {\"error\":1357001}");

    // Test whether is_soft_blocked safely handles or panics on non-ASCII boundary
    let res = std::panic::catch_unwind(|| StealthSessionManager::is_soft_blocked(200, &body));

    // VERIFIED FIX:
    // In crates/proxify-core/src/stealth.rs:
    // check_chunk slices safely at valid UTF-8 character boundaries.
    // When byte 2000 falls in the middle of a multi-byte UTF-8 codepoint (such as Vietnamese or emojis),
    // it will not panic.
    assert!(
        res.is_ok(),
        "Expected is_soft_blocked to safely handle non-ASCII boundary without panicking"
    );
}

// =========================================================================
// 5. SDK Backward Compatibility: BaseExtension on_Init Execution Stress
// =========================================================================

struct MockLegacyExtension {
    initialized: AtomicBool,
}

#[async_trait]
impl BaseExtension for MockLegacyExtension {
    fn name(&self) -> &str {
        "mock_legacy"
    }

    // A modern extension implements on_init
    async fn on_init(&self, context: &mut ExtensionContext) -> Result<(), String> {
        self.initialized.store(true, Ordering::SeqCst);
        context.register_stream_rule("legacy-target.com");
        context.register_soft_block_signature("\"error\":999999");
        Ok(())
    }
}

#[tokio::test]
async fn test_adv_sdk_legacy_calling_on_init() {
    let bus = Arc::new(DummyEventPublisher);
    let pool = create_dummy_pool();
    let mut ctx = ExtensionContext::new(bus, pool);

    let ext = MockLegacyExtension {
        initialized: AtomicBool::new(false),
    };

    // Explicitly call the deprecated on_Init method as a legacy caller would
    #[allow(deprecated)]
    let res = ext.on_Init(&mut ctx).await;

    assert!(res.is_ok(), "Calling on_Init failed: {:?}", res);
    assert!(
        ext.initialized.load(Ordering::SeqCst),
        "on_Init did not execute implementation"
    );
    assert!(ctx
        .stream_rules()
        .contains(&"legacy-target.com".to_string()));
    assert!(ctx
        .soft_block_signatures()
        .contains(&"\"error\":999999".to_string()));
}

struct PureLegacyExtension {
    initialized: AtomicBool,
}

#[async_trait]
impl BaseExtension for PureLegacyExtension {
    fn name(&self) -> &str {
        "pure_legacy"
    }

    // A legacy extension written before M3 only implemented on_Init
    #[allow(deprecated, non_snake_case)]
    async fn on_Init(&self, context: &mut ExtensionContext) -> Result<(), String> {
        self.initialized.store(true, Ordering::SeqCst);
        context.register_stream_rule("pure-legacy.com");
        Ok(())
    }
}

#[tokio::test]
async fn test_adv_sdk_pure_legacy_extension_overriding_on_init() {
    let bus = Arc::new(DummyEventPublisher);
    let pool = create_dummy_pool();
    let mut ctx = ExtensionContext::new(bus, pool);

    let ext = PureLegacyExtension {
        initialized: AtomicBool::new(false),
    };

    // When legacy caller calls on_Init on PureLegacyExtension:
    #[allow(deprecated)]
    let res = ext.on_Init(&mut ctx).await;
    assert!(res.is_ok());
    assert!(ext.initialized.load(Ordering::SeqCst));
    assert!(ctx.stream_rules().contains(&"pure-legacy.com".to_string()));
}

#[tokio::test]
async fn test_adv_sdk_pure_legacy_extension_called_by_modern_host_limitation() {
    let bus = Arc::new(DummyEventPublisher);
    let pool = create_dummy_pool();
    let mut ctx = ExtensionContext::new(bus, pool);

    let ext = PureLegacyExtension {
        initialized: AtomicBool::new(false),
    };

    // When modern host (main.rs:73) calls on_init(&mut ctx):
    let res = ext.on_init(&mut ctx).await;
    assert!(res.is_ok());
    // VERIFIED FIX: BaseExtension provides bidirectional recursion-safe delegation.
    // When modern host calls ext.on_init(&mut ctx), it delegates to on_Init for legacy extensions.
    assert!(
        ext.initialized.load(Ordering::SeqCst),
        "Legacy extension on_Init must be executed by on_init delegation"
    );
    assert!(ctx.stream_rules().contains(&"pure-legacy.com".to_string()));
}

// =========================================================================
// 6. ExtensionContext Encapsulation and Accessors
// =========================================================================

#[test]
fn test_adv_extension_context_encapsulation_api() {
    let bus = Arc::new(DummyEventPublisher);
    let pool = create_dummy_pool();
    let mut ctx = ExtensionContext::new(bus, pool);

    // Verify accessors
    let _ = ctx.db_pool();
    let _ = ctx.event_bus();

    // Verify registration methods
    ctx.register_stream_rule("rule1.com");
    ctx.register_stream_path_rule("rule2.com", "/api/stream");
    ctx.register_stream_exclusion("rule3.com", "bypass");
    ctx.register_soft_block_signature("\"error\":1234");

    assert_eq!(ctx.stream_rules(), &["rule1.com".to_string()]);
    assert_eq!(
        ctx.stream_path_rules(),
        &[("rule2.com".to_string(), "/api/stream".to_string())]
    );
    assert_eq!(
        ctx.stream_exclusions(),
        &[("rule3.com".to_string(), "bypass".to_string())]
    );
    assert_eq!(ctx.soft_block_signatures(), &["\"error\":1234".to_string()]);
}
