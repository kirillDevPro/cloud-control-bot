"""Models for representing a server."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .provider import ProviderType


class ServerStatus(str, Enum):
    """
    Server availability statuses.

    Inherits from str so the enum serializes correctly to JSON.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        """Return the status value as a string."""
        return self.value

    def to_emoji(self) -> str:
        """
        Return the emoji that represents this status.

        Returns:
            str: Emoji representation of the status (defaults to "❓" for unknown)
        """
        emoji_map = {
            ServerStatus.ONLINE: "✅",
            ServerStatus.OFFLINE: "❌",
            ServerStatus.UNKNOWN: "❓",
        }
        return emoji_map.get(self, "❓")


class Server(BaseModel):
    """
    Server model.

    A universal model shared across all cloud providers.
    """

    id: str = Field(..., description="Unique server ID (from the provider)")

    provider: ProviderType = Field(..., description="Cloud provider type")

    provider_alias: str = Field(
        default="",
        description="Provider instance alias (e.g. 'hetzner_prod')",
    )

    name: str = Field(..., description="User-defined server name")

    ip: str = Field(..., description="IP address for ping")

    region: str = Field(..., description="Server hosting region")

    plan: str = Field(..., description="Server pricing plan")

    status: ServerStatus = Field(
        default=ServerStatus.UNKNOWN, description="Current availability status"
    )

    last_seen: datetime | None = Field(
        default=None, description="Timestamp of the last successful ping"
    )

    added_at: datetime = Field(
        default_factory=datetime.now, description="Timestamp when added to monitoring"
    )

    enabled: bool = Field(default=True, description="Whether monitoring is enabled for this server")

    # Additional fields used for display
    os: str | None = Field(default=None, description="Operating system")

    ram_mb: int | None = Field(default=None, description="RAM size in MB")

    disk_gb: int | None = Field(default=None, description="Disk size in GB")

    vcpu_count: int | None = Field(default=None, description="vCPU count")

    power_status: str | None = Field(
        default=None,
        description="Server power status from the provider (e.g. running, stopped)",
    )

    def __str__(self) -> str:
        """Return a human-readable string representation of the server."""
        return f"{self.name} ({self.provider.value}) - {self.status.value}"

    def get_display_name(self) -> str:
        """
        Return the server name prefixed with its status emoji for display.

        Returns:
            str: Formatted name with the status emoji
        """
        return f"{self.status.to_emoji()} {self.name}"

    @property
    def effective_alias(self) -> str:
        """
        Return the provider instance alias used for identification.

        Uses provider_alias when set; otherwise falls back to provider.value
        (backward compatibility with legacy servers that have no alias).

        Returns:
            str: Provider alias (e.g. "hetzner_prod" or "vultr")
        """
        return self.provider_alias if self.provider_alias else self.provider.value

    @property
    def composite_key(self) -> str:
        """
        Return the composite key that uniquely identifies the server.

        Format: "provider_alias:server_id" (current) or "provider:server_id" (legacy).

        Returns:
            str: Unique server key
        """
        return f"{self.effective_alias}:{self.id}"
