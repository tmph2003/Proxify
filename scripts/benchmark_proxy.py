#!/usr/bin/env python3
"""
Proxify Macro Benchmark & Load Testing Harness
Measures throughput (QPS), latency percentiles (p50, p90, p99), error rate, and memory footprint.
"""

import argparse
import http.client
import http.server
import json
import math
import os
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

class MockEchoHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"Proxify Echo OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b""
        resp = b"Received: " + post_body
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, format, *args):
        # Suppress noisy HTTP server logs during benchmark
        pass

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True

def start_mock_upstream():
    server = ThreadedTCPServer(("0.0.0.0", 0), MockEchoHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port

def send_request_via_proxy(proxy_host, proxy_port, target_url):
    start = time.perf_counter()
    conn = None
    try:
        conn = http.client.HTTPConnection(proxy_host, proxy_port, timeout=5)
        # Proxies require absolute URI in request line for standard HTTP
        conn.request("GET", target_url, headers={"User-Agent": "ProxifyBenchmark/2.0"})
        resp = conn.getresponse()
        _ = resp.read()
        latency_ms = (time.perf_counter() - start) * 1000.0
        success = (resp.status == 200)
        return (success, latency_ms, resp.status, None)
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return (False, latency_ms, 0, str(e))
    finally:
        if conn:
            conn.close()

def get_process_memory_mb():
    try:
        import subprocess
        res = subprocess.run(
            ["docker", "stats", "proxify_app", "--no-stream", "--format", "{{.MemUsage}}"],
            capture_output=True, text=True, timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            raw = res.stdout.strip().split("/")[0].strip()
            if "GiB" in raw:
                return float(raw.replace("GiB", "").strip()) * 1024.0
            elif "MiB" in raw:
                return float(raw.replace("MiB", "").strip())
            elif "KiB" in raw:
                return float(raw.replace("KiB", "").strip()) / 1024.0
    except Exception:
        pass
    try:
        # Linux /proc/self/status
        if os.path.exists("/proc/self/status"):
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        return float(parts[1]) / 1024.0
    except Exception:
        pass
    return 0.0

def calculate_percentile(sorted_data, percentile):
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1

def run_benchmark(proxy_url, total_requests, concurrency, output_file, mock_host="host.docker.internal"):
    print("=" * 65)
    print("        PROXIFY PERFORMANCE BENCHMARK HARNESS (MACRO)        ")
    print("=" * 65)

    proxy_parsed = urllib.parse.urlparse(proxy_url)
    proxy_host = proxy_parsed.hostname or "127.0.0.1"
    proxy_port = proxy_parsed.port or 8080

    print(f"[*] Target Proxy:    http://{proxy_host}:{proxy_port}")
    print(f"[*] Total Requests:  {total_requests}")
    print(f"[*] Concurrency:     {concurrency} worker threads")

    # Start ephemeral upstream mock server
    upstream_server, upstream_port = start_mock_upstream()
    target_url = f"http://{mock_host}:{upstream_port}/benchmark-endpoint"
    print(f"[*] Ephemeral Mock:  {target_url}")

    initial_mem_mb = get_process_memory_mb()

    # Pre-flight check
    print("[*] Running pre-flight connection check...")
    success, lat, status, err = send_request_via_proxy(proxy_host, proxy_port, target_url)
    if not success:
        print(f"[-] Pre-flight check failed! (status={status}, err={err})")
        print("    Ensure Proxify server is running or start it via: cargo run --bin proxify-server")
        print("    Recording baseline test result...")

    latencies = []
    success_count = 0
    failure_count = 0
    status_codes = {}

    bench_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(send_request_via_proxy, proxy_host, proxy_port, target_url)
            for _ in range(total_requests)
        ]
        for f in futures:
            ok, lat_ms, status_code, _ = f.result()
            latencies.append(lat_ms)
            status_codes[status_code] = status_codes.get(status_code, 0) + 1
            if ok:
                success_count += 1
            else:
                failure_count += 1

    bench_duration = time.perf_counter() - bench_start
    final_mem_mb = get_process_memory_mb()

    latencies.sort()
    qps = total_requests / bench_duration if bench_duration > 0 else 0.0

    p50 = calculate_percentile(latencies, 50.0)
    p90 = calculate_percentile(latencies, 90.0)
    p95 = calculate_percentile(latencies, 95.0)
    p99 = calculate_percentile(latencies, 99.0)
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    min_lat = latencies[0] if latencies else 0.0
    max_lat = latencies[-1] if latencies else 0.0

    print("-" * 65)
    print("                       BENCHMARK RESULTS                      ")
    print("-" * 65)
    print(f"Total Time Taken:        {bench_duration:.2f} s")
    print(f"Completed Requests:      {total_requests}")
    print(f"Successful Requests:     {success_count} ({success_count/total_requests*100:.1f}%)")
    print(f"Failed Requests:         {failure_count}")
    print(f"Throughput (QPS):        {qps:.2f} req/sec")
    print(f"Min Latency:             {min_lat:.2f} ms")
    print(f"Avg Latency:             {avg_lat:.2f} ms")
    print(f"p50 Median Latency:      {p50:.2f} ms")
    print(f"p90 Latency:             {p90:.2f} ms")
    print(f"p95 Latency:             {p95:.2f} ms")
    print(f"p99 Tail Latency:        {p99:.2f} ms")
    print(f"Max Latency:             {max_lat:.2f} ms")
    if final_mem_mb > 0:
        print(f"Memory Footprint:        {final_mem_mb:.2f} MB (Delta: {final_mem_mb - initial_mem_mb:+.2f} MB)")
    print("-" * 65)

    results = {
        "timestamp": time.time(),
        "proxy_url": proxy_url,
        "concurrency": concurrency,
        "total_requests": total_requests,
        "duration_sec": bench_duration,
        "throughput_qps": qps,
        "success_rate": success_count / total_requests if total_requests else 0,
        "status_distribution": status_codes,
        "latencies_ms": {
            "min": min_lat,
            "avg": avg_lat,
            "p50": p50,
            "p90": p90,
            "p95": p95,
            "p99": p99,
            "max": max_lat,
        },
        "memory_mb": {
            "initial": initial_mem_mb,
            "final": final_mem_mb,
        }
    }

    try:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"[+] Results saved to {output_file}")
    except Exception as e:
        print(f"[-] Could not save JSON report: {e}")

    upstream_server.shutdown()
    return 0 if failure_count == 0 else 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proxify Macro Load Benchmark Harness")
    parser.add_argument("--proxy", default="http://127.0.0.1:8080", help="Proxify HTTP proxy address")
    parser.add_argument("-n", "--requests", type=int, default=500, help="Total number of requests")
    parser.add_argument("-c", "--concurrency", type=int, default=20, help="Number of concurrent worker threads")
    parser.add_argument("--mock-host", default="host.docker.internal", help="Hostname of mock upstream as seen by proxy")
    parser.add_argument("-o", "--output", default="scripts/benchmark_results.json", help="Path to output JSON result")
    args = parser.parse_args()

    sys.exit(run_benchmark(args.proxy, args.requests, args.concurrency, args.output, args.mock_host))
