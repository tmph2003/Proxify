"""Abstract base class for all Proxify extensions."""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .context import ExtensionContext

logger = logging.getLogger("proxify.sdk.base")


class BaseExtension(ABC):
    """
    Abstract Base Class for Proxify Extensions.

    Subclasses must define `id` and `name`, and implement `initialize`.
    The `shutdown` hook is optional for resource cleanup.
    """

    id: str           # Unique slug identifier (e.g., "header_tagger", "sample_extension")
    name: str         # Human-readable display name
    version: str = "1.0.0"
    description: str = ""

    def __init__(self) -> None:
        self.context: Optional["ExtensionContext"] = None

    @abstractmethod
    async def initialize(self, context: "ExtensionContext") -> None:
        """
        Invoked during Proxify server startup when extensions are enabled.

        Extensions must use the provided `context` to:
        - Register traffic observers or mutators
        - Register HTTP routes on the aiohttp dashboard
        - Register CQRS topic handlers for the background worker
        - Register streaming domains or ignored hosts
        - Register UI pages for navigation
        - Register database schema initializers
        """
        self.context = context

    async def shutdown(self) -> None:
        """
        Invoked during graceful server shutdown.

        Override to close background tasks, thread pools, or external clients.
        """
        pass
