"""
Hetzner Cloud provider for managing servers via the Hetzner Cloud API.

API Documentation: https://docs.hetzner.cloud/
"""

import logging
from typing import Any

import httpx

from ..exceptions import (
    HetznerAPIError,
    HetznerAuthenticationError,
    HetznerConflictError,
    HetznerLockedError,
    HetznerNotFoundError,
    HetznerPermissionError,
    HetznerRateLimitError,
    HetznerServerError,
)
from ..models import ProviderType, Server, ServerStatus
from ..models.billing import BillingModel
from .base import BaseProvider
from .mixins import HttpClientMixin, RetryConfig, RetryMixin

logger = logging.getLogger(__name__)

# Constants protecting against infinite loops
MAX_PAGINATION_PAGES = 1000  # Maximum pages during pagination (guard against API errors)


class HetznerProvider(BaseProvider, HttpClientMixin, RetryMixin):
    """
    Provider for working with the Hetzner Cloud API.

    Supports:
    - Fetching the server list (with pagination)
    - Server management (power on, power off, shutdown, reboot)
    - Retry logic with exponential backoff via RetryMixin
    - Rate limiting (3600 req/hour)
    - Graceful shutdown of the HTTP client via HttpClientMixin

    Rate Limits:
        3600 requests per hour (roughly 1 req/sec)
        Headers: RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset

    Example:
        >>> provider = HetznerProvider(api_key="your_api_key")
        >>> servers = await provider.get_servers()
        >>> await provider.start_server(server_id="12345678")
        >>> await provider.close()
    """

    def __init__(
        self,
        api_key: str,
        alias: str = "",
        display_name: str = "",
        emoji: str = "",
    ):
        """
        Initialize the Hetzner Cloud provider.

        Args:
            api_key: Hetzner Cloud API key (obtain it at console.hetzner.cloud)
            alias: Unique identifier of the instance
            display_name: Display name for the UI
            emoji: ASCII emoji for the UI
        """
        super().__init__(alias=alias, display_name=display_name, emoji=emoji)
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        """Base URL of the Hetzner Cloud API."""
        return "https://api.hetzner.cloud/v1"

    @property
    def headers(self) -> dict[str, str]:
        """HTTP headers for the Hetzner API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:
        """
        Decide whether the request should be retried for Hetzner.

        Retry strategy:
        - 429 (Rate Limit): retry honoring the Retry-After header
        - 500-503 (Server Error): retry with exponential backoff
        - Network errors: retry with exponential backoff
        - 401, 403, 404, 409, 423: NO retry

        Args:
            error: The raised exception
            attempt: Attempt number (0-based)

        Returns:
            tuple[bool, float]: (should_retry, custom_wait_time)
        """
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code

            # 429 - rate limit (retry honoring Retry-After)
            if status == 429:
                retry_after = error.response.headers.get("Retry-After")
                wait_time = float(retry_after) if retry_after else 0.0
                logger.warning(f"Hetzner rate limit hit, waiting {wait_time}s")
                return True, wait_time

            # 500-503 - server error (retry)
            if 500 <= status <= 503:
                logger.warning(f"Hetzner server error {status}")
                return True, 0.0

            # 401, 403, 404, 409, 423 - no retry
            return False, 0.0

        # Network errors (retry)
        if isinstance(error, (httpx.RequestError, httpx.TimeoutException)):
            logger.warning(f"Hetzner network error: {error}")
            return True, 0.0

        return False, 0.0

    def _transform_error(self, error: Exception) -> Exception:
        """
        Transform an error into a Hetzner-specific exception.

        Args:
            error: The original exception

        Returns:
            Exception: A Hetzner-specific exception
        """
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            response_body = error.response.text if hasattr(error.response, "text") else None

            if status == 401:
                logger.error("Hetzner authentication error")
                return HetznerAuthenticationError(response_body=response_body)

            if status == 403:
                operation = str(error.request.url.path).split("/")[-1]
                logger.error(f"Hetzner permission error for operation: {operation}")
                return HetznerPermissionError(operation=operation, response_body=response_body)

            if status == 404:
                resource_type, resource_id = self._split_resource_path(
                    str(error.request.url.path)
                )
                logger.warning(f"Hetzner resource not found: {resource_type}/{resource_id}")
                return HetznerNotFoundError(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    response_body=response_body,
                )

            if status == 409:
                operation = str(error.request.url.path).split("/")[-1]
                logger.warning(f"Hetzner conflict error for operation: {operation}")
                return HetznerConflictError(
                    operation=operation,
                    server_status="unknown",
                    response_body=response_body,
                )

            if status == 423:
                _, resource_id = self._split_resource_path(str(error.request.url.path))
                logger.warning(f"Hetzner resource locked: {resource_id}")
                return HetznerLockedError(resource_id=resource_id, response_body=response_body)

            if status == 429:
                logger.error("Hetzner rate limit exceeded after all attempts")
                return HetznerRateLimitError(
                    retry_after=self._parse_retry_after(error.response),
                    response_body=response_body,
                )

            if 500 <= status <= 503:
                logger.error(f"Hetzner server error {status} after all attempts")
                return HetznerServerError(status_code=status, response_body=response_body)

            logger.error(f"Unexpected Hetzner API error {status}")
            return HetznerAPIError(
                message=f"Unexpected API error: HTTP {status}",
                status_code=status,
                response_body=response_body,
            )

        if isinstance(error, (httpx.RequestError, httpx.TimeoutException)):
            logger.error(f"Hetzner network error after all attempts: {error}")
            return HetznerAPIError(
                message=f"Network error: {str(error)}",
                status_code=None,
                response_body=None,
            )

        return error

    async def _fetch_all_paginated(
        self, endpoint: str, data_key: str, per_page: int = 50
    ) -> list[dict[str, Any]]:
        """
        Fetch all items using page-based pagination.

        Hetzner uses page-based pagination:
        - ?page=1&per_page=50
        - Maximum per_page: 50
        - Meta returns: page, per_page, previous_page, next_page, last_page, total_entries

        Args:
            endpoint: API endpoint (e.g., "/servers")
            data_key: Key in the response holding the data (e.g., "servers")
            per_page: Number of items per page (maximum 50)

        Returns:
            List of all items across all pages
        """
        all_items: list[dict[str, Any]] = []
        page = 1
        pages_fetched = 0

        while pages_fetched < MAX_PAGINATION_PAGES:
            url = f"{self.base_url}{endpoint}?page={page}&per_page={per_page}"

            async def make_request() -> dict[str, Any]:
                """Perform a single GET request for the current page and return the parsed JSON."""
                return await self._get_json(url)

            data = await self._retry_with_backoff(make_request)

            # Append the items from the current page
            items = data.get(data_key, [])
            all_items.extend(items)
            pages_fetched += 1

            # Check whether there is a next page
            meta = data.get("meta", {})
            pagination = meta.get("pagination", {})
            next_page = pagination.get("next_page")

            # If there is no next page - exit
            if next_page is None:
                break

            page = next_page
        else:
            # Loop ended because of the page limit (not via break)
            logger.error(
                f"Pagination limit reached ({MAX_PAGINATION_PAGES} pages) for {endpoint}. "
                f"This might indicate an API error or misconfiguration."
            )
            raise HetznerAPIError(
                f"Exceeded maximum pagination pages ({MAX_PAGINATION_PAGES}) for {endpoint}"
            )

        return all_items

    def _parse_hetzner_server(self, server_data: dict[str, Any]) -> Server:
        """
        Convert server data from the Hetzner API into a Server model.

        Args:
            server_data: Dictionary with server data from Hetzner

        Returns:
            A Server object with mapped fields
        """
        # Server ID (integer in Hetzner -> string in our model)
        server_id = str(server_data["id"])

        # Server name
        name = server_data.get("name", server_id)

        # IP address for ping - try to get IPv4, then IPv6
        ip = None
        public_net = server_data.get("public_net", {})
        if public_net:
            # Try IPv4
            ipv4 = public_net.get("ipv4", {})
            if ipv4:
                ip = ipv4.get("ip")

            # Fall back to IPv6 if there is no IPv4
            if not ip:
                ipv6 = public_net.get("ipv6", {})
                if ipv6:
                    ip = ipv6.get("ip")

        # If there is neither IPv4 nor IPv6 - use a fallback
        if not ip:
            logger.warning(
                f"Server {server_id} has no public IP address. "
                f"Monitoring may not work correctly."
            )
            ip = "0.0.0.0"

        # Region (datacenter location)
        region = "unknown"
        datacenter = server_data.get("datacenter", {})
        if datacenter:
            location = datacenter.get("location", {})
            if location:
                region = location.get("name", "unknown")  # nbg1, fsn1, hel1, etc.

        # Plan (server type)
        plan = "unknown"
        server_type = server_data.get("server_type", {})
        if server_type:
            plan = server_type.get("name", "unknown")  # cx11, cpx22, etc.

        # OS (image)
        os_str = None
        image = server_data.get("image")
        if image:
            os_flavor = image.get("os_flavor", "")
            os_version = image.get("os_version", "")
            if os_flavor and os_version:
                os_str = f"{os_flavor} {os_version}"
            elif os_flavor:
                os_str = os_flavor

        # RAM (in MB)
        ram_mb = None
        if server_type:
            ram_gb = server_type.get("memory")  # In GB (e.g., 2.0)
            if ram_gb:
                ram_mb = int(ram_gb * 1024)  # Convert to MB

        # Disk (in GB)
        disk_gb = None
        if server_type:
            disk_gb = server_type.get("disk")

        # vCPU count
        vcpu_count = None
        if server_type:
            vcpu_count = server_type.get("cores")

        # Power status from Hetzner
        power_status = server_data.get("status", "unknown")

        return Server(
            id=server_id,
            provider=ProviderType.HETZNER,
            provider_alias=self._alias,
            name=name,
            ip=ip,
            region=region,
            plan=plan,
            status=ServerStatus.UNKNOWN,  # Status is determined by ping, not the API
            os=os_str,
            ram_mb=ram_mb,
            disk_gb=disk_gb,
            vcpu_count=vcpu_count,
            power_status=power_status,
        )

    # ========== REQUIRED BaseProvider METHODS ==========

    async def get_servers(self) -> list[Server]:
        """
        Fetch the list of all servers from Hetzner Cloud.

        Uses pagination to retrieve all servers (max 50 per page).

        Returns:
            List of servers

        Raises:
            HetznerAuthenticationError: On an invalid API token
            HetznerAPIError: On API errors
        """
        try:
            servers_data = await self._fetch_all_paginated(
                endpoint="/servers",
                data_key="servers",
                per_page=50,  # Maximum for Hetzner
            )

            servers = [self._parse_hetzner_server(s) for s in servers_data]
            return servers

        except (HetznerAuthenticationError, HetznerAPIError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching servers from Hetzner: {e}", exc_info=True)
            raise HetznerAPIError(f"Unexpected error: {str(e)}") from e

    async def get_server(self, server_id: str) -> Server | None:
        """
        Fetch information about a specific server.

        Args:
            server_id: Server ID

        Returns:
            A Server object, or None if the server is not found

        Raises:
            HetznerAuthenticationError: On an invalid API token
            HetznerAPIError: On other API errors
        """
        try:

            async def make_request() -> dict[str, Any]:
                """Perform a single GET request for one server and return the parsed JSON."""
                url = f"{self.base_url}/servers/{server_id}"
                return await self._get_json(url)

            data = await self._retry_with_backoff(make_request)

            server_data = data.get("server")
            if not server_data:
                logger.warning(f"Server {server_id} not found in Hetzner response")
                return None

            return self._parse_hetzner_server(server_data)

        except HetznerNotFoundError:
            logger.warning(f"Server {server_id} not found in Hetzner")
            return None
        except (HetznerAuthenticationError, HetznerAPIError):
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error fetching server {server_id} from Hetzner: {e}",
                exc_info=True,
            )
            raise HetznerAPIError(f"Unexpected error: {str(e)}") from e

    async def _power_action(
        self,
        server_id: str,
        action_path: str,
        *,
        verb: str,
        gerund: str,
        done: str,
    ) -> bool:
        """Perform a power operation on a server (poweron/poweroff/reboot/shutdown).

        Shared implementation for start/stop/reboot/shutdown_server — they differ
        only in the endpoint and the log text.

        Args:
            server_id: Server ID
            action_path: Action endpoint suffix (poweron/poweroff/reboot/shutdown)
            verb: Verb used in error logs (start/stop/reboot/shutdown)
            gerund: Gerund used in in-progress and unexpected-error logs (starting/...)
            done: Past participle used in the success log (started/stopped/...)

        Returns:
            True if the operation succeeded, False on error
        """
        logger.info(f"{gerund.capitalize()} Hetzner server {server_id}...")

        try:

            async def make_request() -> dict[str, Any]:
                """Perform a single POST request for the power action and return the parsed JSON."""
                url = f"{self.base_url}/servers/{server_id}/actions/{action_path}"
                return await self._post_json(url)

            # Critical operation - 5 attempts instead of 3
            await self._retry_with_backoff(make_request, config=RetryConfig(max_retries=5))

            logger.info(f"Hetzner server {server_id} {done}")
            return True

        except (HetznerConflictError, HetznerLockedError):
            # State conflict or the server is locked - this is normal
            logger.warning(f"Cannot {verb} server {server_id}: conflict or locked")
            return False
        except (HetznerAuthenticationError, HetznerPermissionError, HetznerAPIError) as e:
            logger.error(f"Failed to {verb} Hetzner server {server_id}: {e}")
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error {gerund} Hetzner server {server_id}: {e}",
                exc_info=True,
            )
            return False

    async def start_server(self, server_id: str) -> bool:
        """Start a stopped server (POST /servers/{id}/actions/poweron)."""
        return await self._power_action(
            server_id, "poweron", verb="start", gerund="starting", done="started"
        )

    async def stop_server(self, server_id: str) -> bool:
        """Hard power off a server (POST /servers/{id}/actions/poweroff)."""
        return await self._power_action(
            server_id, "poweroff", verb="stop", gerund="stopping", done="stopped"
        )

    async def reboot_server(self, server_id: str) -> bool:
        """Reboot a server via ACPI (POST /servers/{id}/actions/reboot)."""
        return await self._power_action(
            server_id, "reboot", verb="reboot", gerund="rebooting", done="rebooted"
        )

    async def shutdown_server(self, server_id: str) -> bool:
        """Gracefully shut down a server via ACPI (POST /servers/{id}/actions/shutdown)."""
        return await self._power_action(
            server_id, "shutdown", verb="shutdown", gerund="shutting down", done="shutdown"
        )

    async def get_balance(self) -> None:
        """
        Fetch account balance information.

        IMPORTANT: The Hetzner Cloud API does NOT expose balance information!
        The balance is available only via the web console or api.hetzner.com
        (for the whole account).

        Returns:
            None: The balance is not available through the Hetzner Cloud API

        Raises:
            Does not raise any exceptions
        """
        return None

    async def health_check(self) -> bool:
        """
        Check availability of the Hetzner Cloud API.

        Performs a simple GET /servers request with a 10-second timeout.

        Returns:
            True if the API is reachable, False otherwise
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.base_url}/servers?per_page=1", timeout=10.0)
            response.raise_for_status()
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Hetzner health check HTTP error: {e}", exc_info=True)
            return False
        except httpx.RequestError as e:
            logger.error(f"Hetzner health check network error: {e}", exc_info=True)
            return False

    def get_provider_name(self) -> str:
        """Return the provider name."""
        return "hetzner"

    def supports_balance(self) -> bool:
        """
        The Hetzner Cloud API does not expose balance information.

        Returns:
            bool: False - the balance is not available through the API
        """
        return False

    def supports_graceful_shutdown(self, server_id: str | None = None) -> bool:
        """
        Hetzner supports graceful shutdown via ACPI
        (POST /servers/{id}/actions/shutdown) for all servers.

        Args:
            server_id: Optional server ID; ignored because the capability applies
                to every server.

        Returns:
            bool: True
        """
        return True

    def get_billing_model(self) -> BillingModel:
        """
        Hetzner uses a postpaid billing model.

        Invoices are issued retroactively for the previous month.
        Per the documentation: "It is not possible to pay in advance".
        Hourly billing with a monthly cap.

        Returns:
            BillingModel: POSTPAID
        """
        return BillingModel.POSTPAID
