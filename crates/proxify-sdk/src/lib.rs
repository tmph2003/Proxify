pub use async_trait::async_trait;
use axum::Router;
use deadpool_postgres::Pool;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;

use bytes::Bytes;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FlowRequest {
    pub method: String,
    pub url: String,
    pub host: String,
    pub port: u16,
    pub path: String,
    pub scheme: String,
    pub headers: HashMap<String, String>,
    pub content: Bytes,
    pub timestamp_start: f64,
}

impl FlowRequest {
    #[inline]
    pub fn body(&self) -> &Bytes {
        &self.content
    }

    #[inline]
    pub fn body_mut(&mut self) -> &mut Bytes {
        &mut self.content
    }

    #[inline]
    pub fn content_slice(&self) -> &[u8] {
        &self.content
    }

    #[inline]
    pub fn content_vec(&self) -> Vec<u8> {
        self.content.to_vec()
    }

    #[inline]
    pub fn set_content<T: Into<Bytes>>(&mut self, data: T) {
        self.content = data.into();
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FlowResponse {
    pub status_code: u16,
    pub headers: HashMap<String, String>,
    pub content: Bytes,
}

impl FlowResponse {
    #[inline]
    pub fn body(&self) -> &Bytes {
        &self.content
    }

    #[inline]
    pub fn body_mut(&mut self) -> &mut Bytes {
        &mut self.content
    }

    #[inline]
    pub fn content_slice(&self) -> &[u8] {
        &self.content
    }

    #[inline]
    pub fn content_vec(&self) -> Vec<u8> {
        self.content.to_vec()
    }

    #[inline]
    pub fn set_content<T: Into<Bytes>>(&mut self, data: T) {
        self.content = data.into();
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HttpFlow {
    pub request: FlowRequest,
    pub response: Option<FlowResponse>,
}

impl HttpFlow {
    pub fn request_content_type(&self) -> String {
        for (k, v) in &self.request.headers {
            if k.eq_ignore_ascii_case("content-type") {
                return v.to_lowercase();
            }
        }
        String::new()
    }

    pub fn response_content_type(&self) -> String {
        if let Some(ref resp) = self.response {
            for (k, v) in &resp.headers {
                if k.eq_ignore_ascii_case("content-type") {
                    return v.to_lowercase();
                }
            }
        }
        String::new()
    }
}

#[async_trait]
pub trait ObserverInterceptor: Send + Sync {
    async fn observe_request(&self, _flow: &HttpFlow) {}
    async fn observe_response(&self, _flow: &HttpFlow) {}
}

#[async_trait]
pub trait MutatorInterceptor: Send + Sync {
    async fn mutate_request(&self, _flow: &mut HttpFlow) {}
    async fn mutate_response(&self, _flow: &mut HttpFlow) {}
}

pub trait RecordFilter: Send + Sync {
    fn should_record(&self, flow: &HttpFlow) -> bool;
}

pub trait EventPublisher: Send + Sync {
    fn publish(&self, topic: &str, payload: Value) -> bool;
    fn broadcast_ws(&self, event_type: &str, data: Value);
}

#[async_trait]
pub trait TopicHandler: Send + Sync {
    async fn handle(&self, topic: &str, payload: &Value) -> Result<(), String>;
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UiPageMetadata {
    pub name: String,
    pub path: String,
    pub title: String,
    pub icon: String,
    pub description: String,
    pub order: i32,
}

pub struct ExtensionContext {
    pub event_bus: Arc<dyn EventPublisher>,
    pub db_pool: Pool,
    pub observers: Vec<(String, Arc<dyn ObserverInterceptor>)>,
    pub mutators: Vec<(String, Arc<dyn MutatorInterceptor>)>,
    pub stream_rules: Vec<String>,
    pub stream_path_rules: Vec<(String, String)>,
    pub stream_exclusions: Vec<(String, String)>,
    pub soft_block_signatures: Vec<String>,
    pub record_filters: Vec<Arc<dyn RecordFilter>>,
    pub topic_handlers: Vec<(String, Arc<dyn TopicHandler>)>,
    pub sub_routers: Vec<Router>,
    pub ui_pages: Vec<UiPageMetadata>,
    pub lifecycle_depth: u32,
}

impl ExtensionContext {
    pub fn new(event_bus: Arc<dyn EventPublisher>, db_pool: Pool) -> Self {
        Self {
            event_bus,
            db_pool,
            observers: Vec::new(),
            mutators: Vec::new(),
            stream_rules: Vec::new(),
            stream_path_rules: Vec::new(),
            stream_exclusions: Vec::new(),
            soft_block_signatures: Vec::new(),
            record_filters: Vec::new(),
            topic_handlers: Vec::new(),
            sub_routers: Vec::new(),
            ui_pages: Vec::new(),
            lifecycle_depth: 0,
        }
    }

    #[inline]
    pub fn db_pool(&self) -> &Pool {
        &self.db_pool
    }

    #[inline]
    pub fn event_bus(&self) -> Arc<dyn EventPublisher> {
        self.event_bus.clone()
    }

    pub fn register_observer(
        &mut self,
        domain_pattern: &str,
        observer: Arc<dyn ObserverInterceptor>,
    ) {
        self.observers.push((domain_pattern.to_string(), observer));
    }

    pub fn register_mutator(&mut self, domain_pattern: &str, mutator: Arc<dyn MutatorInterceptor>) {
        self.mutators.push((domain_pattern.to_string(), mutator));
    }

    pub fn register_stream_rule(&mut self, domain_pattern: &str) {
        self.stream_rules.push(domain_pattern.to_string());
    }

    pub fn register_stream_path_rule(&mut self, domain_pattern: &str, path_prefix: &str) {
        self.stream_path_rules
            .push((domain_pattern.to_string(), path_prefix.to_string()));
    }

    pub fn register_stream_exclusion(&mut self, domain_pattern: &str, pattern: &str) {
        self.stream_exclusions
            .push((domain_pattern.to_string(), pattern.to_string()));
    }

    pub fn register_soft_block_signature(&mut self, signature: &str) {
        self.soft_block_signatures.push(signature.to_string());
    }

    pub fn register_record_filter(&mut self, filter: Arc<dyn RecordFilter>) {
        self.record_filters.push(filter);
    }

    pub fn subscribe_topic(&mut self, topic: &str, handler: Arc<dyn TopicHandler>) {
        self.topic_handlers.push((topic.to_string(), handler));
    }

    pub fn register_sub_router(&mut self, router: Router) {
        self.sub_routers.push(router);
    }

    pub fn register_ui_page(&mut self, page: UiPageMetadata) {
        self.ui_pages.push(page);
    }

    #[inline]
    pub fn observers(&self) -> &[(String, Arc<dyn ObserverInterceptor>)] {
        &self.observers
    }

    #[inline]
    pub fn mutators(&self) -> &[(String, Arc<dyn MutatorInterceptor>)] {
        &self.mutators
    }

    #[inline]
    pub fn stream_rules(&self) -> &[String] {
        &self.stream_rules
    }

    #[inline]
    pub fn stream_path_rules(&self) -> &[(String, String)] {
        &self.stream_path_rules
    }

    #[inline]
    pub fn stream_exclusions(&self) -> &[(String, String)] {
        &self.stream_exclusions
    }

    #[inline]
    pub fn soft_block_signatures(&self) -> &[String] {
        &self.soft_block_signatures
    }

    #[inline]
    pub fn record_filters(&self) -> &[Arc<dyn RecordFilter>] {
        &self.record_filters
    }

    #[inline]
    pub fn topic_handlers(&self) -> &[(String, Arc<dyn TopicHandler>)] {
        &self.topic_handlers
    }

    #[inline]
    pub fn sub_routers(&self) -> &[Router] {
        &self.sub_routers
    }

    #[inline]
    pub fn take_sub_routers(&mut self) -> Vec<Router> {
        std::mem::take(&mut self.sub_routers)
    }

    #[inline]
    pub fn ui_pages(&self) -> &[UiPageMetadata] {
        &self.ui_pages
    }
}

#[async_trait]
pub trait BaseExtension: Send + Sync {
    fn name(&self) -> &str;

    async fn on_init(&self, context: &mut ExtensionContext) -> Result<(), String> {
        if context.lifecycle_depth > 0 {
            return Ok(());
        }
        context.lifecycle_depth += 1;
        #[allow(deprecated)]
        let res = self.on_Init(context).await;
        context.lifecycle_depth -= 1;
        res
    }

    #[allow(non_snake_case)]
    #[deprecated(note = "Use on_init instead")]
    async fn on_Init(&self, context: &mut ExtensionContext) -> Result<(), String> {
        if context.lifecycle_depth > 0 {
            return Ok(());
        }
        context.lifecycle_depth += 1;
        let res = self.on_init(context).await;
        context.lifecycle_depth -= 1;
        res
    }
}
