"""
Provider Manager for managing multiple cloud providers.

This module provides centralized provider management, allowing several
instances of the same provider type to be registered with different API
keys (alias-based system).
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

from src.models.provider import ProviderType, ProviderConfig
from src.providers.base import BaseProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderServerListGather:
    """Ordered raw results from one snapshot of the provider registry.

    Attributes:
        providers: Stable alias-to-provider/config snapshot used for the requests.
        aliases: Provider aliases in the same positional order as ``results``.
        results: Unclassified values returned by ``asyncio.gather``.
    """

    providers: dict[str, tuple[BaseProvider, ProviderConfig]]
    aliases: list[str]
    results: list[Any]


class _ProviderRegistry(Protocol):
    """Existing provider-manager protocol needed to gather server lists."""

    def get_all_providers(self) -> dict[str, tuple[BaseProvider, ProviderConfig]]:
        """Return one snapshot of the registered providers."""
        ...


async def gather_server_lists(
    provider_manager: _ProviderRegistry,
) -> ProviderServerListGather:
    """Fetch every provider's server list concurrently in registry order.

    The returned values are intentionally raw. Callers retain responsibility
    for classifying exceptions and response types, assigning provider aliases,
    and deciding how successful empty responses affect synchronization.

    Args:
        provider_manager: Manager exposing the existing ``get_all_providers`` protocol.

    Returns:
        ProviderServerListGather: Registry snapshot, ordered aliases, and raw
            per-provider results aligned by position.
    """
    providers = provider_manager.get_all_providers()
    provider_tasks = []
    aliases = []

    for alias, (provider, _config) in providers.items():
        provider_tasks.append(provider.get_servers())
        aliases.append(alias)

    results = await asyncio.gather(*provider_tasks, return_exceptions=True)
    return ProviderServerListGather(
        providers=providers,
        aliases=aliases,
        results=results,
    )


class ProviderManager:
    """
    Manager for handling multiple cloud providers.

    Supports an alias-based system that allows several instances of the same
    provider type to be registered with different API keys.

    Example:
        >>> manager = ProviderManager()
        >>> manager.register_provider("hetzner_prod", provider1, config1)
        >>> manager.register_provider("hetzner_staging", provider2, config2)
        >>>
        >>> provider = manager.get_provider("hetzner_prod")
        >>> servers = await provider.get_servers()
        >>>
        >>> await manager.close_all()
    """

    def __init__(self) -> None:
        """Initialize the provider manager with an empty registry."""
        # Primary storage: alias -> (provider, config)
        self._providers: dict[str, tuple[BaseProvider, ProviderConfig]] = {}
        # Index by type: ProviderType -> list[alias]
        self._by_type: dict[ProviderType, list[str]] = defaultdict(list)

    def register_provider(
        self, alias: str, provider: BaseProvider, config: ProviderConfig
    ) -> None:
        """
        Register a provider in the manager.

        If the alias is already registered, the existing entry is overwritten
        (a warning is logged and the old type-index entry is removed first).

        Args:
            alias: Unique identifier of the provider instance
            provider: Provider instance (subclass of BaseProvider)
            config: Provider configuration
        """
        if alias in self._providers:
            logger.warning(f"Provider '{alias}' is already registered, overwriting")
            # Remove from the type index
            old_config = self._providers[alias][1]
            if alias in self._by_type[old_config.type]:
                self._by_type[old_config.type].remove(alias)

        self._providers[alias] = (provider, config)
        self._by_type[config.type].append(alias)

        logger.info(f"Registered provider: {alias} (type: {config.type.value})")

    def get_provider(self, alias: str) -> BaseProvider | None:
        """
        Get a provider by alias.

        Args:
            alias: Unique identifier of the provider

        Returns:
            The provider instance, or None if it is not registered
        """
        entry = self._providers.get(alias)
        if entry is None:
            logger.warning(f"Provider '{alias}' not registered")
            return None
        return entry[0]

    def get_config(self, alias: str) -> ProviderConfig | None:
        """
        Get a provider's configuration by alias.

        Args:
            alias: Unique identifier of the provider

        Returns:
            The provider configuration, or None if it is not registered
        """
        entry = self._providers.get(alias)
        if entry is None:
            return None
        return entry[1]

    def get_provider_with_config(
        self, alias: str
    ) -> tuple[BaseProvider, ProviderConfig] | None:
        """
        Get a provider together with its configuration.

        Args:
            alias: Unique identifier of the provider

        Returns:
            A (provider, config) tuple, or None if it is not registered
        """
        return self._providers.get(alias)

    def get_all_providers(self) -> dict[str, tuple[BaseProvider, ProviderConfig]]:
        """
        Return all registered providers.

        Returns:
            A copy of the {alias: (provider, config)} dict of all active providers
        """
        return self._providers.copy()

    def get_providers_by_type(self, provider_type: ProviderType) -> list[str]:
        """
        Return the list of aliases for providers of the given type.

        Args:
            provider_type: Provider type

        Returns:
            A copy of the list of aliases
        """
        return self._by_type.get(provider_type, []).copy()

    def get_all_aliases(self) -> list[str]:
        """
        Return the list of all registered aliases.

        Returns:
            A list of aliases
        """
        return list(self._providers.keys())

    def is_registered(self, alias: str) -> bool:
        """
        Check whether a provider is registered.

        Args:
            alias: Unique identifier of the provider

        Returns:
            True if the provider is registered, otherwise False
        """
        return alias in self._providers

    def get_provider_count(self) -> int:
        """
        Return the number of registered providers.

        Returns:
            The count of active providers
        """
        return len(self._providers)

    def resolve_alias_from_composite_key(self, composite_key: str) -> str | None:
        """
        Extract the alias from a composite key.

        A composite key has the format "alias:server_id". This method checks
        whether the first part is a registered alias, and falls back to
        resolving it by provider type for backward compatibility.

        Args:
            composite_key: Composite key in the format "alias:server_id"

        Returns:
            The provider alias, or None if it cannot be resolved
        """
        parts = composite_key.split(":", 1)
        if len(parts) != 2:
            return None

        alias_or_type = parts[0]

        # First, check for a direct match against a registered alias
        if alias_or_type in self._providers:
            return alias_or_type

        # Backward compatibility: try to resolve by provider type.
        # This only works if there is exactly one provider of that type.
        try:
            provider_type = ProviderType(alias_or_type.lower())
            aliases = self._by_type.get(provider_type, [])
            if len(aliases) == 1:
                return aliases[0]
        except ValueError:
            pass

        return None

    async def close_all(self) -> None:
        """
        Close all registered providers (graceful shutdown).

        Calls close() on every provider to cleanly terminate HTTP sessions.
        Only successfully closed providers are removed from the registry;
        providers whose close() raised are left in place and logged.
        """
        exceptions = []
        successfully_closed = []

        # Iterate over a copy of the keys so we can safely delete while iterating
        for alias in list(self._providers.keys()):
            provider, config = self._providers[alias]
            try:
                await provider.close()
                successfully_closed.append(alias)
                # Remove from the type index
                if alias in self._by_type[config.type]:
                    self._by_type[config.type].remove(alias)
                # Remove from the primary storage
                del self._providers[alias]
            except Exception as e:
                logger.error(f"Failed to close provider '{alias}': {e}")
                exceptions.append((alias, e))

        # Check whether any providers remain unclosed
        if self._providers:
            unclosed = ", ".join(self._providers.keys())
            logger.warning(
                f"Failed to close {len(self._providers)} provider(s): {unclosed}. "
                f"HTTP sessions may remain open."
            )

        if exceptions:
            logger.error(f"Encountered {len(exceptions)} error(s) during provider shutdown")

    def __repr__(self) -> str:
        """Return a string representation of the manager listing its provider aliases."""
        providers_list = ", ".join(self._providers.keys())
        return f"ProviderManager(providers=[{providers_list}])"
