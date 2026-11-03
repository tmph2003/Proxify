use ext_facebook::FacebookExtension;
use ext_youtube::YouTubeExtension;
use ext_zalo::ZaloExtension;
use proxify_core::ca::CertificateAuthority;
use proxify_core::dashboard::{build_dashboard_router, DashboardState};
use proxify_core::eventbus::{AsyncEventBus, BackgroundWorker};
use proxify_core::proxy::MitmProxyServer;
use proxify_core::router::ProxyRouter;
use proxify_core::storage::{create_pg_pool, init_core_schemas, RequestStorage};
use proxify_sdk::{BaseExtension, ExtensionContext};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tracing::{error, info};

#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

#[tokio::main]
async fn main() {
    let _ = rustls::crypto::ring::default_provider().install_default();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    info!("=========================================================");
    info!("   Proxify v2.0 (Pure Rust Core + Extension Workspace)   ");
    info!("=========================================================");

    let database_url = std::env::var("DATABASE_URL")
        .or_else(|_| std::env::var("DB_DSN"))
        .unwrap_or_else(|_| {
            "postgresql://proxify_user:proxify_pass@db:5432/proxify_db".to_string()
        });

    let pool = create_pg_pool(&database_url, 24).expect("Failed to create PostgreSQL pool");

    for attempt in 1..=15 {
        match init_core_schemas(&pool).await {
            Ok(_) => break,
            Err(e) => {
                error!(
                    "[Startup] Waiting for PostgreSQL (attempt {}/15): {}",
                    attempt, e
                );
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
            }
        }
    }

    let (event_bus, ws_tx) = AsyncEventBus::new(pool.clone(), 4096);
    let bg_worker = Arc::new(BackgroundWorker::new(pool.clone(), 50, 500));
    let router = Arc::new(ProxyRouter::new());
    let storage = RequestStorage::with_event_bus(pool.clone(), Some(event_bus.clone()));

    let private_ext_root = std::env::var("PROXIFY_EXTENSIONS_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/app/private/extensions"));

    let mut ext_ctx = ExtensionContext::new(event_bus.clone(), pool.clone());

    let extensions: Vec<Box<dyn BaseExtension>> = vec![
        Box::new(YouTubeExtension::new()),
        Box::new(ZaloExtension::new(private_ext_root.join("zalo"))),
        Box::new(FacebookExtension::new(private_ext_root.join("facebook"))),
    ];

    for ext in &extensions {
        match ext.on_init(&mut ext_ctx).await {
            Ok(_) => info!("[ExtensionLoader] Loaded extension: {}", ext.name()),
            Err(e) => error!(
                "[ExtensionLoader] Failed to initialize extension {}: {}",
                ext.name(),
                e
            ),
        }
    }

    for (domain, obs) in ext_ctx.observers {
        router.register_observer(&domain, obs);
    }
    for (domain, mutator) in ext_ctx.mutators {
        router.register_mutator(&domain, mutator);
    }
    for domain in ext_ctx.stream_rules {
        router.register_stream_rule(&domain);
    }
    for (domain, prefix) in ext_ctx.stream_path_rules {
        router.register_stream_path_rule(&domain, &prefix);
    }
    for (domain, pattern) in ext_ctx.stream_exclusions {
        router.register_stream_exclusion(&domain, &pattern);
    }
    for sig in ext_ctx.soft_block_signatures {
        proxify_core::stealth::register_soft_block_signature(&sig);
    }
    if let Ok(ignore_env) = std::env::var("IGNORE_HOSTS") {
        for host in ignore_env.split(',') {
            let trimmed = host.trim();
            if !trimmed.is_empty() {
                router.register_stream_rule(trimmed);
            }
        }
    }
    for filter in ext_ctx.record_filters {
        router.register_record_filter(filter);
    }
    for (topic, handler) in ext_ctx.topic_handlers {
        bg_worker.register_handler(&topic, handler);
    }

    bg_worker.start();

    let frontend_dir = std::env::var("PROXIFY_FRONTEND_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/app/backend/frontend"));

    let dash_state = DashboardState {
        storage: storage.clone(),
        ws_tx,
        ui_pages: Arc::new(ext_ctx.ui_pages),
        frontend_dir,
    };

    let app_router = build_dashboard_router(dash_state, ext_ctx.sub_routers);

    let ca_dir = std::env::var("PROXIFY_CA_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root/.mitmproxy"));

    let ca = CertificateAuthority::load_or_generate(&ca_dir)
        .expect("Failed to initialize Certificate Authority");

    let proxy_port: u16 = std::env::var("PROXY_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8080);
    let dash_port: u16 = std::env::var("DASHBOARD_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8888);

    let proxy_addr = SocketAddr::from(([0, 0, 0, 0], proxy_port));
    let dash_addr = SocketAddr::from(([0, 0, 0, 0], dash_port));

    let storage_for_shutdown = storage.clone();
    let mitm_server = MitmProxyServer::new(ca, router, storage, event_bus);

    let proxy_handle = tokio::spawn(async move {
        if let Err(e) = mitm_server.run(proxy_addr).await {
            error!("[ProxyServer] Fatal error: {}", e);
        }
    });

    let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);

    let dash_handle = tokio::spawn(async move {
        info!(
            "[Dashboard] Web Dashboard & API listening on http://{}",
            dash_addr
        );
        let listener = tokio::net::TcpListener::bind(dash_addr)
            .await
            .expect("Failed to bind Dashboard port");
        let server = axum::serve(listener, app_router);
        let graceful = server.with_graceful_shutdown(async move {
            let _ = shutdown_rx.wait_for(|&v| v).await;
        });
        if let Err(e) = graceful.await {
            error!("[Dashboard] Fatal error: {}", e);
        }
    });

    info!(
        "[System] Proxify proxy running on http://{} and dashboard on http://{}",
        proxy_addr, dash_addr
    );
    info!("[System] Press Ctrl+C to initiate graceful shutdown.");

    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            info!("[System] Received Ctrl+C shutdown signal.");
        }
        res = proxy_handle => {
            if let Err(e) = res {
                error!("[System] Proxy server task failed: {}", e);
            }
        }
        res = dash_handle => {
            if let Err(e) = res {
                error!("[System] Dashboard server task failed: {}", e);
            }
        }
    }

    let _ = shutdown_tx.send(true);
    info!("[System] Initiating graceful shutdown: flushing pending storage records...");
    storage_for_shutdown.shutdown().await;
    info!("[System] Proxify stopped successfully.");
}
