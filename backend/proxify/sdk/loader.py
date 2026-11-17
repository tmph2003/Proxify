"""Dynamic Extension Discovery and Loader for Proxify."""

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import logging
import os
import sys
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aiohttp import web

from .base import BaseExtension
from .context import ExtensionContext

logger = logging.getLogger("proxify.sdk.loader")


class _LegacyNamespaceAliasLoader(importlib.abc.Loader):
    """Maps legacy `proxify.platforms.<ext>.*` imports to top-level `<ext>.*` modules.

    Essential for Nuitka compiled binaries where extension submodules are compiled
    under `<ext>.*` without `.py` files on disk.
    """
    def __init__(self, target_name: str):
        self.target_name = target_name

    def create_module(self, spec):
        return importlib.import_module(self.target_name)

    def exec_module(self, module):
        pass


class _LegacyNamespaceAliasFinder(importlib.abc.MetaPathFinder):
    PREFIX = "proxify.platforms."
    DIRECT_ALIASES = {
        "proxify.utils.circuit_breaker": "circuit_breaker",
    }

    def find_spec(self, fullname: str, path=None, target=None):
        target_name = self.DIRECT_ALIASES.get(fullname)
        if target_name is None and fullname.startswith(self.PREFIX):
            target_name = fullname[len(self.PREFIX):]
        if not target_name:
            return None
        try:
            target_mod = importlib.import_module(target_name)
        except ImportError:
            return None
        is_pkg = hasattr(target_mod, "__path__")
        return importlib.machinery.ModuleSpec(
            fullname,
            _LegacyNamespaceAliasLoader(target_name),
            is_package=is_pkg,
        )


def _install_legacy_alias_finder() -> None:
    if "proxify.platforms" not in sys.modules:
        pkg = types.ModuleType("proxify.platforms")
        pkg.__path__ = []
        pkg.__package__ = "proxify.platforms"
        sys.modules["proxify.platforms"] = pkg
    if not any(isinstance(f, _LegacyNamespaceAliasFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _LegacyNamespaceAliasFinder())


def _get_builtin_extension_packages() -> tuple[str, ...]:
    """Discover compiled built-in extension packages injected at build time or via env."""
    try:
        from proxify._compiled_extensions import COMPILED_EXTENSION_PACKAGES
        if COMPILED_EXTENSION_PACKAGES:
            return tuple(str(x).strip() for x in COMPILED_EXTENSION_PACKAGES if str(x).strip())
    except ImportError:
        pass
    env_pkgs = os.getenv("PROXIFY_BUILTIN_EXTENSIONS", "")
    return tuple(p.strip() for p in env_pkgs.split(",") if p.strip())


class ExtensionLoader:
    """
    Discovers, loads, and manages extensions dynamically from EXTENSIONS_DIR.

    Zero core imports of extension modules.
    Fault-isolated: an error in one extension will NOT crash the core server.
    """

    BUILTIN_EXTENSION_PACKAGES = _get_builtin_extension_packages()

    def __init__(
        self,
        extensions_dir: Optional[str] = None,
        disabled: Optional[bool] = None,
    ):
        env_dir = os.getenv("EXTENSIONS_DIR") or os.getenv("PROXIFY_EXTENSIONS_DIR")
        if not env_dir:
            if "__compiled__" in globals() or getattr(sys, "frozen", False):
                exe_ext = Path(sys.executable).resolve().parent / "extensions"
                env_dir = str(exe_ext)
            else:
                repo_root = Path(__file__).resolve().parent.parent.parent.parent
                private_ext = repo_root / "private" / "extensions"
                local_ext = Path(__file__).resolve().parent.parent.parent / "extensions"
                if private_ext.exists() and private_ext.is_dir():
                    env_dir = str(private_ext)
                elif local_ext.exists() and local_ext.is_dir():
                    env_dir = str(local_ext)
                elif Path("/app/extensions").exists():
                    env_dir = "/app/extensions"
                else:
                    env_dir = str(private_ext)
        self.extensions_dir = Path(extensions_dir or env_dir)

        # Support both DISABLE_EXTENSIONS and PROXIFY_DISABLE_EXTENSIONS
        env_disable = (
            os.getenv("DISABLE_EXTENSIONS", "false").lower() in ("true", "1", "yes")
            or os.getenv("PROXIFY_DISABLE_EXTENSIONS", "false").lower() in ("true", "1", "yes")
        )
        self.disabled = env_disable if disabled is None else disabled

        self.loaded_extensions: List[BaseExtension] = []
        self.ui_pages: List[Dict[str, Any]] = []

    def is_enabled(self) -> bool:
        """Check if extensions are enabled."""
        return not self.disabled

    async def discover_and_load(
        self,
        router: Any,
        dashboard_app: web.Application,
        db_manager: Any,
        sync_db_pool: Any,
        worker: Any,
        filter_instance: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        storage: Optional[Any] = None,
    ) -> List[BaseExtension]:
        """
        Discover and initialize all extensions in `self.extensions_dir`.
        """
        if self.disabled:
            logger.info("🚫 Extensions are DISABLED (DISABLE_EXTENSIONS=true). Running pure core logger.")
            self._register_extensions_api(dashboard_app)
            return []

        _install_legacy_alias_finder()

        candidates: List[tuple[str, BaseExtension]] = []
        loaded_pkg_names: set[str] = set()

        if self.extensions_dir.exists() and self.extensions_dir.is_dir():
            # Add extensions directory and optional sibling shared directory to sys.path
            ext_dir_str = str(self.extensions_dir.resolve())
            if ext_dir_str not in sys.path:
                sys.path.insert(0, ext_dir_str)
            shared_dir = self.extensions_dir.resolve().parent / "shared"
            if shared_dir.exists() and shared_dir.is_dir():
                shared_str = str(shared_dir)
                if shared_str not in sys.path:
                    sys.path.insert(0, shared_str)

            entries = sorted(list(self.extensions_dir.iterdir()))
            for entry in entries:
                if not entry.is_dir() or entry.name.startswith((".", "_")):
                    continue
                inst = self._load_extension_module(entry)
                if inst is not None:
                    candidates.append((entry.name, inst))
                    loaded_pkg_names.add(entry.name)

        # Also discover compiled built-in extensions (e.g. inside Nuitka standalone .exe)
        builtin_pkgs = self.BUILTIN_EXTENSION_PACKAGES or _get_builtin_extension_packages()
        for pkg_name in builtin_pkgs:
            if pkg_name in loaded_pkg_names:
                continue
            inst = self._load_builtin_extension(pkg_name)
            if inst is not None:
                candidates.append((pkg_name, inst))
                loaded_pkg_names.add(pkg_name)

        if not candidates:
            logger.info(f"ℹ️ No external or built-in extensions found (dir='{self.extensions_dir}'). Running pure core logger.")
            self._register_extensions_api(dashboard_app)
            return []

        for entry_name, extension_instance in candidates:
            # Create dedicated capability context for this extension
            context = ExtensionContext(
                extension_id=extension_instance.id,
                router=router,
                dashboard_app=dashboard_app,
                db_manager=db_manager,
                sync_db_pool=sync_db_pool,
                worker=worker,
                filter_instance=filter_instance,
                event_bus=event_bus,
                storage=storage,
            )

            try:
                # 1. Initialize extension
                await extension_instance.initialize(context)
                self.loaded_extensions.append(extension_instance)

                # 2. Run registered database initializers
                for init_fn in context._db_initializers:
                    try:
                        res = init_fn()
                        if inspect.iscoroutine(res):
                            await res
                    except Exception as db_err:
                        logger.error(f"[{extension_instance.id}] DB initializer failed: {db_err}", exc_info=True)

                # 3. Collect UI metadata
                self.ui_pages.extend(context._ui_pages)

                logger.info(
                    f"✅ Extension loaded: {extension_instance.name} "
                    f"(id={extension_instance.id}, v={extension_instance.version})"
                )
            except Exception as init_err:
                logger.error(
                    f"❌ Failed to initialize extension '{entry_name}': {init_err}",
                    exc_info=True,
                )

        logger.info(f"📦 Total extensions loaded: {len(self.loaded_extensions)}")

        # Mount GET /api/extensions endpoint
        self._register_extensions_api(dashboard_app)
        return self.loaded_extensions

    def _load_builtin_extension(self, pkg_name: str) -> Optional[BaseExtension]:
        """Attempt to import a compiled built-in extension package (e.g. inside Nuitka binary)."""
        try:
            module = importlib.import_module(f"{pkg_name}.extension")
        except ImportError:
            return None
        except Exception as e:
            logger.error(f"❌ Failed to import built-in extension '{pkg_name}': {e}", exc_info=True)
            return None

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, BaseExtension)
                and attr is not BaseExtension
            ):
                instance = attr()
                if not hasattr(instance, "id") or not instance.id:
                    instance.id = pkg_name
                if not hasattr(instance, "name") or not instance.name:
                    instance.name = pkg_name.capitalize()
                return instance
        return None

    def _load_extension_module(self, directory: Path) -> Optional[BaseExtension]:
        """
        Dynamically imports the extension module from directory/extension.py or directory/__init__.py.
        """
        ext_file = directory / "extension.py"
        init_file = directory / "__init__.py"
        target_file = ext_file if ext_file.exists() else init_file

        if not target_file.exists():
            return None

        dir_name = directory.name
        dir_path = str(directory.resolve())
        module_name = f"{dir_name}.extension"
        try:
            # Ensure parent package exists in sys.modules so relative imports work
            if dir_name not in sys.modules:
                pkg_mod = types.ModuleType(dir_name)
                pkg_mod.__path__ = [dir_path]
                pkg_mod.__package__ = dir_name
                init_f = directory / "__init__.py"
                if init_f.exists():
                    pkg_mod.__file__ = str(init_f.resolve())
                sys.modules[dir_name] = pkg_mod

            spec = importlib.util.spec_from_file_location(module_name, target_file)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            module.__package__ = dir_name
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Discover subclasses of BaseExtension
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, BaseExtension)
                    and attr is not BaseExtension
                ):
                    instance = attr()
                    if not hasattr(instance, "id") or not instance.id:
                        instance.id = directory.name
                    if not hasattr(instance, "name") or not instance.name:
                        instance.name = directory.name.capitalize()
                    return instance

        except Exception as e:
            logger.error(f"❌ Failed to import extension from '{directory}': {e}", exc_info=True)
            return None

        return None

    def _register_extensions_api(self, app: web.Application) -> None:
        """Register the GET /api/extensions endpoint on the dashboard app."""
        async def handle_extensions(request: web.Request) -> web.Response:
            if self.disabled:
                return web.json_response({
                    "enabled": False,
                    "extensions": [],
                })

            sorted_pages = sorted(self.ui_pages, key=lambda x: x.get("order", 100))
            return web.json_response({
                "enabled": True,
                "extensions": sorted_pages,
            })

        app.router.add_get("/api/extensions", handle_extensions)

    async def shutdown_all(self) -> None:
        """Gracefully shut down all loaded extensions."""
        for ext in reversed(self.loaded_extensions):
            try:
                await ext.shutdown()
                logger.info(f"🛑 Extension shut down: {ext.name}")
            except Exception as e:
                logger.warning(f"Error shutting down extension {ext.name}: {e}")
        self.loaded_extensions.clear()
