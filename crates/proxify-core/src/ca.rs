use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use rcgen::{
    BasicConstraints, CertificateParams, DistinguishedName, DnType, ExtendedKeyUsagePurpose, IsCa,
    KeyPair, KeyUsagePurpose, SanType,
};
use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
use rustls::ServerConfig;
use std::fs;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use time::{Duration, OffsetDateTime};
use tokio::sync::broadcast;
use tracing::{info, warn};

struct CaSigner {
    ca_cert_der: CertificateDer<'static>,
    ca_key: KeyPair,
    ca_cert: rcgen::Certificate,
    leaf_key: KeyPair,
    leaf_key_der: Vec<u8>,
}

impl CaSigner {
    fn generate_server_config(&self, clean_host: &str) -> Result<Arc<ServerConfig>, String> {
        let mut leaf_params = CertificateParams::default();
        leaf_params.is_ca = IsCa::NoCa;
        leaf_params.key_usages = vec![
            KeyUsagePurpose::DigitalSignature,
            KeyUsagePurpose::KeyEncipherment,
        ];
        leaf_params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ServerAuth];
        leaf_params.not_before = OffsetDateTime::now_utc() - Duration::days(2);
        leaf_params.not_after = OffsetDateTime::now_utc() + Duration::days(365);

        let mut dn = DistinguishedName::new();
        dn.push(DnType::CommonName, clean_host.to_string());
        leaf_params.distinguished_name = dn;

        if let Ok(ip) = clean_host.parse::<std::net::IpAddr>() {
            leaf_params.subject_alt_names = vec![SanType::IpAddress(ip)];
        } else if let Ok(ia5) = clean_host.to_string().try_into() {
            leaf_params.subject_alt_names = vec![SanType::DnsName(ia5)];
        }

        let leaf_cert = leaf_params
            .signed_by(&self.leaf_key, &self.ca_cert, &self.ca_key)
            .map_err(|e| format!("Leaf signing failed: {}", e))?;

        let leaf_der = leaf_cert.der().clone();
        let key_der = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(self.leaf_key_der.clone()));

        let mut server_cfg = ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(vec![leaf_der, self.ca_cert_der.clone()], key_der)
            .map_err(|e| format!("rustls ServerConfig error: {}", e))?;

        // Prefer HTTP/1.1 to avoid negotiating h2 with raw HTTP/1.1 upstreams while maintaining h2 capability
        server_cfg.alpn_protocols = vec![b"http/1.1".to_vec(), b"h2".to_vec()];

        Ok(Arc::new(server_cfg))
    }
}

pub struct CertificateAuthority {
    ca_cert_pem: String,
    signer: Arc<CaSigner>,
    leaf_cache: DashMap<String, (Arc<ServerConfig>, AtomicU64)>,
    in_flight: DashMap<String, broadcast::Sender<Result<Arc<ServerConfig>, String>>>,
    access_counter: AtomicU64,
}

impl CertificateAuthority {
    fn build_instance(
        ca_cert_pem: String,
        ca_key_pem: String,
        ca_cert_der: CertificateDer<'static>,
    ) -> Result<Arc<Self>, String> {
        let ca_key =
            KeyPair::from_pem(&ca_key_pem).map_err(|e| format!("Failed to parse CA key: {}", e))?;
        let ca_params = CertificateParams::from_ca_cert_pem(&ca_cert_pem)
            .map_err(|e| format!("Failed to parse CA cert: {}", e))?;
        let ca_cert = ca_params
            .self_signed(&ca_key)
            .map_err(|e| format!("Failed to construct CA signer: {}", e))?;

        let leaf_key =
            KeyPair::generate().map_err(|e| format!("Shared leaf keygen failed: {}", e))?;
        let leaf_key_der = leaf_key.serialize_der();

        let signer = Arc::new(CaSigner {
            ca_cert_der,
            ca_key,
            ca_cert,
            leaf_key,
            leaf_key_der,
        });

        Ok(Arc::new(Self {
            ca_cert_pem,
            signer,
            leaf_cache: DashMap::new(),
            in_flight: DashMap::new(),
            access_counter: AtomicU64::new(1),
        }))
    }

    pub fn load_or_generate(ca_dir: &Path) -> Result<Arc<Self>, String> {
        let _ = rustls::crypto::ring::default_provider().install_default();
        let _ = fs::create_dir_all(ca_dir);
        let combined_pem_path = ca_dir.join("mitmproxy-ca.pem");
        let cert_pem_path = ca_dir.join("mitmproxy-ca-cert.pem");

        if combined_pem_path.exists() {
            if let Ok(raw_pem) = fs::read_to_string(&combined_pem_path) {
                if let Some((key_pem, cert_pem, cert_der)) = Self::extract_key_and_cert(&raw_pem) {
                    info!(
                        "[CA] Loaded existing Root CA from {}",
                        combined_pem_path.display()
                    );
                    if !cert_pem_path.exists() {
                        let _ = fs::write(&cert_pem_path, &cert_pem);
                    }
                    return Self::build_instance(cert_pem, key_pem, cert_der);
                } else {
                    warn!("[CA] Existing mitmproxy-ca.pem could not be parsed by rcgen; generating fresh Root CA in memory.");
                }
            }
        }

        let mut params = CertificateParams::default();
        params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        params.key_usages = vec![
            KeyUsagePurpose::KeyCertSign,
            KeyUsagePurpose::CrlSign,
            KeyUsagePurpose::DigitalSignature,
        ];
        let mut dn = DistinguishedName::new();
        dn.push(DnType::CommonName, "mitmproxy");
        dn.push(DnType::OrganizationName, "mitmproxy");
        params.distinguished_name = dn;
        params.not_before = OffsetDateTime::now_utc() - Duration::days(30);
        params.not_after = OffsetDateTime::now_utc() + Duration::days(3650);

        let key_pair = KeyPair::generate().map_err(|e| format!("CA keygen failed: {}", e))?;
        let ca_cert = params
            .self_signed(&key_pair)
            .map_err(|e| format!("CA self-sign failed: {}", e))?;

        let ca_cert_pem = ca_cert.pem();
        let ca_key_pem = key_pair.serialize_pem();
        let ca_cert_der = ca_cert.der().clone();

        if !combined_pem_path.exists() {
            let combined = format!("{}\n{}", ca_key_pem.trim(), ca_cert_pem.trim());
            let _ = fs::write(&combined_pem_path, combined);
            let _ = fs::write(&cert_pem_path, &ca_cert_pem);
            info!(
                "[CA] Generated new Root CA at {}",
                combined_pem_path.display()
            );
        }

        Self::build_instance(ca_cert_pem, ca_key_pem, ca_cert_der)
    }

    fn extract_key_and_cert(raw_pem: &str) -> Option<(String, String, CertificateDer<'static>)> {
        let mut reader = std::io::BufReader::new(raw_pem.as_bytes());
        let certs: Vec<CertificateDer<'static>> = rustls_pemfile::certs(&mut reader)
            .filter_map(|r| r.ok())
            .collect();
        let cert_der = certs.into_iter().next()?;

        let mut key_pem = String::new();
        let mut cert_pem = String::new();
        let mut in_key = false;
        let mut in_cert = false;

        for line in raw_pem.lines() {
            if line.contains("BEGIN") && line.contains("PRIVATE KEY") {
                in_key = true;
            }
            if line.contains("BEGIN CERTIFICATE") {
                in_cert = true;
            }
            if in_key {
                key_pem.push_str(line);
                key_pem.push('\n');
            }
            if in_cert {
                cert_pem.push_str(line);
                cert_pem.push('\n');
            }
            if line.contains("END") && line.contains("PRIVATE KEY") {
                in_key = false;
            }
            if line.contains("END CERTIFICATE") {
                in_cert = false;
            }
        }

        if key_pem.is_empty() || cert_pem.is_empty() {
            return None;
        }

        if key_pem.contains("BEGIN RSA PRIVATE KEY") {
            use std::io::Write;
            use std::process::{Command, Stdio};
            if let Ok(mut child) = Command::new("openssl")
                .args([
                    "pkcs8", "-topk8", "-inform", "PEM", "-outform", "PEM", "-nocrypt",
                ])
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
            {
                if let Some(mut stdin) = child.stdin.take() {
                    let _ = stdin.write_all(key_pem.as_bytes());
                }
                if let Ok(output) = child.wait_with_output() {
                    if output.status.success() {
                        if let Ok(converted) = String::from_utf8(output.stdout) {
                            if !converted.is_empty() {
                                key_pem = converted;
                            }
                        }
                    }
                }
            }
        }

        KeyPair::from_pem(&key_pem).ok()?;
        CertificateParams::from_ca_cert_pem(&cert_pem).ok()?;

        Some((key_pem, cert_pem, cert_der))
    }

    pub fn ca_cert_pem(&self) -> &str {
        &self.ca_cert_pem
    }

    pub fn ca_cert_der_bytes(&self) -> &[u8] {
        self.signer.ca_cert_der.as_ref()
    }

    fn insert_to_cache(&self, clean_host: String, cfg: Arc<ServerConfig>) {
        if self.leaf_cache.len() >= 4096 {
            // True LRU eviction: evict the oldest 512 entries based on access counter
            let mut entries: Vec<(String, u64)> = self
                .leaf_cache
                .iter()
                .map(|e| (e.key().clone(), e.value().1.load(Ordering::Relaxed)))
                .collect();
            entries.sort_unstable_by_key(|e| e.1);
            for (k, _) in entries.into_iter().take(512) {
                self.leaf_cache.remove(&k);
            }
        }
        let counter = self.access_counter.fetch_add(1, Ordering::Relaxed);
        self.leaf_cache
            .insert(clean_host, (cfg, AtomicU64::new(counter)));
    }

    pub fn server_config_for_host(&self, host: &str) -> Result<Arc<ServerConfig>, String> {
        let clean_host = host.split(':').next().unwrap_or(host).trim().to_lowercase();
        if let Some(entry) = self.leaf_cache.get(&clean_host) {
            entry.1.store(
                self.access_counter.fetch_add(1, Ordering::Relaxed),
                Ordering::Relaxed,
            );
            return Ok(entry.0.clone());
        }

        let cfg = self.signer.generate_server_config(&clean_host)?;
        self.insert_to_cache(clean_host, cfg.clone());
        Ok(cfg)
    }

    pub async fn server_config_for_host_async(
        &self,
        host: &str,
    ) -> Result<Arc<ServerConfig>, String> {
        let clean_host = host.split(':').next().unwrap_or(host).trim().to_lowercase();
        if let Some(entry) = self.leaf_cache.get(&clean_host) {
            entry.1.store(
                self.access_counter.fetch_add(1, Ordering::Relaxed),
                Ordering::Relaxed,
            );
            return Ok(entry.0.clone());
        }

        // Single-flight deduplication with double-checked locking across leaf_cache & in_flight
        let (is_leader, mut rx) = match self.in_flight.entry(clean_host.clone()) {
            Entry::Occupied(e) => (false, e.get().subscribe()),
            Entry::Vacant(e) => {
                if let Some(entry) = self.leaf_cache.get(&clean_host) {
                    entry.1.store(
                        self.access_counter.fetch_add(1, Ordering::Relaxed),
                        Ordering::Relaxed,
                    );
                    return Ok(entry.0.clone());
                }
                let (tx, rx) = broadcast::channel(1);
                e.insert(tx);
                (true, rx)
            }
        };

        if !is_leader {
            return match rx.recv().await {
                Ok(res) => res,
                Err(_) => {
                    // Leader failed or dropped; fallback to direct cache check or sync generate
                    if let Some(entry) = self.leaf_cache.get(&clean_host) {
                        entry.1.store(
                            self.access_counter.fetch_add(1, Ordering::Relaxed),
                            Ordering::Relaxed,
                        );
                        return Ok(entry.0.clone());
                    }
                    self.server_config_for_host(&clean_host)
                }
            };
        }

        // RAII drop guard for in_flight cleanup
        struct InFlightGuard<'a> {
            in_flight: &'a DashMap<String, broadcast::Sender<Result<Arc<ServerConfig>, String>>>,
            key: String,
            completed: bool,
        }
        impl<'a> Drop for InFlightGuard<'a> {
            fn drop(&mut self) {
                if !self.completed {
                    self.in_flight.remove(&self.key);
                }
            }
        }
        let mut guard = InFlightGuard {
            in_flight: &self.in_flight,
            key: clean_host.clone(),
            completed: false,
        };

        // Offload CPU-heavy cryptographic signing to Tokio blocking threadpool
        let signer = self.signer.clone();
        let host_for_task = clean_host.clone();
        let signing_res =
            tokio::task::spawn_blocking(move || signer.generate_server_config(&host_for_task))
                .await
                .map_err(|e| format!("CA spawn_blocking task join error: {}", e))?;

        // Populate leaf_cache BEFORE removing in_flight entry so late arrivals never miss both!
        if let Ok(ref cfg) = signing_res {
            self.insert_to_cache(clean_host.clone(), cfg.clone());
        }

        guard.completed = true;
        if let Some((_, tx)) = self.in_flight.remove(&clean_host) {
            let _ = tx.send(signing_res.clone());
        }

        signing_res
    }

    pub async fn get_server_config(&self, host: &str) -> Result<Arc<ServerConfig>, String> {
        self.server_config_for_host_async(host).await
    }
}
