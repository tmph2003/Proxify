use deadpool_postgres::Pool;
use parking_lot::RwLock;
use proxify_sdk::{EventPublisher, TopicHandler};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{broadcast, mpsc};
use tracing::{error, info, warn};

#[derive(Debug, Clone)]
pub struct QueuedEvent {
    pub topic: String,
    pub payload: Value,
}

pub struct AsyncEventBus {
    tx: mpsc::Sender<QueuedEvent>,
    ws_tx: broadcast::Sender<String>,
}

impl AsyncEventBus {
    pub fn new(pool: Pool, max_queue_size: usize) -> (Arc<Self>, broadcast::Sender<String>) {
        let (tx, mut rx) = mpsc::channel::<QueuedEvent>(max_queue_size);
        let (ws_tx, _) = broadcast::channel::<String>(2048);
        let ws_tx_clone = ws_tx.clone();

        tokio::spawn(async move {
            let mut batch: Vec<QueuedEvent> = Vec::with_capacity(50);
            let mut interval = tokio::time::interval(Duration::from_millis(500));

            loop {
                tokio::select! {
                    maybe_ev = rx.recv() => {
                        match maybe_ev {
                            Some(ev) => {
                                batch.push(ev);
                                while batch.len() < 50 {
                                    match rx.try_recv() {
                                        Ok(next_ev) => batch.push(next_ev),
                                        Err(_) => break,
                                    }
                                }
                                Self::flush_batch(&pool, &mut batch).await;
                            }
                            None => {
                                if !batch.is_empty() {
                                    Self::flush_batch(&pool, &mut batch).await;
                                }
                                break;
                            }
                        }
                    }
                    _ = interval.tick() => {
                        if !batch.is_empty() {
                            Self::flush_batch(&pool, &mut batch).await;
                        }
                    }
                }
            }
        });

        (Arc::new(Self { tx, ws_tx }), ws_tx_clone)
    }

    async fn flush_batch(pool: &Pool, batch: &mut Vec<QueuedEvent>) {
        if batch.is_empty() {
            return;
        }
        let events: Vec<QueuedEvent> = std::mem::take(batch);
        let mut client = match pool.get().await {
            Ok(c) => c,
            Err(e) => {
                error!(
                    "[EventBus] Failed to get DB connection for batch flush: {}",
                    e
                );
                return;
            }
        };

        let tx = match client.transaction().await {
            Ok(t) => t,
            Err(e) => {
                error!(
                    "[EventBus] Failed to begin transaction for batch flush: {}",
                    e
                );
                return;
            }
        };

        for ev in events {
            let payload_str =
                serde_json::to_string(&ev.payload).unwrap_or_else(|_| "{}".to_string());
            if let Err(e) = tx
                .execute(
                    "INSERT INTO core.raw_payloads (topic, raw_data, processed) VALUES ($1, $2::text::jsonb, FALSE)",
                    &[&ev.topic, &payload_str],
                )
                .await
            {
                error!("[EventBus] Error writing event to core.raw_payloads: {}", e);
            }
        }

        let _ = tx.commit().await;
    }

    pub fn subscribe_ws(&self) -> broadcast::Receiver<String> {
        self.ws_tx.subscribe()
    }
}

impl EventPublisher for AsyncEventBus {
    fn publish(&self, topic: &str, payload: Value) -> bool {
        let ev = QueuedEvent {
            topic: topic.to_string(),
            payload,
        };
        match self.tx.try_send(ev) {
            Ok(_) => true,
            Err(mpsc::error::TrySendError::Full(_)) => {
                warn!(
                    "[EventBus] OVERLOAD! Memory queue full, dropping event for topic: {}",
                    topic
                );
                false
            }
            Err(mpsc::error::TrySendError::Closed(_)) => false,
        }
    }

    fn broadcast_ws(&self, event_type: &str, data: Value) {
        if self.ws_tx.receiver_count() == 0 {
            return;
        }
        let msg = json!({
            "type": event_type,
            "data": data,
        });
        if let Ok(s) = serde_json::to_string(&msg) {
            let _ = self.ws_tx.send(s);
        }
    }
}

type TopicHandlersMap = Arc<RwLock<HashMap<String, Vec<Arc<dyn TopicHandler>>>>>;

pub struct BackgroundWorker {
    pool: Pool,
    handlers: TopicHandlersMap,
    batch_size: i64,
    poll_interval: Duration,
}

impl BackgroundWorker {
    pub fn new(pool: Pool, batch_size: i64, poll_interval_ms: u64) -> Self {
        Self {
            pool,
            handlers: Arc::new(RwLock::new(HashMap::new())),
            batch_size,
            poll_interval: Duration::from_millis(poll_interval_ms),
        }
    }

    pub fn register_handler(&self, topic: &str, handler: Arc<dyn TopicHandler>) {
        let mut map = self.handlers.write();
        map.entry(topic.to_string()).or_default().push(handler);
        info!("[Worker] Registered handler for topic '{}'", topic);
    }

    pub fn start(self: Arc<Self>) {
        let worker_poll = self.clone();
        tokio::spawn(async move {
            info!(
                "[Worker] CQRS Background Worker started (batch_size={}).",
                worker_poll.batch_size
            );
            loop {
                let processed = worker_poll.poll_and_process().await;
                if processed == 0 {
                    tokio::time::sleep(worker_poll.poll_interval).await;
                }
            }
        });

        let worker_clean = self;
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(3600));
            loop {
                interval.tick().await;
                if let Ok(client) = worker_clean.pool.get().await {
                    match client
                        .execute(
                            "DELETE FROM core.raw_payloads WHERE processed = TRUE AND created_at < NOW() - INTERVAL '1 day'",
                            &[],
                        )
                        .await
                    {
                        Ok(deleted) if deleted > 0 => {
                            info!("[Worker GC] Cleaned up {} old raw_payloads.", deleted);
                        }
                        _ => {}
                    }
                }
            }
        });
    }

    async fn poll_and_process(&self) -> usize {
        let mut client = match self.pool.get().await {
            Ok(c) => c,
            Err(e) => {
                error!("[Worker] DB connection error: {}", e);
                return 0;
            }
        };

        let tx = match client.transaction().await {
            Ok(t) => t,
            Err(e) => {
                error!("[Worker] Failed to start transaction: {}", e);
                return 0;
            }
        };

        let rows = match tx
            .query(
                "SELECT id, topic, raw_data::text AS payload_text
                 FROM core.raw_payloads
                 WHERE processed = FALSE
                 ORDER BY id ASC
                 LIMIT $1
                 FOR UPDATE SKIP LOCKED",
                &[&self.batch_size],
            )
            .await
        {
            Ok(r) => r,
            Err(e) => {
                error!("[Worker] Query error on core.raw_payloads: {}", e);
                return 0;
            }
        };

        if rows.is_empty() {
            let _ = tx.commit().await;
            return 0;
        }

        let mut processed_ids: Vec<i64> = Vec::new();

        for row in &rows {
            let record_id: i64 = row.get("id");
            let topic: String = row.get("topic");
            let payload_text: String = row.get("payload_text");
            let payload: Value = serde_json::from_str(&payload_text)
                .unwrap_or_else(|_| Value::Object(Default::default()));

            let handlers = {
                let map = self.handlers.read();
                map.get(&topic).cloned().unwrap_or_default()
            };

            for handler in handlers {
                if let Err(err_msg) = handler.handle(&topic, &payload).await {
                    error!(
                        "[Worker] Handler error on record #{} (topic {}): {}",
                        record_id, topic, err_msg
                    );
                }
            }
            processed_ids.push(record_id);
        }

        if !processed_ids.is_empty() {
            let _ = tx
                .execute(
                    "UPDATE core.raw_payloads SET processed = TRUE WHERE id = ANY($1::bigint[])",
                    &[&processed_ids],
                )
                .await;
        }

        let count = rows.len();
        if let Err(e) = tx.commit().await {
            error!("[Worker] Failed to commit transaction: {}", e);
            return 0;
        }

        count
    }
}
