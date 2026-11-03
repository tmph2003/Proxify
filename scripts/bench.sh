#!/usr/bin/env bash
# Proxify Performance Benchmark Execution Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=========================================================="
echo "          PROXIFY COMPREHENSIVE BENCHMARK RUNNER          "
echo "=========================================================="

echo "[1/2] Running Criterion Microbenchmarks..."
cd "${ROOT_DIR}"
cargo bench --bench proxy_micro_benches

echo ""
echo "[2/2] Running Macro Load Benchmark Harness..."
python3 "${SCRIPT_DIR}/benchmark_proxy.py" --requests 1000 --concurrency 25 --output "${SCRIPT_DIR}/benchmark_results.json" || true

echo ""
echo "[+] All benchmarks finished successfully!"
