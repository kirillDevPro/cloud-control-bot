"""Application configuration via Pydantic Settings with YAML support.

Providers are automatically discovered from environment variables in the .env file
(auto-discovery). Provider configuration in YAML is no longer required.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from ..models.provider import ProviderConfig
from .provider_discovery import (
    discover_providers_from_env,
    generate_provider_config,
    get_provider_api_key_from_env,
    get_provider_aws_credentials_from_env,
)


def _load_yaml_config() -> dict[str, Any]:
    """Load configuration from the YAML file.

    Returns:
        dict[str, Any]: Parsed YAML contents, or an empty dict if the file
            does not exist or is empty.
    """
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """Pydantic settings source that reads values from the YAML config file."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        """Initialize the source and eagerly load the YAML config into memory.

        Args:
            settings_cls: The Settings class this source provides values for.
        """
        super().__init__(settings_cls)
        self._yaml_data = _load_yaml_config()

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        """Resolve a single Settings field from the loaded YAML configuration.

        Args:
            field: The Pydantic field info (unused; required by the source API).
            field_name: Name of the Settings field to look up.

        Returns:
            tuple[Any, str, bool]: A tuple of (value, field_name, value_is_complex).
                ``value`` is None when the field is not mapped to YAML or is
                absent from the YAML structure.
        """
        # Mapping of Settings fields to their nested location in the YAML structure
        field_mapping: dict[str, tuple[str, ...]] = {
            # Monitoring
            "PING_INTERVAL": ("monitoring", "ping_interval"),
            "PING_TIMEOUT": ("monitoring", "ping_timeout"),
            "PING_ATTEMPTS": ("monitoring", "ping_attempts"),
            # Balance
            "BALANCE_THRESHOLD": ("balance", "threshold"),
            "BALANCE_CHECK_INTERVAL": ("balance", "check_interval"),
            # Synchronization
            "SERVERS_SYNC_INTERVAL": ("sync", "servers_interval"),
            # Logging
            "LOG_LEVEL": ("logging", "level"),
            # Paths
            "DATA_DIR": ("data", "directory"),
        }

        if field_name not in field_mapping:
            return None, field_name, False

        # Walk the nested YAML structure following the mapped key path
        keys = field_mapping[field_name]
        current: Any = self._yaml_data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None, field_name, False
            current = current[key]

        result: Any = current

        # Special handling for DATA_DIR: convert a string into a Path
        if field_name == "DATA_DIR" and isinstance(result, str):
            result = Path(result)

        return result, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Return all field values resolvable from the YAML config.

        Returns:
            dict[str, Any]: Mapping of field name to value for every Settings
                field that has a non-None value in the YAML configuration.
        """
        result: dict[str, Any] = {}
        for field_name in self.settings_cls.model_fields:
            value, _, _ = self.get_field_value(None, field_name)
            if value is not None:
                result[field_name] = value
        return result


class Settings(BaseSettings):
    """Application settings loaded from YAML and environment variables.

    Load priority (highest to lowest):
    1. Environment variables (.env)
    2. YAML configuration (config.yaml)
    3. Default values

    BALANCE_THRESHOLD is a startup seed for runtime_settings: once an admin changes
    the low-balance threshold or alert toggle in the bot, data/runtime_settings.json
    owns both runtime values until that file is removed.

    PROVIDERS: Automatically discovered from environment variables (auto-discovery).
    Variable patterns:
    - Hetzner: HETZNER_{SUFFIX}_API_KEY -> alias=hetzner_{suffix}
    - Vultr: VULTR_{SUFFIX}_API_KEY -> alias=vultr_{suffix}
    - AWS: AWS_{SUFFIX}_ACCESS_KEY_ID + AWS_{SUFFIX}_SECRET_ACCESS_KEY -> alias=aws_{suffix}

    Examples:
    - HETZNER_PROD_API_KEY=xxx -> alias=hetzner_prod, display_name="Hetzner (prod)"
    - VULTR_MAIN_API_KEY=xxx -> alias=vultr_main, display_name="Vultr"
    - AWS_PROD_ACCESS_KEY_ID=xxx -> alias=aws_prod, display_name="AWS (prod)"
    """

    # === REQUIRED PARAMETERS (only in .env) ===

    TELEGRAM_BOT_TOKEN: str = Field(..., description="Telegram bot token (obtain from @BotFather)")

    # === RUNTIME PARAMETERS (env/defaults; selected fields also map from YAML) ===

    ADMIN_IDS: str = Field(
        default="",
        description="Comma-separated list of administrator IDs",
    )

    # Monitoring
    PING_INTERVAL: int = Field(default=60, description="Ping interval in seconds", ge=10, le=3600)

    PING_TIMEOUT: int = Field(default=5, description="Timeout for the ping in seconds", ge=1, le=30)

    PING_ATTEMPTS: int = Field(
        default=3,
        description="Number of ping attempts before marking a server as unavailable",
        ge=1,
        le=10,
    )

    # Balance
    BALANCE_THRESHOLD: float = Field(
        default=100.0, description="Balance threshold for notification (USD)", ge=0.0
    )

    BALANCE_CHECK_INTERVAL: int = Field(
        default=21600,  # 6 hours
        description="Balance check interval in seconds",
        ge=3600,  # minimum 1 hour
        le=86400,  # maximum 24 hours
    )

    # Synchronization
    SERVERS_SYNC_INTERVAL: int = Field(
        default=1800,  # 30 minutes
        description="Server synchronization interval with provider APIs in seconds",
        ge=300,  # minimum 5 minutes
        le=86400,  # maximum 24 hours
    )

    # Logging
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Paths
    DATA_DIR: Path = Field(default=Path("data"), description="Directory for storing data")

    # === PYDANTIC CONFIGURATION ===

    # Anchor the .env to the project root (not the CWD) so TELEGRAM_BOT_TOKEN /
    # ADMIN_IDS load regardless of the working directory — matching the project-root
    # .env that provider auto-discovery reads.
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Configure the settings sources with priority: env > yaml > defaults.

        Args:
            settings_cls: The Settings class being configured.
            init_settings: Source for values passed to the constructor.
            env_settings: Source for OS environment variables.
            dotenv_settings: Source for values from the .env file.
            file_secret_settings: Source for file-based secrets.

        Returns:
            tuple[PydanticBaseSettingsSource, ...]: Ordered sources, highest
                priority first, with the YAML source inserted ahead of file secrets.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    # === VALIDATORS ===

    @field_validator("ADMIN_IDS")
    @classmethod
    def validate_admin_ids(cls, v: str) -> str:
        """Validate the format of ADMIN_IDS.

        Args:
            v: The raw ADMIN_IDS value, a comma-separated list of numeric IDs.

        Returns:
            str: The validated value unchanged.

        Raises:
            ValueError: If the value is empty, contains empty elements, or
                contains a non-numeric element.
        """
        if not v:
            raise ValueError("ADMIN_IDS cannot be empty")

        # Strip every element BEFORE validating
        ids = [admin_id.strip() for admin_id in v.split(",")]

        for admin_id in ids:
            if not admin_id:
                # Empty element after stripping (e.g. "123,,456")
                raise ValueError(
                    f"ADMIN_IDS contains empty elements. Received: {v}"
                )
            if not (admin_id.isascii() and admin_id.isdigit()):
                # str.isdigit() also accepts non-ASCII digits (superscripts, other
                # Unicode numerics) that int() later rejects; require ASCII so the
                # failure surfaces here at config-load time, not mid-broadcast.
                raise ValueError(
                    f"ADMIN_IDS must contain only numbers separated by commas. "
                    f"Received: {v}"
                )

        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate that the logging level is one of the allowed values.

        Args:
            v: The raw LOG_LEVEL value (case-insensitive).

        Returns:
            str: The uppercased logging level.

        Raises:
            ValueError: If the value is not one of DEBUG, INFO, WARNING,
                ERROR, or CRITICAL.
        """
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()

        if v_upper not in valid_levels:
            raise ValueError(
                f"LOG_LEVEL must be one of: {', '.join(valid_levels)}. " f"Received: {v}"
            )

        return v_upper

    @field_validator("DATA_DIR")
    @classmethod
    def anchor_data_dir(cls, v: Path) -> Path:
        """Anchor a relative DATA_DIR on the project root, never the CWD.

        A relative path resolves against the process working directory, so a
        launch from a different CWD (systemd WorkingDirectory, cron wrapper) would
        silently create a second data/ folder and diverge from the intended state.
        Absolute paths are kept as-is.

        Args:
            v: The configured DATA_DIR (relative or absolute).

        Returns:
            Path: An absolute path anchored on the project root when v is relative.
        """
        path = Path(v)
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[2]
            path = project_root / path
        return path

    @model_validator(mode="after")
    def validate_at_least_one_provider(self) -> "Settings":
        """Validate that at least one provider was discovered from the environment.

        Returns:
            Settings: The validated settings instance (self).

        Raises:
            ValueError: If no provider could be discovered from environment variables.
        """
        provider_configs = self.get_provider_configs()

        if not provider_configs:
            raise ValueError(
                "No provider was found in the environment variables! "
                "Add keys to the .env file following the template:\n"
                "  - Hetzner: HETZNER_{SUFFIX}_API_KEY (for example, HETZNER_PROD_API_KEY)\n"
                "  - Vultr: VULTR_{SUFFIX}_API_KEY (for example, VULTR_MAIN_API_KEY)\n"
                "  - AWS: AWS_{SUFFIX}_ACCESS_KEY_ID + AWS_{SUFFIX}_SECRET_ACCESS_KEY"
            )

        return self

    # === PROVIDER METHODS ===

    def get_provider_configs(self) -> dict[str, ProviderConfig]:
        """
        Return configurations for all providers discovered from the environment.

        Uses auto-discovery: scans environment variables against the known
        patterns and automatically builds provider configurations.

        Returns:
            dict[str, ProviderConfig]: Mapping of {alias: ProviderConfig}.
        """
        discovered = discover_providers_from_env()
        return {alias: generate_provider_config(d) for alias, d in discovered.items()}

    def get_provider_api_key(self, alias: str) -> str | None:
        """
        Get a provider's API key by alias.

        Looks up the environment variable following the pattern: {ALIAS}_API_KEY

        Examples:
        - alias="hetzner_prod" -> HETZNER_PROD_API_KEY
        - alias="vultr_main" -> VULTR_MAIN_API_KEY

        Args:
            alias: Provider alias (e.g. "hetzner_prod").

        Returns:
            str | None: The API key, or None if not found.
        """
        return get_provider_api_key_from_env(alias)

    def get_provider_aws_credentials(self, alias: str) -> tuple[str, str] | None:
        """
        Get AWS credentials by alias.

        Looks up the environment variables:
        - {ALIAS}_ACCESS_KEY_ID
        - {ALIAS}_SECRET_ACCESS_KEY

        Examples:
        - alias="aws_prod" -> AWS_PROD_ACCESS_KEY_ID, AWS_PROD_SECRET_ACCESS_KEY

        Args:
            alias: Provider alias (e.g. "aws_prod").

        Returns:
            tuple[str, str] | None: (access_key_id, secret_access_key), or None
                if either variable is missing.
        """
        return get_provider_aws_credentials_from_env(alias)

    # === METHODS ===

    def get_admin_ids_list(self) -> list[int]:
        """Return the list of administrator IDs as integers.

        Returns:
            list[int]: Parsed admin IDs, or an empty list if ADMIN_IDS is unset.
        """
        if not self.ADMIN_IDS:
            return []
        return [
            int(admin_id.strip())
            for admin_id in self.ADMIN_IDS.split(",")
            if admin_id.strip()
        ]

    def ensure_data_dir(self) -> None:
        """Create the data directory if it does not already exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def get_servers_file(self) -> Path:
        """Return the path to the servers.json file.

        Returns:
            Path: DATA_DIR joined with "servers.json".
        """
        return self.DATA_DIR / "servers.json"

    def get_balance_history_file(self) -> Path:
        """Return the path to the balance_history.json file.

        Returns:
            Path: DATA_DIR joined with "balance_history.json".
        """
        return self.DATA_DIR / "balance_history.json"

    def get_runtime_settings_file(self) -> Path:
        """Return the path to the runtime_settings.json file.

        Returns:
            Path: DATA_DIR joined with "runtime_settings.json".
        """
        return self.DATA_DIR / "runtime_settings.json"


# === SINGLETON ===

_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    Loads settings from config.yaml and the .env file on the first call;
    subsequent calls return the cached instance.

    Priority: .env > config.yaml > default values.

    Returns:
        Settings: The cached, lazily-initialized settings instance, with its
            data directory already ensured to exist.
    """
    global _settings

    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
        _settings.ensure_data_dir()

    return _settings
