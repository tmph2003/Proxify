use parking_lot::RwLock;
use proxify_sdk::{HttpFlow, MutatorInterceptor, ObserverInterceptor, RecordFilter};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

#[derive(Default)]
struct TrieNode {
    children: HashMap<String, TrieNode>,
    observers: Vec<Arc<dyn ObserverInterceptor>>,
    mutators: Vec<Arc<dyn MutatorInterceptor>>,
    wildcard_observers: Vec<Arc<dyn ObserverInterceptor>>,
    wildcard_mutators: Vec<Arc<dyn MutatorInterceptor>>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct StreamDomainRule {
    exact: String,
    dot_suffix: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct StreamPathRule {
    domain_exact: String,
    domain_dot_suffix: String,
    path_prefix: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct StreamExclusionRule {
    domain_exact: String,
    domain_dot_suffix: String,
    pattern: String,
}

#[inline]
fn normalize_stream_domain(domain_pattern: &str) -> (String, String) {
    let clean = domain_pattern
        .trim()
        .trim_start_matches("*.")
        .to_lowercase();
    if clean.is_empty() || clean == "*" {
        (String::new(), String::new())
    } else {
        let dot_suffix = format!(".{}", clean);
        (clean, dot_suffix)
    }
}

#[inline]
fn host_matches_rule(host: &str, exact: &str, dot_suffix: &str) -> bool {
    if exact.is_empty() {
        return true;
    }
    host.eq_ignore_ascii_case(exact)
        || (host.len() > dot_suffix.len()
            && host[host.len() - dot_suffix.len()..].eq_ignore_ascii_case(dot_suffix))
}

struct RouterInner {
    root: TrieNode,
    global_observers: Vec<Arc<dyn ObserverInterceptor>>,
    global_mutators: Vec<Arc<dyn MutatorInterceptor>>,
    stream_rules: Vec<StreamDomainRule>,
    stream_path_rules: Vec<StreamPathRule>,
    stream_exclusions: Vec<StreamExclusionRule>,
    record_filters: Vec<Arc<dyn RecordFilter>>,
}

pub struct ProxyRouter {
    inner: RwLock<RouterInner>,
}

pub type ResolvedInterceptors = (
    Vec<Arc<dyn ObserverInterceptor>>,
    Vec<Arc<dyn MutatorInterceptor>>,
);

impl ProxyRouter {
    pub fn new() -> Self {
        Self {
            inner: RwLock::new(RouterInner {
                root: TrieNode::default(),
                global_observers: Vec::new(),
                global_mutators: Vec::new(),
                stream_rules: Vec::new(),
                stream_path_rules: Vec::new(),
                stream_exclusions: Vec::new(),
                record_filters: Vec::new(),
            }),
        }
    }

    fn normalize_domain(domain: &str) -> (bool, Vec<String>) {
        let trimmed = domain
            .trim()
            .split(':')
            .next()
            .unwrap_or("")
            .trim_matches('.')
            .to_lowercase();
        if let Some(rest) = trimmed.strip_prefix("*.") {
            let labels = rest
                .split('.')
                .filter(|s| !s.is_empty())
                .rev()
                .map(|s| s.to_string())
                .collect();
            (true, labels)
        } else {
            let labels = trimmed
                .split('.')
                .filter(|s| !s.is_empty())
                .rev()
                .map(|s| s.to_string())
                .collect();
            (false, labels)
        }
    }

    pub fn register_observer(&self, domain_pattern: &str, observer: Arc<dyn ObserverInterceptor>) {
        let mut inner = self.inner.write();
        if domain_pattern == "*" || domain_pattern.is_empty() {
            inner.global_observers.push(observer);
            return;
        }
        let (is_wildcard, labels) = Self::normalize_domain(domain_pattern);
        if labels.is_empty() {
            inner.global_observers.push(observer);
            return;
        }
        let mut node = &mut inner.root;
        for label in labels {
            node = node.children.entry(label).or_default();
        }
        if is_wildcard {
            node.wildcard_observers.push(observer);
        } else {
            node.observers.push(observer);
        }
    }

    pub fn register_mutator(&self, domain_pattern: &str, mutator: Arc<dyn MutatorInterceptor>) {
        let mut inner = self.inner.write();
        if domain_pattern == "*" || domain_pattern.is_empty() {
            inner.global_mutators.push(mutator);
            return;
        }
        let (is_wildcard, labels) = Self::normalize_domain(domain_pattern);
        if labels.is_empty() {
            inner.global_mutators.push(mutator);
            return;
        }
        let mut node = &mut inner.root;
        for label in labels {
            node = node.children.entry(label).or_default();
        }
        if is_wildcard {
            node.wildcard_mutators.push(mutator);
        } else {
            node.mutators.push(mutator);
        }
    }

    pub fn register_stream_rule(&self, domain_pattern: &str) {
        let (exact, dot_suffix) = normalize_stream_domain(domain_pattern);
        if !exact.is_empty() {
            let mut inner = self.inner.write();
            if !inner.stream_rules.iter().any(|r| r.exact == exact) {
                inner
                    .stream_rules
                    .push(StreamDomainRule { exact, dot_suffix });
            }
        }
    }

    pub fn register_stream_path_rule(&self, domain_pattern: &str, path_prefix: &str) {
        let (domain_exact, domain_dot_suffix) = normalize_stream_domain(domain_pattern);
        let prefix = path_prefix.trim().to_lowercase();
        if !prefix.is_empty() {
            let mut inner = self.inner.write();
            if !inner
                .stream_path_rules
                .iter()
                .any(|r| r.domain_exact == domain_exact && r.path_prefix == prefix)
            {
                inner.stream_path_rules.push(StreamPathRule {
                    domain_exact,
                    domain_dot_suffix,
                    path_prefix: prefix,
                });
            }
        }
    }

    pub fn register_stream_exclusion(&self, domain_pattern: &str, pattern: &str) {
        let (domain_exact, domain_dot_suffix) = normalize_stream_domain(domain_pattern);
        let pat = pattern.trim().to_lowercase();
        if !pat.is_empty() {
            let mut inner = self.inner.write();
            if !inner
                .stream_exclusions
                .iter()
                .any(|r| r.domain_exact == domain_exact && r.pattern == pat)
            {
                inner.stream_exclusions.push(StreamExclusionRule {
                    domain_exact,
                    domain_dot_suffix,
                    pattern: pat,
                });
            }
        }
    }

    pub fn register_record_filter(&self, filter: Arc<dyn RecordFilter>) {
        self.inner.write().record_filters.push(filter);
    }

    pub fn resolve(&self, host: &str) -> ResolvedInterceptors {
        let inner = self.inner.read();
        let mut observers = inner.global_observers.clone();
        let mut mutators = inner.global_mutators.clone();

        let host_lower = host
            .split(':')
            .next()
            .unwrap_or(host)
            .trim()
            .trim_matches('.')
            .to_lowercase();
        let labels: Vec<&str> = host_lower
            .split('.')
            .filter(|s| !s.is_empty())
            .rev()
            .collect();
        let mut node = &inner.root;

        for (i, label) in labels.iter().enumerate() {
            if let Some(child) = node.children.get(*label) {
                node = child;
                observers.extend(node.wildcard_observers.iter().cloned());
                mutators.extend(node.wildcard_mutators.iter().cloned());
                if i + 1 == labels.len() {
                    observers.extend(node.observers.iter().cloned());
                    mutators.extend(node.mutators.iter().cloned());
                }
            } else {
                break;
            }
        }

        let uniq_obs = if observers.len() <= 1 {
            observers
        } else {
            let mut u = Vec::with_capacity(observers.len());
            let mut seen = HashSet::new();
            for o in observers {
                let ptr = Arc::as_ptr(&o) as *const () as usize;
                if seen.insert(ptr) {
                    u.push(o);
                }
            }
            u
        };

        let uniq_mut = if mutators.len() <= 1 {
            mutators
        } else {
            let mut u = Vec::with_capacity(mutators.len());
            let mut seen = HashSet::new();
            for m in mutators {
                let ptr = Arc::as_ptr(&m) as *const () as usize;
                if seen.insert(ptr) {
                    u.push(m);
                }
            }
            u
        };

        (uniq_obs, uniq_mut)
    }

    pub fn should_stream(&self, host: &str) -> bool {
        let h = host.split(':').next().unwrap_or(host).trim();
        let inner = self.inner.read();
        inner.stream_rules.iter().any(|r| {
            h.eq_ignore_ascii_case(&r.exact)
                || (h.len() > r.dot_suffix.len()
                    && h[h.len() - r.dot_suffix.len()..].eq_ignore_ascii_case(&r.dot_suffix))
        })
    }

    pub fn should_stream_path(&self, host: &str, path: &str) -> bool {
        let h = host.split(':').next().unwrap_or(host).trim();
        let p = path.split('?').next().unwrap_or(path).to_lowercase();
        let inner = self.inner.read();
        inner.stream_path_rules.iter().any(|r| {
            host_matches_rule(h, &r.domain_exact, &r.domain_dot_suffix)
                && p.starts_with(&r.path_prefix)
        })
    }

    pub fn is_stream_excluded(&self, host: &str, path: &str) -> bool {
        let h = host.split(':').next().unwrap_or(host).trim();
        let p = path.split('?').next().unwrap_or(path).to_lowercase();
        let inner = self.inner.read();
        inner.stream_exclusions.iter().any(|r| {
            host_matches_rule(h, &r.domain_exact, &r.domain_dot_suffix) && p.contains(&r.pattern)
        })
    }

    pub fn should_stream_request(&self, host: &str, path: &str) -> bool {
        let h = host.split(':').next().unwrap_or(host).trim();
        let p = path.split('?').next().unwrap_or(path).to_lowercase();
        let inner = self.inner.read();

        if inner.stream_exclusions.iter().any(|r| {
            host_matches_rule(h, &r.domain_exact, &r.domain_dot_suffix) && p.contains(&r.pattern)
        }) {
            return false;
        }

        if inner.stream_rules.iter().any(|r| {
            h.eq_ignore_ascii_case(&r.exact)
                || (h.len() > r.dot_suffix.len()
                    && h[h.len() - r.dot_suffix.len()..].eq_ignore_ascii_case(&r.dot_suffix))
        }) {
            return true;
        }

        inner.stream_path_rules.iter().any(|r| {
            host_matches_rule(h, &r.domain_exact, &r.domain_dot_suffix)
                && p.starts_with(&r.path_prefix)
        })
    }

    pub fn should_record(&self, flow: &HttpFlow) -> bool {
        let host = flow.request.host.trim();
        let path = flow.request.path.trim();

        if self.should_stream_request(host, path) {
            return false;
        }

        let inner = self.inner.read();
        for filter in &inner.record_filters {
            if !filter.should_record(flow) {
                return false;
            }
        }
        true
    }
}

impl Default for ProxyRouter {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;

    struct DummyMutator;
    #[async_trait]
    impl MutatorInterceptor for DummyMutator {}

    #[test]
    fn test_radix_trie_matching() {
        let router = ProxyRouter::new();
        let m = Arc::new(DummyMutator);
        router.register_mutator("*.youtube.com", m.clone());
        router.register_mutator("youtube.com", m);

        let (_, muts1) = router.resolve("www.youtube.com");
        assert_eq!(muts1.len(), 1);

        let (_, muts2) = router.resolve("youtube.com");
        assert_eq!(muts2.len(), 1);

        let (_, muts3) = router.resolve("example.com");
        assert_eq!(muts3.len(), 0);
    }

    #[test]
    fn test_stream_path_rule_matching() {
        let router = ProxyRouter::new();
        router.register_stream_path_rule("*.youtube.com", "/live_chat");
        router.register_stream_path_rule("*.youtube.com", "/videoplayback");

        assert!(router.should_stream_path("www.youtube.com", "/live_chat?v=123"));
        assert!(router.should_stream_path("youtube.com", "/videoplayback?id=456"));
        assert!(!router.should_stream_path("www.youtube.com", "/watch?v=123"));
        assert!(!router.should_stream_path("vimeo.com", "/live_chat"));
    }

    #[test]
    fn test_stream_exclusion_rule() {
        let router = ProxyRouter::new();
        router.register_stream_rule("*.zalo.me");
        router.register_stream_exclusion("*.zalo.me", "trusted-device-bridge");

        assert!(router.should_stream("chat.zalo.me"));
        assert!(router.is_stream_excluded("chat.zalo.me", "/api/trusted-device-bridge.js"));
        assert!(!router.is_stream_excluded("chat.zalo.me", "/api/normal.js"));

        // should_stream_request combines both
        assert!(!router.should_stream_request("chat.zalo.me", "/api/trusted-device-bridge.js"));
        assert!(router.should_stream_request("chat.zalo.me", "/api/normal.js"));
    }
}
