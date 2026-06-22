"""Cloud provider type and provider-instance configuration models."""

from enum import Enum

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    """
    Supported cloud provider types.

    Inherits from str so the enum serializes correctly to JSON.
    """

    VULTR = "vultr"
    HETZNER = "hetzner"
    AWS = "aws"

    def __str__(self) -> str:
        """Return the provider type as its underlying string value."""
        return self.value


class ProviderConfig(BaseModel):
    """
    Configuration for a single provider instance.

    Allows creating multiple instances of the same provider type with
    different API keys (for example, two Hetzner accounts).

    Attributes:
        alias: Unique instance identifier (for example, "hetzner_prod").
        type: Provider type (VULTR, HETZNER, AWS).
        display_name: Display name for the UI (for example, "Hetzner (prod)").
        emoji: ASCII emoji for the UI (for example, "[H]").
        regions: List of AWS regions (AWS only; None means all regions).
        enable_ec2: Enable EC2 monitoring (AWS only).
        enable_lightsail: Enable Lightsail monitoring (AWS only).
    """

    alias: str = Field(..., description="Unique provider instance identifier")
    type: ProviderType = Field(..., description="Provider type")
    display_name: str = Field(..., description="Display name for the UI")
    emoji: str = Field(default="[?]", description="ASCII emoji for the UI")

    # AWS-specific settings
    regions: list[str] | None = Field(
        default=None,
        description="List of AWS regions (None = all regions)",
    )
    enable_ec2: bool = Field(default=True, description="Enable EC2 instance monitoring")
    enable_lightsail: bool = Field(
        default=True,
        description="Enable Lightsail instance monitoring",
    )

    def __str__(self) -> str:
        """Return a human-readable representation: "<display_name> (<alias>)"."""
        return f"{self.display_name} ({self.alias})"

    def __repr__(self) -> str:
        """Return a debug representation showing the alias and provider type."""
        return f"ProviderConfig(alias={self.alias!r}, type={self.type.value!r})"
