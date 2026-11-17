"""Entry point for running as: python -m proxify or python backend/proxify/__main__.py"""
import multiprocessing
import os
import sys
from pathlib import Path

# Direct execution bootstrap: ensure backend/ directory is on sys.path
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Safe multiprocessing bootstrap for Windows standalone executables
multiprocessing.freeze_support()

# Early PyO3 builtins patch before any third-party imports
from proxify.utils.compat import (
    _patch_nuitka_pyo3_builtins,
    get_application_base_dir,
    get_default_ca_cert_path,
    get_default_db_path,
    get_outer_executable_path,
    install_windows_ca_certificate,
    is_compiled_executable,
    setup_headless_logging,
)

_patch_nuitka_pyo3_builtins()

import argparse
import asyncio
import ctypes
import logging
import subprocess
import threading
from ctypes import wintypes
from dotenv import load_dotenv

_exe_env = Path(get_default_db_path()).resolve().parent / ".env"
if _exe_env.is_file():
    load_dotenv(_exe_env)
load_dotenv()


def _install_ca_with_autogen(custom_cert: str | None = None) -> tuple[bool, Path]:
    cert_path = Path(custom_cert) if custom_cert else get_default_ca_cert_path()
    if not cert_path.is_file():
        try:
            from mitmproxy.certs import CertStore

            mitm_dir = Path.home() / ".mitmproxy"
            mitm_dir.mkdir(parents=True, exist_ok=True)
            CertStore.from_store(mitm_dir, "mitmproxy")
        except Exception as e:
            logging.debug("CertStore auto-generation skipped: %s", e)

    if not cert_path.is_file():
        return False, cert_path
    return install_windows_ca_certificate(cert_path), cert_path


def _should_auto_detach(args: argparse.Namespace) -> bool:
    """Detect interactive Git Bash / mintty launches of compiled binary to detach cleanly."""
    if sys.platform != "win32" or not is_compiled_executable():
        return False
    if any((
        args.console,
        args.no_tray,
        args.tray_worker,
        args.install_ca,
        args.stop,
        os.getenv("PROXIFY_FOREGROUND") == "1",
        bool(os.getenv("PYTEST_CURRENT_TEST")),
    )):
        return False
    return bool(os.getenv("MSYSTEM") or os.getenv("TERM_PROGRAM") == "mintty")


def _spawn_detached_tray_worker(raw_argv: list[str]) -> None:
    """Spawn background `--tray-worker` completely detached from the current terminal."""
    exe_path = str(get_outer_executable_path())
    filtered_args = [arg for arg in raw_argv if arg != "--tray-worker"]
    cmd = [exe_path, "--tray-worker", *filtered_args]

    detached_process = 0x00000008
    create_new_process_group = 0x00000200
    create_no_window = 0x08000000
    create_breakaway_from_job = 0x01000000
    base_flags = detached_process | create_new_process_group | create_no_window

    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=base_flags | create_breakaway_from_job,
        )
    except OSError:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=base_flags,
        )


def _mutex_name(proxy_port: int, dashboard_port: int) -> str:
    return f"Local\\ProxifyInstance_{proxy_port}_{dashboard_port}"


def _is_instance_running(proxy_port: int, dashboard_port: int) -> bool:
    if sys.platform != "win32":
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenMutexW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    handle = k32.OpenMutexW(0x00100000, False, _mutex_name(proxy_port, dashboard_port))
    if handle:
        k32.CloseHandle(handle)
        return True
    return False


def _acquire_single_instance_mutex(proxy_port: int, dashboard_port: int):
    """Acquire a Windows named mutex scoped to proxy+dashboard ports. Returns handle or None if duplicate."""
    if sys.platform != "win32":
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    handle = k32.CreateMutexW(None, False, _mutex_name(proxy_port, dashboard_port))
    err = ctypes.get_last_error()
    if err == 183:  # ERROR_ALREADY_EXISTS
        if handle:
            k32.CloseHandle(handle)
        return None
    return handle


def _release_single_instance_mutex(handle) -> None:
    if sys.platform == "win32" and handle and handle is not True:
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle.restype = wintypes.BOOL
            k32.CloseHandle(handle)
        except Exception:
            pass


def _attach_or_alloc_windows_console() -> None:
    """Ensure a visible console is attached when --console is explicitly requested on a GUI build."""
    if sys.platform != "win32":
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.AttachConsole.argtypes = [wintypes.DWORD]
    k32.AttachConsole.restype = wintypes.BOOL
    k32.AllocConsole.argtypes = []
    k32.AllocConsole.restype = wintypes.BOOL
    if not k32.AttachConsole(0xFFFFFFFF):  # ATTACH_PARENT_PROCESS
        k32.AllocConsole()
    try:
        if sys.stdout is None:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        if sys.stderr is None:
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except Exception:
        pass


def _stop_running_instances() -> int:
    """Gracefully stop background proxify.exe instances (and fall back to taskkill)."""
    if sys.platform != "win32":
        return 0
    import csv
    import io
    import time

    def _list_other_proxify_pids() -> list[int]:
        current_pid = os.getpid()
        parent_pid = os.getppid()
        res = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq proxify.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        found: list[int] = []
        for row in csv.reader(io.StringIO(res.stdout or "")):
            if len(row) >= 2 and row[1].isdigit():
                pid = int(row[1])
                if pid not in (current_pid, parent_pid):
                    found.append(pid)
        return found

    pids = _list_other_proxify_pids()
    if not pids:
        if sys.stdout is not None:
            print("Không có tiến trình proxify.exe nào đang chạy ngầm.")
        return 0

    # Ask any active System Tray hidden windows to quit gracefully (removes tray icon + flushes DB)
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.FindWindowExW.restype = wintypes.HWND
        u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u32.PostMessageW.restype = wintypes.BOOL
        hwnd = None
        for _ in range(16):
            hwnd = u32.FindWindowExW(None, hwnd, None, "Proxify Tray Hidden Window")
            if not hwnd:
                break
            u32.PostMessageW(hwnd, 0x0111, 1005, 0)  # WM_COMMAND, CMD_QUIT
    except Exception:
        pass

    deadline = time.monotonic() + 3.0
    remaining = pids
    while remaining and time.monotonic() < deadline:
        time.sleep(0.2)
        remaining = _list_other_proxify_pids()

    for pid in remaining:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)

    if sys.stdout is not None:
        print(f"Đã dừng {len(pids)} tiến trình proxify.exe (PID: {', '.join(map(str, pids))}).")
    return len(pids)


def _open_dashboard_browser(dashboard_port: int) -> None:
    url = f"http://localhost:{dashboard_port}"
    try:
        if sys.platform == "win32":
            os.startfile(url)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Proxify - Request capture and interception proxy")
    parser.add_argument(
        "--install-ca",
        action="store_true",
        help="Install Mitmproxy Root CA certificate into Windows Certificate Store",
    )
    parser.add_argument(
        "--cert-path",
        type=str,
        default=None,
        help="Custom path to CA certificate (.cer/.pem)",
    )
    parser.add_argument(
        "--console",
        "--foreground",
        dest="console",
        action="store_true",
        help="Run in foreground console mode instead of detaching to System Tray",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Disable Windows System Tray icon",
    )
    parser.add_argument(
        "--tray-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop background proxify.exe instances",
    )
    args, _ = parser.parse_known_args()

    if args.install_ca:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        ok, cert_path = _install_ca_with_autogen(args.cert_path)
        if not cert_path.is_file():
            print(f"❌ Error: CA certificate not found at {cert_path}. Run Proxify once to generate it or specify --cert-path.")
            sys.exit(1)

        print(f"Installing Root CA certificate from: {cert_path}")
        if ok:
            print("✅ Mitmproxy Root CA successfully trusted in Windows CurrentUser Root Store.")
            sys.exit(0)
        else:
            print("❌ Failed to install Root CA into Windows Certificate Store.")
            sys.exit(1)

    if args.stop:
        _stop_running_instances()
        sys.exit(0)

    proxy_port = int(os.environ.get("PROXY_PORT", 8080))
    dashboard_port = int(os.environ.get("DASHBOARD_PORT", 8888))

    if _should_auto_detach(args):
        if _is_instance_running(proxy_port, dashboard_port):
            _open_dashboard_browser(dashboard_port)
            if sys.stdout is not None:
                print(f"Proxify đã đang chạy ngầm. Đang mở Dashboard tại http://localhost:{dashboard_port}")
            sys.exit(0)
        _spawn_detached_tray_worker(sys.argv[1:])
        if sys.stdout is not None:
            print(
                f"✅ Proxify đã chạy ngầm dưới khay hệ thống (System Tray) — "
                f"Proxy: 127.0.0.1:{proxy_port} | Dashboard: http://localhost:{dashboard_port}"
            )
        sys.exit(0)

    if args.console:
        _attach_or_alloc_windows_console()

    tray_enabled = (
        sys.platform == "win32"
        and not args.no_tray
        and not args.console
        and os.getenv("PROXIFY_NO_TRAY") != "1"
        and not os.getenv("PYTEST_CURRENT_TEST")
    )

    mutex_handle = None
    if tray_enabled:
        mutex_handle = _acquire_single_instance_mutex(proxy_port, dashboard_port)
        if mutex_handle is None:
            _open_dashboard_browser(dashboard_port)
            sys.exit(0)

    _patch_nuitka_pyo3_builtins()

    log_path = get_application_base_dir() / "proxify.log"
    has_live_console = setup_headless_logging(log_path, force_file_log=args.tray_worker)
    if has_live_console:
        logging.basicConfig(level=logging.INFO)

    tray = None
    master_ref: dict[str, object] = {"master": None}
    quit_requested = threading.Event()

    def _on_tray_quit() -> None:
        quit_requested.set()
        m = master_ref.get("master")
        if m is not None:
            try:
                m.shutdown()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _on_master_ready(master, _loop) -> None:
        master_ref["master"] = master
        if quit_requested.is_set():
            master.shutdown()

    if tray_enabled:
        from proxify.utils.tray import WindowsSystemTray

        tray = WindowsSystemTray(
            proxy_port=proxy_port,
            dashboard_port=dashboard_port,
            log_path=log_path,
            on_quit=_on_tray_quit,
            on_install_ca=lambda: _install_ca_with_autogen(None)[0],
        )
        tray.start()

    from proxify.server import run_server
    try:
        asyncio.run(run_server(on_master_ready=_on_master_ready, enable_termlog=has_live_console))
    except KeyboardInterrupt:
        logging.info("Exited.")
    finally:
        if tray is not None:
            tray.stop()
        _release_single_instance_mutex(mutex_handle)


if __name__ == "__main__":
    main()
