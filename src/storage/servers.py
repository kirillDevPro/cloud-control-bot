"""Repository for managing the list of servers with a TTL cache."""

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..models import Server, ServerStatus, ProviderType
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CachedData:
    """Container for cached data with a TTL."""

    def __init__(self, data: list[Server], ttl_seconds: float = 30.0):
        """
        Initialize the cache with data.

        Args:
            data: List of servers to cache
            ttl_seconds: Cache lifetime in seconds
        """
        self.data = data
        self.created_at = datetime.now()
        self.ttl = timedelta(seconds=ttl_seconds)

    def is_valid(self) -> bool:
        """
        Check whether the cache is still valid.

        Returns:
            bool: True if the cache has not yet expired
        """
        return datetime.now() - self.created_at < self.ttl


class ServersRepository(BaseRepository[Server]):
    """
    Repository for working with the list of servers.

    Provides CRUD operations on servers.
    Uses a TTL cache to optimize frequent get_all() calls.
    The cache is automatically invalidated on any change.
    """

    # Cache lifetime in seconds
    CACHE_TTL_SECONDS: float = 30.0

    def __init__(self, file_path: Path):
        """
        Initialize the servers repository.

        Args:
            file_path: Path to servers.json
        """
        super().__init__(file_path)
        self._cache: CachedData | None = None
        self._cache_lock = threading.Lock()

    def _invalidate_cache(self) -> None:
        """Invalidate the cache (thread-safe)."""
        with self._cache_lock:
            self._cache = None

    def _get_empty_data(self) -> list:
        """Return an empty server list for repository initialization.

        Returns:
            list: Empty list used when the storage file does not exist yet.
        """
        return []

    def get_all(self) -> list[Server]:
        """
        Get all servers using the TTL cache.

        The cache lives for CACHE_TTL_SECONDS seconds, after which it is refreshed.
        On any change (add, update, remove) the cache is invalidated.

        Returns:
            list[Server]: List of all servers
        """
        with self._cache_lock:
            # Check whether the cache is valid
            if self._cache is not None and self._cache.is_valid():
                return list(self._cache.data)  # Shallow copy for thread-safety

            # Cache is invalid - load the data
            data = self.load_all()
            servers = [Server(**item) for item in data]

            # Store in the cache
            self._cache = CachedData(servers, self.CACHE_TTL_SECONDS)

            return list(servers)  # Shallow copy for thread-safety

    def get_by_id(self, server_id: str, provider: ProviderType | None = None) -> Server | None:
        """
        Get a server by ID.

        IMPORTANT: If provider is specified, the lookup uses the composite key (provider, id).
        This prevents conflicts when servers from different providers share the same ID.

        Args:
            server_id: Server ID
            provider: Provider type (optional, for an exact lookup)

        Returns:
            Server | None: The server, or None if not found
        """
        servers = self.get_all()

        # If provider is specified, look up by the composite key
        if provider is not None:
            for server in servers:
                if server.id == server_id and server.provider == provider:
                    return server
            return None

        # If provider is not specified, look up by ID only
        # WARNING: May return the wrong server if there is an ID conflict!
        matching_servers = [s for s in servers if s.id == server_id]

        if len(matching_servers) > 1:
            logger.warning(
                f"Found {len(matching_servers)} servers with ID '{server_id}' "
                f"from different providers. Returning first match. "
                f"Consider specifying provider parameter to avoid ambiguity."
            )

        return matching_servers[0] if matching_servers else None

    def get_by_composite_key(self, composite_key: str) -> Server | None:
        """
        Get a server by its composite key.

        The composite key has the format:
        - New: "provider_alias:server_id" (e.g. "hetzner_prod:abc-123")
        - Legacy: "provider:server_id" (e.g. "vultr:abc-123")

        The method first tries to find the server by provider_alias, then by provider.value.

        Args:
            composite_key: Composite key

        Returns:
            Server | None: The server, or None if not found or the key format is invalid
        """
        try:
            # Split the composite key into prefix and server_id
            parts = composite_key.split(":", 1)
            if len(parts) != 2:
                logger.error(
                    f"Invalid composite key format: '{composite_key}'. "
                    f"Expected format: 'provider_alias:server_id' or 'provider:server_id'"
                )
                return None

            prefix, server_id = parts

            # First try to find the server by provider_alias
            server = self.get_by_provider_alias_and_id(prefix, server_id)
            if server:
                return server

            # Fallback: try treating the prefix as provider.value (legacy format)
            try:
                provider = ProviderType(prefix.lower())
                return self.get_by_id(server_id, provider)
            except ValueError:
                # This is NOT an error - the server simply is not found (neither by alias
                # nor by the legacy format). For example, when checking for existence
                # before adding a new server.
                return None

        except (ValueError, AttributeError) as e:
            logger.error(f"Error parsing composite key '{composite_key}': {e}", exc_info=True)
            return None

    def get_by_provider_alias(self, provider_alias: str) -> list[Server]:
        """
        Get servers by provider alias.

        Args:
            provider_alias: Provider alias (e.g. "hetzner_prod")

        Returns:
            list[Server]: List of the provider's servers
        """
        servers = self.get_all()
        return [s for s in servers if s.provider_alias == provider_alias]

    def get_by_provider_alias_and_id(
        self, provider_alias: str, server_id: str
    ) -> Server | None:
        """
        Get a server by provider alias and server ID.

        Args:
            provider_alias: Provider alias (e.g. "hetzner_prod")
            server_id: Server ID

        Returns:
            Server | None: The server, or None if not found
        """
        servers = self.get_all()
        for server in servers:
            if server.provider_alias == provider_alias and server.id == server_id:
                return server
        return None

    def get_enabled(self) -> list[Server]:
        """
        Get servers that have monitoring enabled.

        Returns:
            list[Server]: List of servers with enabled=True
        """
        servers = self.get_all()
        return [s for s in servers if s.enabled]

    def add_server(self, server: Server) -> Server:
        """
        Add a new server.

        IMPORTANT: The existence check is performed by composite_key (provider_alias:id),
        which allows adding servers with the same ID from different accounts
        (e.g. hetzner_prod:123 and hetzner_staging:123).

        Args:
            server: Server object to add

        Returns:
            Server: The added server

        Raises:
            ValueError: If a server with the same composite_key already exists
        """
        # Check by composite_key (accounts for provider_alias)
        existing = self.get_by_composite_key(server.composite_key)
        if existing:
            raise ValueError(
                f"Server with composite_key {server.composite_key} already exists"
            )

        servers = self.get_all()
        servers.append(server)
        self._save_servers(servers)

        return server

    def update_server(self, server: Server) -> Server:
        """
        Update an existing server.

        IMPORTANT: The server is identified by composite_key (provider_alias:id)
        to work correctly with multiple accounts of the same provider.

        Args:
            server: Server object with updated data

        Returns:
            Server: The updated server

        Raises:
            ValueError: If the server is not found
        """
        servers = self.get_all()
        updated = False

        for i, s in enumerate(servers):
            # Use composite_key for correct identification
            # (accounts for provider_alias for multi-account support)
            if s.composite_key == server.composite_key:
                servers[i] = server
                updated = True
                break

        if not updated:
            raise ValueError(
                f"Server with ID {server.id} (provider: {server.provider.value}) not found"
            )

        self._save_servers(servers)
        return server

    def remove_server(self, server_id: str, provider: ProviderType | None = None) -> bool:
        """
        Remove a server by ID.

        IMPORTANT: If provider is specified, removal uses the composite key (provider, id).
        This prevents accidental removal of other providers' servers with the same ID.

        Args:
            server_id: Server ID
            provider: Provider type (RECOMMENDED to avoid ambiguity)

        Returns:
            bool: True if the server was removed, False if not found
        """
        servers = self.get_all()
        initial_count = len(servers)

        if provider is not None:
            # Remove by the composite key (provider, id)
            servers = [s for s in servers if not (s.id == server_id and s.provider == provider)]
        else:
            # Remove all servers with this ID (legacy behavior)
            matching = [s for s in servers if s.id == server_id]
            if len(matching) > 1:
                logger.warning(
                    f"Found {len(matching)} servers with ID '{server_id}' from different providers. "
                    f"All will be removed. Consider specifying provider parameter."
                )
            servers = [s for s in servers if s.id != server_id]

        removed_count = initial_count - len(servers)
        if removed_count == 0:
            logger.warning(f"Attempt to remove a nonexistent server: {server_id}")
            return False

        self._save_servers(servers)
        return True

    def remove_server_by_composite_key(self, composite_key: str) -> bool:
        """
        Remove a server by composite_key (provider_alias:server_id).

        IMPORTANT: This method guarantees exact removal of a specific server,
        unlike remove_server(), which may remove several servers with the same ID
        from different accounts.

        Args:
            composite_key: Server composite key (e.g. "hetzner_prod:12345")

        Returns:
            bool: True if the server was removed, False if not found
        """
        servers = self.get_all()
        initial_count = len(servers)
        servers = [s for s in servers if s.composite_key != composite_key]

        if len(servers) == initial_count:
            logger.warning(f"Server not found by composite_key: {composite_key}")
            return False

        self._save_servers(servers)
        return True

    def update_status(
        self, server_id: str, status: ServerStatus, provider: ProviderType | None = None
    ) -> Server | None:
        """
        Update a server's status.

        Args:
            server_id: Server ID
            status: New status
            provider: Provider type (recommended to avoid ambiguity)

        Returns:
            Server | None: The updated server, or None if not found
        """
        from datetime import datetime

        server = self.get_by_id(server_id, provider)
        if not server:
            logger.warning(f"Attempt to update the status of a nonexistent server: {server_id}")
            return None

        server.status = status

        # Update last_seen if the server is online
        if status == ServerStatus.ONLINE:
            server.last_seen = datetime.now()

        self.update_server(server)
        return server

    def bulk_update_from_api(self, api_servers: list[Server]) -> dict:
        """
        Bulk-update the list of servers from a provider's API.

        Adds new servers and updates existing ones.
        Does NOT remove servers that are absent from the API (they may have been added manually).

        IMPORTANT: Uses composite_key (provider_alias:id) for identification so
        two accounts of the same provider type that share a bare id are not
        collapsed, and writes the file ONCE at the end instead of per row
        (avoids O(N^2) JSON rewrites).

        Args:
            api_servers: List of servers from the API

        Returns:
            dict: Operation statistics (added, updated, unchanged)
        """
        # Identify by composite_key (alias-aware), like sync_with_api_servers.
        existing_servers = {s.composite_key: s for s in self.get_all()}
        stats = {"added": 0, "updated": 0, "unchanged": 0}

        # Accumulate changes in memory and persist once at the end.
        result_map: dict[str, Server] = dict(existing_servers)
        changed = False

        for api_server in api_servers:
            key = api_server.composite_key

            if key in existing_servers:
                # Server exists - update its data
                existing = existing_servers[key]

                # Preserve runtime state. `enabled` is NOT preserved: it has no
                # user toggle and is provider-driven (recomputed from public-IP
                # presence), so an AWS instance that loses/regains a pingable IP
                # is correctly dis/re-enabled by the parser.
                api_server.status = existing.status
                api_server.last_seen = existing.last_seen
                api_server.added_at = existing.added_at

                # Check whether the data changed
                if self._server_data_changed(existing, api_server):
                    result_map[key] = api_server
                    stats["updated"] += 1
                    changed = True
                else:
                    stats["unchanged"] += 1
            else:
                # New server: keep the provider-parsed `enabled` (True by default;
                # AWS sets it False for an instance with no pingable public IP, so
                # it is not monitored and won't raise false-offline alerts).
                result_map[key] = api_server
                stats["added"] += 1
                changed = True

        # A single file write for the whole sync (instead of N rewrites).
        if changed:
            self._save_servers(list(result_map.values()))

        return stats

    def sync_with_api_servers(
        self,
        api_servers: list[Server],
        successful_aliases: set[str],
    ) -> dict:
        """
        Synchronize servers with the providers' APIs.

        Unlike bulk_update_from_api, this method also REMOVES servers that are
        no longer present in the API. New servers keep the provider-parsed
        `enabled` flag (True by default; AWS sets it False for an instance
        without a pingable public IP).

        IMPORTANT: Uses the composite key (provider_alias, id) for correct identification.
        IMPORTANT: Servers of providers that are not in successful_aliases are
        NOT removed (the provider may be temporarily unavailable).

        Args:
            api_servers: List of servers from the API
            successful_aliases: Set of provider aliases that responded successfully.
                Only servers from these providers are removed.

        Returns:
            dict: Detailed operation statistics:
                - added_servers: list[Server] - list of added servers
                - removed_servers: list[Server] - list of removed servers
                - updated_servers: list[Server] - list of updated servers
                - ip_changed_servers: list[tuple[Server, str]] - servers whose IP changed
                  (new server, old IP) - require restarting their worker
                - unchanged_count: int - number of servers with no changes
                - skipped_removal_count: int - number of servers skipped during removal
                - skipped_aliases: set[str] - aliases of providers whose servers were skipped
        """
        from collections import defaultdict

        # Deduplicate by composite_key. A provider should not return servers
        # with the same key, but we guard against it: otherwise a duplicate would
        # inflate the added_servers counter and diverge from the actual file state.
        deduped: dict[str, Server] = {}
        for api_server in api_servers:
            if api_server.composite_key in deduped:
                logger.warning(
                    f"Duplicate composite_key {api_server.composite_key} in API response, "
                    f"keeping the last occurrence"
                )
            deduped[api_server.composite_key] = api_server
        api_servers = list(deduped.values())

        # Get the current servers
        existing_servers_list = self.get_all()
        # Use composite_key for identification (works with aliases)
        existing_servers = {s.composite_key: s for s in existing_servers_list}

        # Build the set of keys from the API (using composite_key)
        api_keys = {s.composite_key for s in api_servers}

        # Initialize the results
        added_servers: list[Server] = []
        removed_servers: list[Server] = []
        updated_servers: list[Server] = []
        # Servers whose IP changed (require restarting their worker)
        ip_changed_servers: list[tuple[Server, str]] = []  # (server, old_ip)
        unchanged_count = 0
        # Servers skipped during removal (provider unavailable)
        skipped_removal_count = 0
        skipped_aliases: set[str] = set()

        # Per-provider statistics
        provider_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"added": 0, "removed": 0, "updated": 0, "unchanged": 0}
        )

        # Working copy used to accumulate changes in memory.
        # IMPORTANT: we mutate result_map and save it ONCE at the end (_save_servers),
        # instead of calling add/update/remove in the loop — otherwise O(N^2) JSON rewrites.
        result_map: dict[str, Server] = dict(existing_servers)

        # Process servers from the API (additions and updates)
        for api_server in api_servers:
            key = api_server.composite_key
            # Use the alias if present, otherwise provider.value for statistics
            provider_name = api_server.effective_alias

            if key in existing_servers:
                # Server exists - update its data
                existing = existing_servers[key]

                # Preserve runtime state and identifiers. `enabled` is NOT
                # preserved: it has no user toggle and is provider-driven
                # (recomputed from public-IP presence), so an AWS instance that
                # loses/regains a pingable IP is correctly dis/re-enabled.
                api_server.provider_alias = existing.provider_alias or api_server.provider_alias
                api_server.status = existing.status
                api_server.last_seen = existing.last_seen
                api_server.added_at = existing.added_at

                # Check whether the data changed
                if self._server_data_changed(existing, api_server):
                    # Check whether the IP changed (critical for restarting the worker)
                    if existing.ip != api_server.ip:
                        ip_changed_servers.append((api_server, existing.ip))
                    result_map[key] = api_server
                    updated_servers.append(api_server)
                    provider_stats[provider_name]["updated"] += 1
                else:
                    unchanged_count += 1
                    provider_stats[provider_name]["unchanged"] += 1
            else:
                # New server: keep the provider-parsed `enabled` (True by default;
                # AWS sets it False for an instance with no pingable public IP, so
                # it is not monitored and won't raise false-offline alerts).
                result_map[key] = api_server
                added_servers.append(api_server)
                provider_stats[provider_name]["added"] += 1

        # Find and remove servers that are no longer present in the API
        for key, existing_server in existing_servers.items():
            if key not in api_keys:
                # Get the server's alias (effective_alias accounts for the legacy format)
                server_alias = existing_server.effective_alias

                # Check whether the provider was available
                if server_alias not in successful_aliases:
                    # Provider unavailable - do NOT remove the server
                    logger.debug(
                        f"Skipping removal of {existing_server.composite_key}: "
                        f"provider {server_alias} was unavailable"
                    )
                    skipped_removal_count += 1
                    skipped_aliases.add(server_alias)
                    continue

                # The server is absent from the API and the provider was available - remove it.
                # IMPORTANT: Use composite_key for exact removal, otherwise we might
                # remove servers with the same ID from other accounts.
                del result_map[key]
                removed_servers.append(existing_server)
                provider_stats[server_alias]["removed"] += 1

        # A single file write for the whole sync (instead of N rewrites).
        # Write only if something changed — otherwise an unnecessary cache invalidation.
        if added_servers or removed_servers or updated_servers:
            self._save_servers(list(result_map.values()))

        return {
            "added_servers": added_servers,
            "removed_servers": removed_servers,
            "updated_servers": updated_servers,
            "ip_changed_servers": ip_changed_servers,
            "unchanged_count": unchanged_count,
            "skipped_removal_count": skipped_removal_count,
            "skipped_aliases": skipped_aliases,
        }

    def _save_servers(self, servers: list[Server]) -> None:
        """
        Save the list of servers to the file and invalidate the cache.

        Args:
            servers: List of servers
        """
        data = [s.model_dump() for s in servers]
        self.save_all(data)
        # Invalidate the cache after saving
        self._invalidate_cache()

    def _server_data_changed(self, old: Server, new: Server) -> bool:
        """
        Check whether a server's data has changed.

        Args:
            old: Previous server object
            new: New server object

        Returns:
            bool: True if the data has changed
        """
        # Compare the API-derived fields plus `enabled` (provider-driven via the
        # public-IP check), so a monitorability flip is detected and persisted.
        return (
            old.name != new.name
            or old.ip != new.ip
            or old.region != new.region
            or old.plan != new.plan
            or old.os != new.os
            or old.ram_mb != new.ram_mb
            or old.disk_gb != new.disk_gb
            or old.vcpu_count != new.vcpu_count
            or old.enabled != new.enabled
        )
