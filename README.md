<h1 align="center">
    <br>
    <img alt="Proxify Logo" src="assets/logo.png" width="150" style="border-radius: 20px;">
    <br>
    Proxify
    <br>
    <small>The Ultimate Request Capture & Proxy Framework</small>
</h1>

<p align="center">
    <strong>English</strong> | <a href="README_vi.md">Tiếng Việt</a>
</p>

<p align="center">
    <a href="https://python.org" alt="Python version">
        <img alt="Python version" src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python"></a>
    <a href="https://mitmproxy.org/" alt="Mitmproxy">
        <img alt="Mitmproxy version" src="https://img.shields.io/badge/Mitmproxy-10.1%2B-red?style=flat-square"></a>
    <a href="https://postgresql.org" alt="PostgreSQL">
        <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-Ready-336791?style=flat-square&logo=postgresql"></a>
    <a href="#" alt="License">
        <img alt="License" src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square"></a>
</p>

<p align="center">
    <a href="#core-features"><strong>Features</strong></a>
    &middot;
    <a href="#quick-start"><strong>Quick Start</strong></a>
    &middot;
    <a href="#platforms"><strong>Platforms</strong></a>
    &middot;
    <a href="#dashboard"><strong>Dashboard</strong></a>
    &middot;
    <a href="#cli"><strong>CLI</strong></a>
</p>

**Proxify** is a powerful HTTP/HTTPS request interception and analysis framework built on top of `mitmproxy`.

Designed to run silently in the background, it automatically collects, parses, and stores requests from various platforms (Zalo, Facebook, Shopee, etc.) into a PostgreSQL database for Data Extraction, Analytics, or Reverse Engineering.

The system is multi-threaded, memory-optimized, and comes with a real-time Web Dashboard. Capture everything, without missing a single byte!

```python
# Powerful integration with multiple Platforms
from proxify.platforms.zalo import zalo_db

# Automatically store extracted data into PostgreSQL
zalo_db.groups.upsert(
    group_id="12345", 
    name="Data Extraction Group", 
    members=150
)
```

Or run the powerful CLI Server mode:

```bash
# Start proxy server on port 9090 and monitor facebook.com
python -m proxify --port 9090 --dashboard-port 9999 --domain facebook.com
```

---

## 🚀 Quick Start

Getting started is extremely simple.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment variables
cp .env.example .env
# Edit your .env file with your specific DB_DSN, PROXY_PORT, etc.

# 3. Start Proxify
python -m proxify
```
> ⚠️ **Important**: Once the system is running, you **must manually configure the Proxy** on your browser or phone:
> - **Host:** `127.0.0.1` (if running on the same machine) or your machine's LAN IP (if using a phone).
> - **Port:** `8080`
> 
> Finally, navigate to `http://mitm.it` in that browser to download and install the HTTPS certificate.

## 🛡️ Core Features

- **Stealthy Request Capture**: Listens and extracts data from traffic passing through the proxy without interfering with the user's main data flow.
- **HTTP/2 Support**: Ready to capture ultra-fast HTTP/2 streams, or force downgrade to HTTP/1.1 (to avoid 502 errors on strict platforms).
- **PostgreSQL Connection Pool**: Built-in, industry-standard `ThreadedConnectionPool` for safe, multi-threaded data storage.
- **Real-time Dashboard**: Monitor traffic, configure proxy settings, and view logs directly from your browser—no need to stare at the terminal console.
- **Highly Extensible**: Mitmproxy's Addon architecture allows you to easily write custom parsing logic for specific domains (Platforms).

## 📂 Directory Structure (Architecture)

The codebase follows strict **SOLID** principles, utilizing **Dependency Injection**, **Event-Driven Architecture (Pub/Sub)**, and the **Repository Pattern** to ensure high maintainability and performance.

```text
proxify/
├── __main__.py             # CLI Entry point
├── server.py               # Starts mitmproxy and registers Event Listeners
├── capture_addon.py        # Core Proxy Interceptor. Emits `response_captured` events
├── storage.py              # Background worker for Bulk Database inserts
├── core/                   # 🧠 Core Event-Driven Engine
│   ├── events.py           # EventBus (Publisher/Subscriber logic)
│   ├── interfaces.py       # Typing Protocols (e.g., EventListener)
│   └── listeners.py        # Subscribers (DashboardBroadcaster, DatabaseWriter)
├── database/               # 💾 Database Management
│   ├── connection.py       # Shared singleton PostgreSQL ThreadedConnectionPool
│   └── setup.py            # Initial DB schema setups
├── platforms/              # 🌐 Platform-specific Data Extractors
│   ├── facebook/           
│   │   ├── database.py     # Facebook Database Facade
│   │   ├── repository.py   # Repository Pattern for Authors, Posts, Comments
│   │   └── extractor.py    # Background script to parse raw requests into structured data
│   └── zalo/               # (Similar Repository structure as Facebook)
├── plugins/                # 🔌 Drop-in plugins for extended proxy functionality
└── utils/                  # 🛠️ Helper functions (e.g., GraphQL parsing)
```

### 🔌 Plugin Architecture (Open/Closed Principle)

Proxify utilizes a dynamic Plugin Architecture to ensure the core interceptor (`capture_addon.py`) remains extremely lightweight and completely decoupled from domain-specific logic.

- **Open for Extension:** To capture data from a new platform (e.g., TikTok, Shopee), simply drop a new file into the `plugins/` directory and use the `@register_plugin("name")` decorator.
- **Closed for Modification:** You never need to modify the core `capture_addon.py` file to add new functionality. The system automatically discovers and routes matching network flows to your plugin based on the `target_domains` you define.

Plugins can also inject their own API routes and UI tabs directly into the web Dashboard!

## 🆘 Troubleshooting

### Docker Desktop on Windows: "Only one usage of each socket address"

If you encounter an infinite loop error (`connectex: Only one usage of each socket address`) when connecting to the proxy, it is highly likely that Docker Desktop is inheriting your Windows Proxy settings, causing the proxy to forward requests to itself.

**Solution:**
1. Open **Docker Desktop**.
2. Go to **Settings** (Gear icon) -> **Resources** -> **Proxies**.
3. Under **Containers proxy**, change the setting from `Same as host proxy` to **`No proxy`**.
4. Click **Apply & Restart**.

Once Docker restarts, the container will be able to connect to the internet normally without creating an infinite loop.
