<h1 align="center">
    <br>
    <img alt="Proxify Logo" src="assets/logo.png" width="150" style="border-radius: 20px;">
    <br>
    Proxify
    <br>
    <small>The Ultimate Multi-Platform Request Capture & Reverse-Engineering Framework</small>
</h1>

<p align="center">
    <strong>English</strong> | <a href="README_vi.md">Tiếng Việt</a>
</p>

<p align="center">
    <a href="https://python.org" alt="Python version">
        <img alt="Python version" src="https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square&logo=python"></a>
    <a href="https://mitmproxy.org/" alt="Mitmproxy">
        <img alt="Mitmproxy version" src="https://img.shields.io/badge/Mitmproxy-10.1%2B-red?style=flat-square"></a>
    <a href="https://react.dev/" alt="React">
        <img alt="React version" src="https://img.shields.io/badge/React-18%2B-61DAFB?style=flat-square&logo=react"></a>
    <a href="https://postgresql.org" alt="PostgreSQL">
        <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-Ready-336791?style=flat-square&logo=postgresql"></a>
    <a href="#" alt="License">
        <img alt="License" src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square"></a>
</p>

<p align="center">
    <a href="#overview"><strong>Overview</strong></a>
    &middot;
    <a href="#core-features"><strong>Core Features</strong></a>
    &middot;
    <a href="#platforms"><strong>Platforms & Plugins</strong></a>
    &middot;
    <a href="#quick-start"><strong>Quick Start</strong></a>
    &middot;
    <a href="#architecture"><strong>Architecture</strong></a>
    &middot;
    <a href="#structure"><strong>Directory Structure</strong></a>
</p>

---

## 🌟 Overview

**Proxify** is a comprehensive framework engineered for **traffic interception, reverse-engineering, and automated data extraction** across HTTP, HTTPS, HTTP/2, and WebSocket protocols.

Built on the industrial-grade **Mitmproxy 10** engine, Proxify seamlessly unites:
1. **Multi-Threaded Proxy Core**: Silent interception, HTTPS TLS decryption, and high-throughput raw traffic ingestion into PostgreSQL.
2. **Anti-Bot & WAF Bypass Engine**: Intelligent detection and evasion of modern bot protections (Cloudflare Turnstile, Facebook Checkpoint, Akamai) via TLS/JA3 impersonation and a Chrome Extension First-Party Tab Bridge.
3. **Pluggable Multi-Platform Architecture**: Out-of-the-box support for **Facebook**, **Zalo**, and **YouTube**, alongside a dynamic plugin system ready to scale to TikTok, Shopee, Telegram, and beyond.
4. **Interactive Real-Time Dashboard**: A modern React-powered UI featuring a Live Traffic Inspector (akin to Fiddler/Charles/Burp Suite), platform-specific management consoles, session persistence, and crawling controllers.

---

## 🛡️ Core Features

### 1. Stealth MITM Interception & Decryption
- **Full HTTPS/TLS Decryption**: Generates and manages trusted CA root certificates to decrypt encrypted traffic across desktop browsers, mobile apps (Android/iOS), and emulators.
- **HTTP/2 & WebSocket Streaming**: Native handling of multiplexed HTTP/2 frames and persistent WebSocket duplex streams (e.g., Zalo chat sockets, Facebook Lightspeed).
- **Asynchronous Traffic Storage**: Offloads raw requests/responses to an asynchronous PostgreSQL pipeline (`TrafficStorageWorker`) with zero latency impact on live browsing.
- **Clean Logging Engine**: Employs `PollingEndpointFilter` to silence routine `200 OK` polling noise, delivering a tranquil, high-signal console.

### 2. Anti-Bot Bypass & Stealth Suite
- **Soft-Block Detection (`stealth.py`)**: Automatically detects Cloudflare challenge pages, CAPTCHAs, and 429/503 rate-limit states to trigger intelligent exponential backoff.
- **Chrome Extension First-Party Tab Bridge**: Executes requests directly within the user's authentic Facebook/site browser tab, fully inheriting real cookies, local IP, and browser context to **eliminate 1357001 logout errors**.
- **Circuit Breaker Resilience**: Prevents cascading failures and server bans by auto-throttling requests when upstream targets show distress.

### 3. Hot-Pluggable Dynamic Plugin System
- Follows the **Open/Closed Principle**: Extend Proxify to any new service simply by subclassing `BasePlugin` and adding the `@register_plugin("name")` decorator.
- Lifecycle hooks available: `on_request()`, `on_response()`, `on_websocket_message()`, and `on_error()`.

---

## 🌐 Supported Platforms & Plugins

### 📘 1. Facebook Platform (`backend/extensions/facebook/`)
- **Decoupled Feed & Comment Engine (50x Faster)**: Super-fast chronological feed scraping (~1.5s/page) decoupled from deep comment extraction.
- **Dual-Engine Post Refresh & Zero-Checkpoint Architecture**:
  - **Zero-Cookie Anonymous Engine**: Instantly refreshes reactions, comment counts, and post availability using browser-fingerprinted HTTP/2 sessions without sending account cookies, eliminating checkpoint risks.
  - **Extension Bridge GraphQL Fallback**: Seamless fallback for private groups executing strictly scoped `/api/graphql/` queries inside the user's authentic tab.
- **Multi-Tenant Chrome Extension Isolation**: Client ID-based job queues, heartbeats, and token caching allowing multiple concurrent browser sessions without state collision.
- **Automatic Unfiltered Comments**: Automatically enforces `CHRONOLOGICAL_UNFILTERED_INTENT_V1` to capture 100% of all comments without manual UI toggles.
- **Bi-Directional Relay Pagination**: Comprehensive handling of both `before` and `after` cursors up to 500 pages (~5,000 comments/post).
- **Interactive Floating Action Bar**: Bulk refresh, status verification, background comment crawling with live progress polling, and CSV export.
- **Facebook Dashboard Console**: Group selector, author filters, full-text search, and multi-level comment hierarchy viewer.

### 💬 2. Zalo Platform (`backend/extensions/zalo/`)
- **Protocol & Crypto Decryption**: Uses an embedded JavaScript runtime (`crypto_subtle.js`) to decrypt end-to-end encrypted packets and WebSocket messages from Zalo Web.
- **Message & Contact Extractor**: Automatically parses chat messages, group memberships, and contact books into structured PostgreSQL tables.
- **Dedicated Zalo Web UI**: Independent interface for inspecting decrypted Zalo messages and contacts in real-time.

### 🎥 3. YouTube Platform & Enhancer (`backend/extensions/youtube/`)
- **Graceful Ad-Stripping Engine**: Intelligently prunes top-level ad containers (`clean_youtube_json_data`) in Innertube JSON APIs and watch HTML without corrupting the player's internal state machine or breaking pause/play controls.
- **Inline Anti-AFK Watchdog**: Injects a lightweight in-page watchdog script and resets inactivity thresholds (`lactThresholdMs`) to 1,000 days, permanently bypassing "Video paused. Continue watching?" interruptions.
- **Zero-Buffering Stream Passthrough**: Routes high-throughput video chunks (`googlevideo.com`) via raw TCP Passthrough without TLS decryption overhead or Python memory buffering.

### 🔌 4. Zero-Overhead Passthrough & Stealth Suite (`backend/proxify/utils/stealth.py`)
- **Inverted Scope Protection (`allow_hosts`)**: Only intercepts target platform APIs; 100% of non-target internet traffic (Google Workspace, GitHub, games, OS telemetry) passes through at raw wire speed.
- **TLS ClientHello Impersonation**: Disguises proxy connections from JA3 fingerprint monitors using standard browser cipher suites.

---

## 🚀 Quick Start

### Method 1: Docker Compose (Recommended)

Start the entire stack (Backend Proxy + PostgreSQL + React UI) with a single command:

```bash
# 1. Clone the repository
git clone https://github.com/tmph2003/Proxify.git
cd Proxify

# 2. Launch all services
docker compose up -d
```

Access your environment:
- **Web Dashboard (React UI):** `http://localhost:8888`
- **Proxy Server (Mitmproxy):** `http://localhost:8080`
- **PostgreSQL Database:** Port `5432`

> 💡 **One-Time SSL Certificate Setup:**  
> Route your browser/device traffic through `127.0.0.1:8080`, then visit `http://mitm.it` in your browser to install the Mitmproxy Root CA certificate.

---

### Method 2: Manual Development Mode

```bash
# 1. Install Python requirements
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env

# 3. Start Proxy Backend
python -m proxify

# 4. Start React Frontend (in a separate terminal)
cd frontend
npm install
npm run dev
```

---

## 📂 Architecture Overview

```mermaid
graph TD
    Client["📱 Client Traffic (Browser / Mobile / App)"] -->|Proxy :8080| Core["🛡️ Proxify Core (Mitmproxy Engine)"]
    Core --> Plugins["🔌 Plugins & Platforms (Facebook, Zalo, YouTube,...)"]
    Plugins --> DB[("💾 PostgreSQL Database")]
    
    UI["💻 React Web Dashboard (:8888)"] <-->|Control & Monitor| Core
    Extension["🧩 Chrome Extension Bridge"] <-->|Anti-Bot Tab Execution| Plugins
```

---

## 📂 Directory Structure
 
```text
Proxify/
├── backend/
│   ├── chrome_extension/        # Browser Extension Bridge (Service Worker & Content Script)
│   ├── extensions/              # Modular Platform Extensions
│   │   ├── facebook/            # Facebook (Crawler, Bridge, Auth, Extractor, Multi-Tenant)
│   │   ├── youtube/             # YouTube (Ad-Stripper, Anti-AFK, Stream Passthrough)
│   │   └── zalo/                # Zalo (Crypto Decryption, Models, Extractor, DB)
│   ├── proxify/                 # Core framework & orchestration
│   │   ├── core/                # System orchestration & event bus
│   │   ├── database/            # PostgreSQL connection pool & migrations
│   │   ├── plugins/             # Plugin registry & base classes
│   │   ├── sdk/                 # Public SDK & lifecycle interfaces
│   │   ├── utils/               # Shared utilities (stealth, circuit breaker, graphql)
│   │   ├── server.py            # Mitmproxy DumpMaster & traffic scope management
│   │   └── dashboard.py         # Internal metrics dashboard API
│   └── tests/                   # Pytest test suite (87 tests)
├── frontend/                    # Modern React Web Dashboard (React + Vite + TypeScript)
│   ├── src/                     # UI components, state hooks, traffic viewers
│   └── nginx.conf               # Nginx production web server configuration
├── scripts/                     # Operational & utility scripts (e.g. shortcut creators)
├── docs/                        # Architecture documentation & AI Developer Changelog
└── docker-compose.yml           # Multi-container orchestration (App, UI, Database)
```

---

## 📜 License

This project is licensed under the **MIT License**. Contributions, issues, and feature requests are welcome!
