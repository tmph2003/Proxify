"""
Proxify Plugin SDK
==================
The official SDK for developing extensions for Proxify.

Provides BaseExtension, ExtensionContext, and the dynamic ExtensionLoader.
Extensions can observe or mutate HTTP/HTTPS traffic, register custom API routes,
add dynamic streaming bypass domains, and handle background CQRS tasks.
"""

from .base import BaseExtension
from .context import ExtensionContext
from .loader import ExtensionLoader

__all__ = [
    "BaseExtension",
    "ExtensionContext",
    "ExtensionLoader",
]
