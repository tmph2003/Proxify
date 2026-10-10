"""
System Stability & End-to-End Network Reliability Verification Script for Proxify.

Tests:
1. Docker container health (proxify_app, proxify_ui, proxify_db) and ports 8080 / 8888 reachability.
2. Proxy connectivity to YouTube (HTTP 200, streaming functional).
3. Direct passthrough / bypass for Google Workspace and GitHub (genuine TLS certs, 0 SSL errors).
4. Windows ProxyOverride and WinHTTP bypass synchronization.
5. Full regression test execution (all 72 existing backend tests pass).
"""

import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def log_pass(msg: str):
    print(f"  {Colors.GREEN}[PASS]{Colors.RESET} {msg}")


def log_fail(msg: str):
    print(f"  {Colors.RED}[FAIL]{Colors.RESET} {msg}")


def log_info(msg: str):
    print(f"  {Colors.BLUE}[INFO]{Colors.RESET} {msg}")


def log_section(title: str):
    print(f"\n{Colors.BOLD}{Colors.YELLOW}=== {title} ==={Colors.RESET}")


def check_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Checks if a TCP port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def test_docker_health() -> bool:
    """1. Docker container health and port 8080 / 8888 reachability."""
    log_section("1. Docker Container Health & Service Reachability")
    all_ok = True

    # 1.1 Check docker compose ps
    try:
        proc = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        containers = []
        raw = proc.stdout.strip()
        if raw:
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        expected_services = {"proxify": "proxify_app", "ui": "proxify_ui", "db": "proxify_db"}
        found_services = {}

        for c in containers:
            name = c.get("Name", "")
            service = c.get("Service", "")
            status = c.get("Status", "")
            health = c.get("Health", "")
            state = c.get("State", "")
            
            # Docker json formats health in different fields depending on version
            is_healthy = "healthy" in status.lower() or "healthy" in health.lower()
            is_running = state.lower() == "running" or "up" in status.lower()

            for s_key, s_name in expected_services.items():
                if name == s_name or service == s_key:
                    found_services[s_name] = (is_running, is_healthy, status)

        for s_name in expected_services.values():
            if s_name in found_services:
                is_running, is_healthy, status_str = found_services[s_name]
                if is_running and is_healthy:
                    log_pass(f"Container '{s_name}' is running and healthy ({status_str})")
                else:
                    log_fail(f"Container '{s_name}' status: running={is_running}, healthy={is_healthy} ({status_str})")
                    all_ok = False
            else:
                log_fail(f"Container '{s_name}' not found in docker compose ps")
                all_ok = False

    except Exception as e:
        log_fail(f"Error checking docker compose ps: {e}")
        all_ok = False

    # 1.2 Check TCP reachability for 8080 and 8888
    if check_port("127.0.0.1", 8080):
        log_pass("Proxy port 8080 is reachable")
    else:
        log_fail("Proxy port 8080 is NOT reachable")
        all_ok = False

    if check_port("127.0.0.1", 8888):
        log_pass("Dashboard port 8888 is reachable")
    else:
        log_fail("Dashboard port 8888 is NOT reachable")
        all_ok = False

    # 1.3 Verify /api/health endpoint on 8888
    try:
        req = urllib.request.Request("http://127.0.0.1:8888/api/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "healthy":
                log_pass(f"Dashboard /api/health responded: {data}")
            else:
                log_fail(f"Dashboard /api/health unexpected response: {data}")
                all_ok = False
    except Exception as e:
        log_fail(f"Error querying /api/health: {e}")
        all_ok = False

    # 1.4 Verify /api/config endpoint on 8888
    try:
        req = urllib.request.Request("http://127.0.0.1:8888/api/config")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "retention_days" in data and "db_integration_enabled" in data:
                log_pass(f"Dashboard /api/config responded: {data}")
            else:
                log_fail(f"Dashboard /api/config unexpected response: {data}")
                all_ok = False
    except Exception as e:
        log_fail(f"Error querying /api/config: {e}")
        all_ok = False

    return all_ok


def test_youtube_proxy() -> bool:
    """2. Proxy connectivity to YouTube (HTTP 200, streaming functional)."""
    log_section("2. YouTube Enhancer Stability & Streaming Compatibility")
    all_ok = True

    # 2.1 curl to https://www.youtube.com through proxy 127.0.0.1:8080
    try:
        proc = subprocess.run(
            ["curl.exe", "-x", "127.0.0.1:8080", "-s", "-I", "https://www.youtube.com"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = proc.stdout
        if "HTTP/1.1 200" in output or "HTTP/2 200" in output or "HTTP/1.1 302" in output:
            log_pass("curl -x 127.0.0.1:8080 -I https://www.youtube.com returned HTTP 200/302 successfully")
        else:
            log_fail(f"curl -x 127.0.0.1:8080 -I https://www.youtube.com unexpected output:\n{output}\nStderr: {proc.stderr}")
            all_ok = False
    except Exception as e:
        log_fail(f"Error connecting to YouTube via proxy: {e}")
        all_ok = False

    # 2.2 Verify googlevideo.com streaming route handling
    try:
        # Test connecting to googlevideo.com through proxy
        proc = subprocess.run(
            ["curl.exe", "-x", "127.0.0.1:8080", "-s", "-I", "https://redirector.googlevideo.com/videoplayback"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = proc.stdout
        # Expect 400 Bad Request or 403 Forbidden or 302 from googlevideo without params, but connection must succeed
        if "HTTP/1.1" in output or "HTTP/2" in output:
            first_line = output.splitlines()[0] if output.splitlines() else ""
            log_pass(f"googlevideo.com stream endpoint reached cleanly through proxy: {first_line}")
        else:
            log_fail(f"googlevideo.com connection failed:\n{output}\nStderr: {proc.stderr}")
            all_ok = False
    except Exception as e:
        log_fail(f"Error connecting to googlevideo.com via proxy: {e}")
        all_ok = False

    return all_ok


def test_passthrough_and_bypass() -> bool:
    """3. Direct passthrough / bypass for Google Workspace and GitHub."""
    log_section("3. Direct Passthrough / System Bypass (Google Workspace & GitHub)")
    all_ok = True

    # 3.1 Test mail.google.com via proxy
    try:
        proc = subprocess.run(
            ["curl.exe", "-x", "127.0.0.1:8080", "-s", "-I", "https://mail.google.com"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = proc.stdout
        if "HTTP/1.1 200 Connection established" in output and ("HTTP/1.1 301" in output or "HTTP/1.1 200" in output):
            log_pass("curl -x 127.0.0.1:8080 -I https://mail.google.com passed through directly (0 SSL errors)")
        else:
            log_fail(f"curl mail.google.com failed passthrough:\n{output}\nStderr: {proc.stderr}")
            all_ok = False
    except Exception as e:
        log_fail(f"Error testing mail.google.com passthrough: {e}")
        all_ok = False

    # 3.2 Test github.com via proxy
    try:
        proc = subprocess.run(
            ["curl.exe", "-x", "127.0.0.1:8080", "-s", "-I", "https://github.com"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = proc.stdout
        if "HTTP/1.1 200 Connection established" in output and ("HTTP/1.1 200 OK" in output or "HTTP/2 200" in output):
            log_pass("curl -x 127.0.0.1:8080 -I https://github.com passed through directly (0 SSL errors)")
        else:
            log_fail(f"curl github.com failed passthrough:\n{output}\nStderr: {proc.stderr}")
            all_ok = False
    except Exception as e:
        log_fail(f"Error testing github.com passthrough: {e}")
        all_ok = False

    # 3.3 Verify genuine TLS certificate extraction via TCP CONNECT through 127.0.0.1:8080
    for target_host in ["mail.google.com", "github.com"]:
        try:
            s = socket.create_connection(("127.0.0.1", 8080), timeout=5)
            connect_cmd = f"CONNECT {target_host}:443 HTTP/1.1\r\nHost: {target_host}:443\r\n\r\n"
            s.sendall(connect_cmd.encode("utf-8"))
            resp = s.recv(4096).decode("latin-1")
            if "200 Connection established" not in resp:
                log_fail(f"CONNECT to {target_host} rejected: {resp}")
                all_ok = False
                s.close()
                continue

            ctx = ssl.create_default_context()
            with ctx.wrap_socket(s, server_hostname=target_host) as ss:
                cert = ss.getpeercert()
                issuer_dict = dict(x[0] for x in cert.get("issuer", []))
                issuer_o = issuer_dict.get("organizationName", "")
                issuer_cn = issuer_dict.get("commonName", "")
                
                # mitmproxy certs have Organization = 'mitmproxy'
                if "mitmproxy" in issuer_o.lower() or "mitmproxy" in issuer_cn.lower():
                    log_fail(f"Certificate for {target_host} is MITM decrypted by mitmproxy! Expected genuine cert.")
                    all_ok = False
                else:
                    log_pass(f"Genuine TLS cert verified for {target_host}: Issuer={issuer_o} ({issuer_cn})")
        except Exception as e:
            log_fail(f"TLS certificate check for {target_host} failed: {e}")
            all_ok = False

    # 3.4 Verify Windows ProxyOverride & WinHTTP synchronization
    try:
        ps_cmd = 'Get-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" | Select-Object -ExpandProperty ProxyOverride'
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, check=True)
        reg_override = proc.stdout.strip().lower()

        proc2 = subprocess.run(["netsh", "winhttp", "show", "proxy"], capture_output=True, text=True, check=True)
        winhttp_output = proc2.stdout.lower()

        required_bypass_keywords = [
            "mail.google.com",
            "chat.google.com",
            "accounts.google.com",
            "clients6.google.com",
            "drive.google.com",
            "github.com",
            "githubassets.com",
            "githubusercontent.com",
            "zadn.vn",
            "zing.vn",
            "microsoft.com",
            "windowsupdate.com",
        ]

        missing_reg = [k for k in required_bypass_keywords if k not in reg_override]
        missing_winhttp = [k for k in required_bypass_keywords if k not in winhttp_output]

        if not missing_reg:
            log_pass(f"Registry ProxyOverride contains all required bypass domains ({len(required_bypass_keywords)} verified)")
        else:
            log_fail(f"Registry ProxyOverride is missing: {missing_reg}")
            all_ok = False

        if not missing_winhttp:
            log_pass(f"WinHTTP Bypass List contains all required bypass domains ({len(required_bypass_keywords)} verified)")
        else:
            log_fail(f"WinHTTP Bypass List is missing: {missing_winhttp}")
            all_ok = False

        # Ensure Zalo Web (chat.zalo.me) is NOT bypassed
        if "chat.zalo.me" in reg_override or "*.zalo.me" in reg_override:
            log_fail("Registry ProxyOverride contains Zalo Web bypass (*.zalo.me or chat.zalo.me), which blocks interception!")
            all_ok = False
        else:
            log_pass("Registry ProxyOverride correctly does NOT bypass Zalo Web (chat.zalo.me is intercepted)")

    except Exception as e:
        log_fail(f"Error checking Windows ProxyOverride settings: {e}")
        all_ok = False

    # 3.5 Verify ProxyRouter strict domain boundary isolation
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
        from proxify.core.router import ProxyRouter
        test_router = ProxyRouter(ignored_hosts=[
            "github.com",
            "mail.google.com",
            "zadn.vn",
            "zing.vn",
            "microsoft.com",
        ])
        obs_none, mut_none = test_router._search(None)
        if (test_router.is_ignored("github.com") and
            test_router.is_ignored("github.com:443") and
            test_router.is_ignored("api.github.com") and
            test_router.is_ignored("api.github.com:443") and
            not test_router.is_ignored("fake-github.com") and
            not test_router.is_ignored("amazing.vn") and
            not test_router.is_ignored("evilmicrosoft.com") and
            not test_router.is_ignored(None) and
            isinstance(obs_none, list)):
            log_pass("ProxyRouter strict domain boundary isolation verified (ports normalized & lookalikes rejected)")
        else:
            log_fail("ProxyRouter boundary isolation failed: lookalike domain matched or port normalization failed!")
            all_ok = False
    except Exception as e:
        log_fail(f"Error verifying ProxyRouter boundary isolation: {e}")
        all_ok = False

    return all_ok


def test_regression_suite() -> bool:
    """4. Full execution of existing 72 backend unit/integration tests without regression."""
    log_section("4. Backend Test Suite Execution (Regression Safety)")
    backend_dir = Path(__file__).resolve().parent.parent / "backend"

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "extensions"],
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = proc.stdout
        passed_match = re.search(r"(\d+) passed", output)
        passed_count = int(passed_match.group(1)) if passed_match else 0

        if proc.returncode == 0 and passed_count >= 72:
            log_pass(f"All {passed_count} backend tests passed successfully (exit code 0)")
            return True
        else:
            log_fail(f"Pytest failed with exit code {proc.returncode} (passed: {passed_count}):\n{output}\nStderr: {proc.stderr}")
            return False
    except Exception as e:
        log_fail(f"Error running pytest suite: {e}")
        return False


def main():
    print(f"{Colors.BOLD}{Colors.BLUE}======================================================{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE} Proxify Comprehensive System Stability Verification   {Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}======================================================{Colors.RESET}")

    results = [
        ("Docker Health & Ports", test_docker_health()),
        ("YouTube Enhancer & Streaming", test_youtube_proxy()),
        ("Passthrough & Bypass Boundary", test_passthrough_and_bypass()),
        ("Backend Regression Suite", test_regression_suite()),
    ]

    log_section("Summary Verification Report")
    all_passed = True
    for name, passed in results:
        status_text = f"{Colors.GREEN}PASSED{Colors.RESET}" if passed else f"{Colors.RED}FAILED{Colors.RESET}"
        print(f"  - {name.ljust(35)}: {status_text}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 54)
    if all_passed:
        print(f"{Colors.BOLD}{Colors.GREEN}✅ ALL SYSTEM STABILITY VERIFICATION CHECKS PASSED!{Colors.RESET}")
        sys.exit(0)
    else:
        print(f"{Colors.BOLD}{Colors.RED}❌ SYSTEM STABILITY VERIFICATION DETECTED FAILURES!{Colors.RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
