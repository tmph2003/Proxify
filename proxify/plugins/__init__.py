"""Proxify Plugins System."""

from .base import BasePlugin
from .registry import register_plugin, discover_plugins, get_all_plugin_classes

__all__ = ["BasePlugin", "register_plugin", "discover_plugins", "get_all_plugin_classes"]
