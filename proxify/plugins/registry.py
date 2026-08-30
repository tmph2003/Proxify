"""Plugin registry and discovery for Proxify."""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, Type

from .base import BasePlugin

logger = logging.getLogger("proxify.plugins")

# Central registry holding all registered plugin classes
_PLUGIN_REGISTRY: Dict[str, Type[BasePlugin]] = {}

def register_plugin(name: str):
    """
    Decorator to register a plugin class.
    :param name: Unique identifier for the plugin.
    """
    def decorator(cls: Type[BasePlugin]):
        if not issubclass(cls, BasePlugin):
            raise TypeError(f"Plugin {cls.__name__} must inherit from BasePlugin")
        _PLUGIN_REGISTRY[name] = cls
        logger.debug(f"Registered plugin: {name} -> {cls.__name__}")
        return cls
    return decorator

def get_all_plugin_classes() -> Dict[str, Type[BasePlugin]]:
    """Return a dictionary of all registered plugin classes."""
    return dict(_PLUGIN_REGISTRY)

def discover_plugins() -> None:
    """
    Dynamically discover and import all modules in the plugins directory.
    This triggers the @register_plugin decorators.
    """
    logger.info("Discovering plugins...")
    import proxify.plugins
    
    for _, module_name, _ in pkgutil.iter_modules(proxify.plugins.__path__, proxify.plugins.__name__ + "."):
        # Skip base and registry themselves
        if module_name.endswith(".base") or module_name.endswith(".registry"):
            continue
        
        try:
            importlib.import_module(module_name)
            logger.debug(f"Imported plugin module: {module_name}")
        except Exception as e:
            logger.error(f"Failed to import plugin module {module_name}: {e}", exc_info=True)
            
    logger.info(f"Total plugins registered: {len(_PLUGIN_REGISTRY)}")
