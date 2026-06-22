"""Factory for creating provider instances."""

import logging

from ..models.provider import ProviderConfig, ProviderType
from .base import BaseProvider
from .vultr import VultrProvider
from .hetzner import HetznerProvider
from .aws import AWSProvider

logger = logging.getLogger(__name__)


class ProviderFactory:
    """
    Factory for creating provider instances.

    Uses ProviderConfig to build providers with the correct alias,
    display_name, and emoji.

    Example:
        >>> config = ProviderConfig(
        ...     alias="hetzner_prod",
        ...     type=ProviderType.HETZNER,
        ...     display_name="Hetzner (prod)",
        ...     emoji="[H]",
        ... )
        >>> provider = ProviderFactory.create(config, api_key="...")
    """

    # Mapping from provider type to provider class
    _provider_classes: dict[ProviderType, type[BaseProvider]] = {
        ProviderType.VULTR: VultrProvider,
        ProviderType.HETZNER: HetznerProvider,
        ProviderType.AWS: AWSProvider,
    }

    @classmethod
    def create(
        cls,
        config: ProviderConfig,
        api_key: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
    ) -> BaseProvider:
        """
        Create a provider instance from the given configuration.

        Args:
            config: Provider configuration.
            api_key: API key (for Vultr, Hetzner).
            access_key_id: AWS Access Key ID (for AWS).
            secret_access_key: AWS Secret Access Key (for AWS).

        Returns:
            BaseProvider: The created provider instance.

        Raises:
            ValueError: If the provider type is not supported, or if the
                required credentials for the provider type are missing.
        """
        if config.type not in cls._provider_classes:
            available = ", ".join(p.value for p in cls._provider_classes.keys())
            raise ValueError(
                f"Provider {config.type.value} is not supported. Available: {available}"
            )

        logger.info(f"Creating provider: {config.alias} (type: {config.type.value})")

        # Parameters common to all provider types
        common_kwargs = {
            "alias": config.alias,
            "display_name": config.display_name,
            "emoji": config.emoji,
        }

        # AWS requires its own dedicated credentials and options
        if config.type == ProviderType.AWS:
            if not access_key_id or not secret_access_key:
                raise ValueError(
                    f"AWS provider '{config.alias}' requires access_key_id and secret_access_key"
                )

            return AWSProvider(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                regions=config.regions,
                enable_ec2=config.enable_ec2,
                enable_lightsail=config.enable_lightsail,
                **common_kwargs,
            )

        # Vultr and Hetzner use a single api_key
        provider_class = cls._provider_classes[config.type]

        if not api_key:
            raise ValueError(f"Provider '{config.alias}' requires api_key")

        # VultrProvider and HetznerProvider accept api_key (mypy can't see this)
        return provider_class(api_key=api_key, **common_kwargs)  # type: ignore

    @classmethod
    def get_supported_types(cls) -> list[ProviderType]:
        """Return the list of supported provider types."""
        return list(cls._provider_classes.keys())

    @classmethod
    def is_supported(cls, provider_type: ProviderType) -> bool:
        """Return whether the given provider type is supported."""
        return provider_type in cls._provider_classes

    @classmethod
    def register_provider(
        cls, provider_type: ProviderType, provider_class: type[BaseProvider]
    ) -> None:
        """
        Register a new provider class in the factory.

        Allows the set of supported providers to be extended dynamically.
        If the type is already registered, it is overwritten and a warning
        is logged.

        Args:
            provider_type: The provider type to register.
            provider_class: The provider class to associate with the type.
        """
        if provider_type in cls._provider_classes:
            logger.warning(
                f"Provider {provider_type.value} is already registered. Overwriting."
            )

        cls._provider_classes[provider_type] = provider_class
        logger.info(f"Registered provider: {provider_type.value}")
