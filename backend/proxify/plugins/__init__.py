"""Proxify Plugins System."""

from pathlib import Path
from .base import BasePlugin
from .registry import register_plugin, discover_plugins, get_all_plugin_classes

__all__ = ["BasePlugin", "register_plugin", "discover_plugins", "get_all_plugin_classes"]

# Add local and docker extensions paths to plugins package __path__
_ext_path = Path(__file__).resolve().parent.parent.parent / "extensions"
if _ext_path.exists() and _ext_path.is_dir() and str(_ext_path) not in __path__:
    __path__.append(str(_ext_path))

_docker_path = Path("/app/extensions")
if _docker_path.exists() and _docker_path.is_dir() and str(_docker_path) not in __path__:
    __path__.append(str(_docker_path))

