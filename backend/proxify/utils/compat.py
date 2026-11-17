"""
Runtime Compatibility & Platform Helpers — Proxify.

Provides unified environment path resolution across development, PyInstaller,
and Nuitka compiled executables; early PyO3 builtins runtime monkeypatching;
and Windows Root Certificate Store installation helper.
"""

import builtins
import logging
import logging.handlers
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("proxify.utils.compat")


def is_compiled_executable() -> bool:
    """Return True when running from a frozen/compiled standalone executable (Nuitka/PyInstaller)."""
    if getattr(sys, "frozen", False):
        return True
    compiled_info = globals().get("__compiled__", getattr(builtins, "__compiled__", None))
    return compiled_info is not None


def get_outer_executable_path() -> Path:
    """Return the outer executable path (respecting Nuitka onefile original_argv0)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    compiled_info = globals().get("__compiled__", getattr(builtins, "__compiled__", None))
    if compiled_info is not None:
        orig = getattr(compiled_info, "original_argv0", None)
        if orig:
            p = Path(orig)
            return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
    return Path(sys.executable).resolve()


class _SafeLogStream:
    """Minimal writable file-backed stream for headless GUI subsystems when stdout/stderr is None."""

    _is_proxify_log_stream = True

    def __init__(self, log_path: Path):
        self._log_path = Path(log_path)
        self.encoding = "utf-8"

    def write(self, msg: str) -> int:
        if not msg:
            return 0
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8", errors="replace") as f:
                f.write(msg)
            return len(msg)
        except Exception:
            return 0

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def setup_headless_logging(log_path: Path, force_file_log: bool = False) -> bool:
    """Configure UTF-8 rotating file logging and guard None stdout/stderr in GUI builds.

    Returns:
        True if live stdout/stderr console streams are attached (suitable for termlog),
        False if running headless (GUI subsystem with None streams or forced background log).
    """
    has_live_console = (
        sys.stdout is not None
        and sys.stderr is not None
        and not getattr(sys.stdout, "_is_proxify_log_stream", False)
        and not force_file_log
    )

    if not has_live_console or force_file_log:
        resolved_log = Path(log_path)
        resolved_log.parent.mkdir(parents=True, exist_ok=True)

        safe_stream = _SafeLogStream(resolved_log)
        if sys.stdout is None:
            sys.stdout = safe_stream  # type: ignore[assignment]
        if sys.stderr is None:
            sys.stderr = safe_stream  # type: ignore[assignment]

        root_logger = logging.getLogger()
        already_attached = any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            and Path(getattr(h, "baseFilename", "")) == resolved_log.resolve()
            for h in root_logger.handlers
        )
        if not already_attached:
            file_handler = logging.handlers.RotatingFileHandler(
                filename=str(resolved_log),
                maxBytes=5 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
            root_logger.addHandler(file_handler)
        if root_logger.level == logging.NOTSET:
            root_logger.setLevel(logging.INFO)

    return has_live_console


def get_application_base_dir() -> Path:
    """Resolve the true application base directory across all runtime environments.

    Resolution order:
    1. PROXIFY_DB_PATH environment variable (returns its parent directory if set)
    2. sys.frozen (PyInstaller / cx_Freeze standalone executable)
    3. __compiled__ (Nuitka standalone / onefile executable)
    4. Default fallback: Path.cwd() (standard Python development mode)
    """
    env_db = os.getenv("PROXIFY_DB_PATH")
    if env_db:
        p = Path(env_db)
        return p.resolve().parent if p.is_absolute() else (Path.cwd() / p).resolve().parent

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    compiled_info = globals().get("__compiled__", getattr(builtins, "__compiled__", None))
    if compiled_info is not None:
        orig = getattr(compiled_info, "original_argv0", None)
        if orig:
            p = Path(orig)
            return p.resolve().parent if p.is_absolute() else (Path.cwd() / p).resolve().parent
        return Path(sys.executable).resolve().parent

    return Path.cwd()


def get_default_db_path() -> str:
    """Return the absolute path to the default SQLite database file.

    If PROXIFY_DB_PATH is set in environment, returns that directly.
    Otherwise returns 'proxify.db' located inside get_application_base_dir().
    """
    env_path = os.getenv("PROXIFY_DB_PATH")
    if env_path:
        return env_path
    return str(get_application_base_dir() / "proxify.db")


def _patch_nuitka_pyo3_builtins() -> None:
    """Ensure every compiled/wrapped module dict contains '__builtins__'.

    Under Nuitka 4.x, C-compiled modules do not populate '__builtins__' in
    module.__dict__ unless referenced in Python source. Rust PyO3 extensions
    (such as cryptography called from OpenSSL.crypto during mitmproxy TLS
    handshakes) look up f_globals['__builtins__'] via PyObject_GetItem and
    raise KeyError: '__builtins__' if absent.

    This function is idempotent and safe to call multiple times.
    """
    bdict = builtins.__dict__

    def _stamp_module(mod) -> None:
        if mod is None:
            return
        for candidate in (mod, _unwrap_deprecated_module(mod)):
            if candidate is None:
                continue
            try:
                mdict = object.__getattribute__(candidate, "__dict__")
                if isinstance(mdict, dict) and "__builtins__" not in mdict:
                    mdict["__builtins__"] = bdict
            except Exception:
                pass

    def _unwrap_deprecated_module(mod):
        try:
            return object.__getattribute__(mod, "_module")
        except Exception:
            return None

    for existing in list(sys.modules.values()):
        _stamp_module(existing)

    try:
        import cryptography.utils as _cu
        _orig_mwd_init = getattr(_cu._ModuleWithDeprecations, "__init__", None)
        if _orig_mwd_init and not getattr(_orig_mwd_init, "_proxify_patched", False):
            def _patched_mwd_init(self, module):
                _stamp_module(module)
                _orig_mwd_init(self, module)

            _patched_mwd_init._proxify_patched = True  # type: ignore[attr-defined]
            _cu._ModuleWithDeprecations.__init__ = _patched_mwd_init
    except Exception:
        pass

    _orig_import = builtins.__import__
    if not getattr(_orig_import, "_proxify_builtins_patched", False):
        def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
            mod = _orig_import(name, globals, locals, fromlist, level)
            _stamp_module(mod)
            if name in sys.modules:
                _stamp_module(sys.modules[name])
            return mod

        _patched_import._proxify_builtins_patched = True  # type: ignore[attr-defined]
        builtins.__import__ = _patched_import


def install_windows_ca_certificate(cer_path: Path) -> bool:
    """Install a CA certificate (.cer/.pem) into the Windows CurrentUser Root Store.

    Uses Windows built-in `certutil.exe -user -addstore Root <path>`.
    Does not require Administrator privileges because it installs to CurrentUser Root.

    Args:
        cer_path: Path to the certificate file (.cer or .pem).

    Returns:
        True if successfully installed, False otherwise.
    """
    cer = Path(cer_path).resolve()
    if not cer.is_file():
        logger.error(f"Certificate file not found: {cer}")
        return False

    if sys.platform != "win32":
        logger.warning(f"install_windows_ca_certificate is only supported on Windows (current: {sys.platform})")
        return False

    try:
        cmd = ["certutil.exe", "-user", "-addstore", "Root", str(cer)]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        stdout_lower = (res.stdout or "").lower()
        if res.returncode == 0 or "command completed successfully" in stdout_lower:
            logger.info(f"Successfully added certificate {cer.name} to Windows CurrentUser Root store.")
            return True
        logger.error(f"certutil failed with returncode {res.returncode}: {res.stderr or res.stdout}")
        return False
    except FileNotFoundError:
        logger.error("certutil.exe not found on system PATH.")
        return False
    except Exception as e:
        logger.error(f"Failed to install CA certificate via certutil: {e}")
        return False


def get_default_ca_cert_path() -> Path:
    """Locate the default Mitmproxy CA certificate on the system."""
    candidates = [
        Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer",
        Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem",
        Path(get_default_db_path()).resolve().parent / "mitmproxy-ca-cert.cer",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]
