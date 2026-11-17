"""
Unit tests for runtime compatibility utilities and Windows packaging helpers.
"""

import builtins
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from proxify.utils.compat import (
    _patch_nuitka_pyo3_builtins,
    get_application_base_dir,
    get_default_ca_cert_path,
    get_default_db_path,
    install_windows_ca_certificate,
)


class TestApplicationPathResolver:
    """Tests for get_application_base_dir and get_default_db_path across runtime environments."""

    def test_env_var_absolute_db_path(self, monkeypatch, tmp_path):
        custom_db = tmp_path / "custom" / "my_proxify.db"
        monkeypatch.setenv("PROXIFY_DB_PATH", str(custom_db))

        base_dir = get_application_base_dir()
        db_path = get_default_db_path()

        assert base_dir == custom_db.parent.resolve()
        assert db_path == str(custom_db)

    def test_env_var_relative_db_path(self, monkeypatch):
        monkeypatch.setenv("PROXIFY_DB_PATH", "nested/data.db")

        base_dir = get_application_base_dir()
        db_path = get_default_db_path()

        assert base_dir == (Path.cwd() / "nested").resolve()
        assert db_path == "nested/data.db"

    def test_frozen_runtime_resolution(self, monkeypatch, tmp_path):
        fake_exe = tmp_path / "dist" / "proxify.exe"
        monkeypatch.delenv("PROXIFY_DB_PATH", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))

        base_dir = get_application_base_dir()
        db_path = get_default_db_path()

        assert base_dir == fake_exe.parent.resolve()
        assert db_path == str(fake_exe.parent.resolve() / "proxify.db")

    def test_compiled_nuitka_with_original_argv0(self, monkeypatch, tmp_path):
        fake_bin_dir = tmp_path / "nuitka_app"
        fake_bin_dir.mkdir(parents=True, exist_ok=True)
        fake_argv0 = str(fake_bin_dir / "proxify.exe")

        compiled_mock = types.SimpleNamespace(original_argv0=fake_argv0)
        monkeypatch.delenv("PROXIFY_DB_PATH", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setattr(builtins, "__compiled__", compiled_mock, raising=False)

        base_dir = get_application_base_dir()
        db_path = get_default_db_path()

        assert base_dir == fake_bin_dir.resolve()
        assert db_path == str(fake_bin_dir.resolve() / "proxify.db")

    def test_compiled_nuitka_fallback_to_executable(self, monkeypatch, tmp_path):
        fake_exe = tmp_path / "standalone" / "proxify.exe"
        compiled_mock = types.SimpleNamespace(original_argv0=None)

        monkeypatch.delenv("PROXIFY_DB_PATH", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        monkeypatch.setattr(builtins, "__compiled__", compiled_mock, raising=False)

        base_dir = get_application_base_dir()
        assert base_dir == fake_exe.parent.resolve()

    def test_dev_fallback_to_cwd(self, monkeypatch):
        monkeypatch.delenv("PROXIFY_DB_PATH", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        if hasattr(builtins, "__compiled__"):
            monkeypatch.delattr(builtins, "__compiled__")

        base_dir = get_application_base_dir()
        db_path = get_default_db_path()

        assert base_dir == Path.cwd()
        assert db_path == str(Path.cwd() / "proxify.db")


class TestWindowsCaCertificateInstaller:
    """Tests for install_windows_ca_certificate and get_default_ca_cert_path."""

    def test_missing_certificate_file_returns_false(self, tmp_path):
        non_existent = tmp_path / "missing.cer"
        assert not install_windows_ca_certificate(non_existent)

    def test_non_windows_platform_returns_false(self, monkeypatch, tmp_path):
        cert_file = tmp_path / "test.cer"
        cert_file.write_text("dummy cert", encoding="utf-8")

        monkeypatch.setattr(sys, "platform", "darwin")
        assert not install_windows_ca_certificate(cert_file)

    def test_successful_installation_on_windows(self, monkeypatch, tmp_path):
        cert_file = tmp_path / "test.cer"
        cert_file.write_text("dummy cert content", encoding="utf-8")

        monkeypatch.setattr(sys, "platform", "win32")

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "CertUtil: -addstore command completed successfully.\n"
        mock_res.stderr = ""

        with patch("subprocess.run", return_value=mock_res) as mock_run:
            ok = install_windows_ca_certificate(cert_file)
            assert ok is True
            mock_run.assert_called_once()
            cmd_called = mock_run.call_args[0][0]
            assert cmd_called == ["certutil.exe", "-user", "-addstore", "Root", str(cert_file.resolve())]

    def test_failed_certutil_exit_code(self, monkeypatch, tmp_path):
        cert_file = tmp_path / "test.cer"
        cert_file.write_text("dummy cert content", encoding="utf-8")

        monkeypatch.setattr(sys, "platform", "win32")

        mock_res = MagicMock()
        mock_res.returncode = 2147942402
        mock_res.stdout = "CertUtil: Access is denied."
        mock_res.stderr = "Error adding certificate to store."

        with patch("subprocess.run", return_value=mock_res):
            ok = install_windows_ca_certificate(cert_file)
            assert ok is False

    def test_certutil_not_found(self, monkeypatch, tmp_path):
        cert_file = tmp_path / "test.cer"
        cert_file.write_text("dummy cert content", encoding="utf-8")

        monkeypatch.setattr(sys, "platform", "win32")

        with patch("subprocess.run", side_effect=FileNotFoundError("certutil not found")):
            ok = install_windows_ca_certificate(cert_file)
            assert ok is False

    def test_get_default_ca_cert_path(self, monkeypatch, tmp_path):
        custom_cert = tmp_path / "mitmproxy-ca-cert.cer"
        custom_cert.write_text("dummy", encoding="utf-8")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        found = get_default_ca_cert_path()
        assert isinstance(found, Path)


class TestPyO3BuiltinsPatching:
    """Tests for _patch_nuitka_pyo3_builtins idempotency and module dict stamping."""

    def test_patch_injects_builtins_into_new_module(self):
        test_mod = types.ModuleType("test_fake_pyo3_module")
        if "__builtins__" in test_mod.__dict__:
            del test_mod.__dict__["__builtins__"]

        assert "__builtins__" not in test_mod.__dict__

        sys.modules["test_fake_pyo3_module"] = test_mod
        try:
            _patch_nuitka_pyo3_builtins()
            assert "__builtins__" in test_mod.__dict__
            assert test_mod.__dict__["__builtins__"] == builtins.__dict__
        finally:
            sys.modules.pop("test_fake_pyo3_module", None)

    def test_patch_idempotency(self):
        # Calling patch multiple times must succeed without error or duplicate wraps
        _patch_nuitka_pyo3_builtins()
        _patch_nuitka_pyo3_builtins()
        assert getattr(builtins.__import__, "_proxify_builtins_patched", False) is True


class TestCliInstallCa:
    """Tests for proxify CLI --install-ca option."""

    def test_cli_install_ca_success(self, monkeypatch, tmp_path):
        from proxify.__main__ import main

        fake_cert = tmp_path / "test.cer"
        fake_cert.write_text("cert content", encoding="utf-8")

        monkeypatch.setattr(sys, "argv", ["proxify", "--install-ca", "--cert-path", str(fake_cert)])

        with patch("proxify.__main__.install_windows_ca_certificate", return_value=True) as mock_install, \
             pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_install.assert_called_once_with(fake_cert)

    def test_cli_install_ca_failure(self, monkeypatch, tmp_path):
        from proxify.__main__ import main

        fake_cert = tmp_path / "test.cer"
        fake_cert.write_text("cert content", encoding="utf-8")

        monkeypatch.setattr(sys, "argv", ["proxify", "--install-ca", "--cert-path", str(fake_cert)])

        with patch("proxify.__main__.install_windows_ca_certificate", return_value=False) as mock_install, \
             pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_install.assert_called_once_with(fake_cert)

    def test_cli_install_ca_missing_file_fails(self, monkeypatch, tmp_path):
        from proxify.__main__ import main

        non_existent = tmp_path / "does_not_exist.cer"
        monkeypatch.setattr(sys, "argv", ["proxify", "--install-ca", "--cert-path", str(non_existent)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1


class TestDirectExecutionBootstrap:
    """Tests for direct execution sys.path bootstrap without PYTHONPATH."""

    def test_direct_execution_main_without_pythonpath(self):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        main_script = Path(__file__).resolve().parent.parent / "proxify" / "__main__.py"
        res = subprocess.run(
            [sys.executable, str(main_script), "--help"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "--install-ca" in res.stdout
        assert "--cert-path" in res.stdout


class TestDatabaseLayerFixes:
    """Tests for database layer fixes: connection pool default resolution and FTS5 request body trigger."""

    def test_database_pool_none_db_path_resolves_default(self, monkeypatch, tmp_path):
        from proxify.database.connection import DatabasePool

        test_db = tmp_path / "pool_default.db"
        monkeypatch.setenv("PROXIFY_DB_PATH", str(test_db))

        pool = DatabasePool(db_path=None)
        try:
            with pool.connection() as conn:
                assert conn is not None
                conn.execute("SELECT 1;")
            with pool.read_connection() as rconn:
                assert rconn is not None
                cur = rconn.cursor()
                res = cur.execute("SELECT 1;").fetchone()
                assert res[0] == 1
        finally:
            pool.close()

    def test_fts5_trigger_indexes_request_body_when_response_is_binary(self, tmp_path):
        import sqlite3
        from proxify.core.traffic_storage.repository import RequestRepository

        db_file = tmp_path / "fts_test.db"
        conn = sqlite3.connect(str(db_file))
        repo = RequestRepository()
        repo.init_db(conn)

        # Insert a request with JSON request body but binary response content type
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO requests (
                timestamp, timestamp_epoch, method, url, scheme, domain, port, path,
                request_content_type, request_body,
                response_content_type, response_body
            ) VALUES (
                '2026-11-17T00:00:00Z', 1700000000.0, 'POST', 'https://api.example.com/upload',
                'https', 'api.example.com', 443, '/upload',
                'application/json', '{"action": "secret_keyword_alpha"}',
                'image/png', X'89504E47'
            )
        """)
        conn.commit()

        # Query FTS5 for the keyword in request_body
        fts_cur = conn.cursor()
        fts_res = fts_cur.execute(
            "SELECT rowid, request_body FROM requests_fts WHERE requests_fts MATCH 'secret_keyword_alpha'"
        ).fetchall()
        assert len(fts_res) == 1
        assert "secret_keyword_alpha" in fts_res[0][1]
        conn.close()

    def test_fts5_delete_trigger_prevents_malformed_disk_image_corruption(self, tmp_path):
        import sqlite3
        from proxify.core.traffic_storage.repository import RequestRepository

        db_file = tmp_path / "fts_delete_test.db"
        conn = sqlite3.connect(str(db_file))
        repo = RequestRepository()
        repo.init_db(conn)

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO requests (
                id, timestamp, timestamp_epoch, method, url, scheme, domain, port, path,
                request_content_type, request_body,
                response_content_type, response_body
            ) VALUES (
                1, '2026-11-17T00:00:00Z', 1700000000.0, 'POST', 'https://api.example.com/test',
                'https', 'api.example.com', 443, '/test',
                'application/json', '{"token": "SECRET_FTS_DELETE_TOKEN_123"}',
                'application/json', '{"status": "deleted_later_token_456"}'
            )
        """)
        conn.commit()

        # Verify keywords are indexed
        req_res = cur.execute(
            "SELECT rowid, request_body FROM requests_fts WHERE requests_fts MATCH 'SECRET_FTS_DELETE_TOKEN_123'"
        ).fetchall()
        assert len(req_res) == 1

        resp_res = cur.execute(
            "SELECT rowid, response_body FROM requests_fts WHERE requests_fts MATCH 'deleted_later_token_456'"
        ).fetchall()
        assert len(resp_res) == 1

        # Delete the row from main table
        cur.execute("DELETE FROM requests WHERE id = 1")
        conn.commit()

        # Querying requests_fts MATCH for deleted tokens MUST NOT raise sqlite3.DatabaseError: database disk image is malformed
        # and MUST return empty list
        req_res_after = cur.execute(
            "SELECT rowid, request_body FROM requests_fts WHERE requests_fts MATCH 'SECRET_FTS_DELETE_TOKEN_123'"
        ).fetchall()
        assert req_res_after == []

        resp_res_after = cur.execute(
            "SELECT rowid, response_body FROM requests_fts WHERE requests_fts MATCH 'deleted_later_token_456'"
        ).fetchall()
        assert resp_res_after == []

        conn.close()


class TestBuiltinExtensionDiscovery:
    """Tests for dynamic built-in extension package discovery without hardcoded private names."""

    def test_get_builtin_extension_packages_env_and_default(self, monkeypatch):
        from proxify.sdk.loader import _get_builtin_extension_packages

        monkeypatch.setitem(sys.modules, "proxify._compiled_extensions", None)
        monkeypatch.delenv("PROXIFY_BUILTIN_EXTENSIONS", raising=False)
        assert _get_builtin_extension_packages() == ()

        monkeypatch.setenv("PROXIFY_BUILTIN_EXTENSIONS", " ext_one , ext_two , ")
        assert _get_builtin_extension_packages() == ("ext_one", "ext_two")


class TestDashboardSpaRouting:
    """Tests for Dashboard SPA static mounting and API 404 precedence."""

    @pytest.mark.asyncio
    async def test_dashboard_mount_spa_static_routes_and_api_404(self):
        from aiohttp.test_utils import TestClient, TestServer
        from proxify.dashboard import Dashboard

        storage = MagicMock()
        storage.db_integration_enabled = False
        dashboard = Dashboard(storage=storage)
        dashboard.mount_spa_static()

        repo_root = Path(__file__).resolve().parent.parent.parent
        if not (repo_root / "frontend" / "dist" / "index.html").is_file():
            pytest.skip("frontend/dist/index.html not built")

        async with TestClient(TestServer(dashboard.get_app())) as client:
            for route in ("/", "/custom-page", "/settings/view"):
                resp = await client.get(route)
                assert resp.status == 200
                text = await resp.text()
                assert '<div id="root"></div>' in text

            api_404 = await client.get("/api/nonexistent_endpoint")
            assert api_404.status == 404
            data = await api_404.json()
            assert "error" in data


class TestHeadlessLoggingAndAutoDetach:
    """Tests for headless GUI logging, outer executable resolution, and Git Bash auto-detach."""

    def test_get_outer_executable_path_and_compiled_detection(self, monkeypatch, tmp_path):
        from proxify.utils.compat import get_outer_executable_path, is_compiled_executable

        monkeypatch.setattr(sys, "frozen", False, raising=False)
        if hasattr(builtins, "__compiled__"):
            monkeypatch.delattr(builtins, "__compiled__")
        assert is_compiled_executable() is False

        fake_bin = tmp_path / "proxify.exe"
        compiled_ns = types.SimpleNamespace(original_argv0=str(fake_bin))
        monkeypatch.setattr(builtins, "__compiled__", compiled_ns, raising=False)
        assert is_compiled_executable() is True
        assert get_outer_executable_path() == fake_bin.resolve()

    def test_setup_headless_logging_handles_none_streams(self, monkeypatch, tmp_path):
        import logging
        from proxify.utils.compat import setup_headless_logging

        log_file = tmp_path / "proxify_headless.log"
        root_logger = logging.getLogger()
        orig_handlers = list(root_logger.handlers)
        orig_level = root_logger.level

        try:
            root_logger.setLevel(logging.NOTSET)
            monkeypatch.setattr(sys, "stdout", None)
            monkeypatch.setattr(sys, "stderr", None)

            has_console = setup_headless_logging(log_file)
            assert has_console is False
            assert root_logger.level == logging.INFO
            assert sys.stdout is not None
            assert sys.stderr is not None
            assert sys.stdout.isatty() is False

            print("headless print check")
            logging.getLogger("test.headless").info("headless logger check")
            for h in list(root_logger.handlers):
                if h not in orig_handlers:
                    h.flush()
                    h.close()
                    root_logger.removeHandler(h)

            content = log_file.read_text(encoding="utf-8")
            assert "headless print check" in content
            assert "headless logger check" in content
        finally:
            root_logger.setLevel(orig_level)
            for h in list(root_logger.handlers):
                if h not in orig_handlers:
                    try:
                        h.close()
                    except Exception:
                        pass
                    root_logger.removeHandler(h)

    def test_should_auto_detach_git_bash_vs_flags(self, monkeypatch):
        from proxify.__main__ import _should_auto_detach

        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr("proxify.__main__.is_compiled_executable", lambda: True)
        monkeypatch.setenv("MSYSTEM", "MINGW64")
        monkeypatch.delenv("PROXIFY_FOREGROUND", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        base_args = types.SimpleNamespace(
            console=False,
            no_tray=False,
            tray_worker=False,
            install_ca=False,
            stop=False,
        )
        assert _should_auto_detach(base_args) is True

        for flag in ("console", "no_tray", "tray_worker", "install_ca", "stop"):
            ns = types.SimpleNamespace(**{**vars(base_args), flag: True})
            assert _should_auto_detach(ns) is False

        monkeypatch.setenv("PROXIFY_FOREGROUND", "1")
        assert _should_auto_detach(base_args) is False


class TestWindowsSystemTray:
    """Tests for Win64 struct layout and WindowsSystemTray lifecycle."""

    def test_win32_struct_sizes_and_graceful_noop_on_non_windows(self, monkeypatch):
        import ctypes
        from proxify.utils import tray as tray_mod

        if sys.platform == "win32":
            # Win64 sizeof(NOTIFYICONDATAW) == 976, sizeof(WNDCLASSEXW) == 80
            assert ctypes.sizeof(tray_mod.NOTIFYICONDATAW) == 976
            assert ctypes.sizeof(tray_mod.WNDCLASSEXW) == 80

        monkeypatch.setattr(tray_mod, "IS_WINDOWS", False)
        t = tray_mod.WindowsSystemTray(proxy_port=8080, dashboard_port=8888)
        t.start()
        assert t._thread is None
        assert t.show_notification("Title", "Message") is False
        t.stop()

