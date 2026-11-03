# Stage 1: Build Pure Rust Workspace
FROM rust:slim-bookworm AS builder

WORKDIR /workspace

RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY crates ./crates
COPY tests ./tests
COPY benches ./benches

RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/workspace/target \
    cargo build --release -p proxify-server && \
    cp /workspace/target/release/proxify-server /usr/local/bin/proxify-server

# Stage 2: Minimal Runtime Container
FROM debian:bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    openssl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/proxify-server /usr/local/bin/proxify-server
COPY private/extensions /app/extensions

EXPOSE 8080 8888

ENV PROXY_HOST=0.0.0.0
ENV PROXY_PORT=8080
ENV DASHBOARD_PORT=8888
ENV PROXIFY_EXTENSIONS_DIR=/app/extensions
ENV PROXIFY_CA_DIR=/root/.mitmproxy

CMD ["proxify-server"]
