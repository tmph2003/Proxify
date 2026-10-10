"""Dynamic Extension Discovery and Loader for Proxify."""

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


class ExtensionLoader:
    """
    Discovers, loads, and manages extensions dynamically from EXTENSIONS_DIR.

    Zero core imports of extension modules.
    Fault-isolated: an error in one extension will NOT crash the core server.
    """

    def __init__(
        self,
        extensions_dir: Optional[str] = None,
        disabled: Optional[bool] = None,
    ):
        env_dir = os.getenv("EXTENSIONS_DIR")
        if not env_dir:
            local_ext = Path(__file__).resolve().parent.parent.parent / "extensions"
            if local_ext.exists() and local_ext.is_dir():
                env_dir = str(local_ext)
            elif Path("/app/extensions").exists():
                env_dir = "/app/extensions"
            else:
                env_dir = str(local_ext)
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

        if not self.extensions_dir.exists() or not self.extensions_dir.is_dir():
            logger.info(f"ℹ️ Extensions directory '{self.extensions_dir}' does not exist. Running pure core logger.")
            self._register_extensions_api(dashboard_app)
            return []

        # Add extensions directory to sys.path so extensions can import their internal packages
        ext_dir_str = str(self.extensions_dir.resolve())
        if ext_dir_str not in sys.path:
            sys.path.insert(0, ext_dir_str)

        entries = sorted(list(self.extensions_dir.iterdir()))
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue

            extension_instance = self._load_extension_module(entry)
            if extension_instance is None:
                continue

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
                    f"❌ Failed to initialize extension '{entry.name}': {init_err}",
                    exc_info=True,
                )

        logger.info(f"📦 Total extensions loaded: {len(self.loaded_extensions)}")

        # Mount GET /api/extensions endpoint
        self._register_extensions_api(dashboard_app)
        return self.loaded_extensions

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

            # Alias virtual packages so legacy/internal imports work seamlessly
            for prefix in ("proxify.platforms", "proxify.plugins"):
                pkg_alias = f"{prefix}.{dir_name}"
                if pkg_alias not in sys.modules:
                    pkg = types.ModuleType(pkg_alias)
                    pkg.__path__ = [dir_path]
                    init_f = directory / "__init__.py"
                    if init_f.exists():
                        pkg.__file__ = str(init_f.resolve())
                    pkg.__package__ = pkg_alias
                    sys.modules[pkg_alias] = pkg

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
