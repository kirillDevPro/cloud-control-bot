"""Vultr provider for working with the Vultr API v2."""

import logging
from datetime import datetime
from typing import Any

import httpx

from ..exceptions import (
    VultrAPIError,
    VultrAuthenticationError,
    VultrNotFoundError,
    VultrPermissionError,
    VultrRateLimitError,
    VultrServerError,
)
from ..models import ProviderType, Server, ServerStatus
from ..storage.balance import PrepaidBalanceRecord
from .base import BaseProvider
from .mixins import HttpClientMixin, RetryConfig, RetryMixin

logger = logging.getLogger(__name__)


class VultrProvider(BaseProvider, HttpClientMixin, RetryMixin):
    """
    Provider for working with the Vultr API v2.

    Implements full integration with the Vultr API:
    - Async HTTP client based on httpx via HttpClientMixin
    - Authentication via Bearer Token
    - Cursor-based pagination (per_page=500)
    - Rate limiting with exponential backoff via RetryMixin
    - Handling of all API error types
    - Conversion of Vultr responses into models
    """

    MAX_PAGINATION_PAGES = 100  # Guard against an infinite loop

    def __init__(
        self,
        api_key: str,
        alias: str = "",
        display_name: str = "",
        emoji: str = "",
    ):
        """
        Initialize the Vultr provider.

        Args:
            api_key: Vultr API key
            alias: Unique identifier of the provider instance
            display_name: Display name for the UI
            emoji: ASCII emoji for the UI
        """
        super().__init__(alias=alias, display_name=display_name, emoji=emoji)
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        """Return the base URL of the Vultr API v2.

        Returns:
            str: Base API URL.
        """
        return "https://api.vultr.com/v2"

    @property
    def headers(self) -> dict[str, str]:
        """Return HTTP headers for the Vultr API.

        Returns:
            dict[str, str]: Authorization and content-type headers.
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _should_retry(self, error: Exception, _attempt: int) -> tuple[bool, float]:
        """
        Decide whether a Vultr request should be retried.

        Retry strategy:
        - 429 (Rate Limit): retry honoring the Retry-After header
        - 500-503 (Server Error): retry with exponential backoff
        - Network errors: retry with exponential backoff
        - 401, 403, 404: NO retry

        Args:
            error: The raised exception
            _attempt: Attempt number (0-based), unused in this implementation

        Returns:
            tuple[bool, float]: (should_retry, custom_wait_time)
        """
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code

            # 429 - rate limit (retry honoring Retry-After)
            if status == 429:
                retry_after = error.response.headers.get("Retry-After")
                wait_time = float(retry_after) if retry_after else 0.0
                logger.warning(f"Vultr rate limit hit, waiting {wait_time}s")
                return True, wait_time

            # 500+ - server error (retry)
            if status >= 500:
                logger.warning(f"Vultr server error {status}")
                return True, 0.0

            # 401, 403, 404 - no retry
            return False, 0.0

        # Network errors (retry)
        if isinstance(error, (httpx.RequestError, httpx.TimeoutException)):
            logger.warning(f"Vultr network error: {error}")
            return True, 0.0

        return False, 0.0

    def _transform_error(self, error: Exception) -> Exception:
        """
        Transform an error into a Vultr-specific exception.

        Args:
            error: The original exception

        Returns:
            Exception: The Vultr-specific exception
        """
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            response_body = error.response.text

            if status == 401:
                logger.error("Invalid Vultr API token!")
                return VultrAuthenticationError(response_body=response_body)

            if status == 403:
                operation = str(error.request.url.path)
                logger.error(f"Insufficient permissions for operation: {operation}")
                return VultrPermissionError(operation=operation, response_body=response_body)

            if status == 404:
                resource_type, resource_id = self._split_resource_path(
                    str(error.request.url.path)
                )
                logger.warning(f"{resource_type} {resource_id} not found")
                return VultrNotFoundError(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    response_body=response_body,
                )

            if status == 429:
                logger.error("Rate limit exceeded after all retries")
                return VultrRateLimitError(
                    retry_after=self._parse_retry_after(error.response),
                    response_body=response_body,
                )

            if status >= 500:
                logger.error(f"Vultr server error {status} after all retries")
                return VultrServerError(status_code=status, response_body=response_body)

            logger.error(f"Unexpected API error ({status})")
            return VultrAPIError(
                message=f"Unexpected Vultr API error: HTTP {status}",
                status_code=status,
                response_body=response_body,
            )

        if isinstance(error, (httpx.RequestError, httpx.TimeoutException)):
            logger.error(f"Network error after all retries: {error}")
            return VultrAPIError(
                message=f"Network error while calling the Vultr API: {error}",
                status_code=None,
                response_body=None,
            )

        return error

    async def _fetch_all_paginated(
        self, endpoint: str, data_key: str, per_page: int = 500
    ) -> list[dict[str, Any]]:
        """
        Fetch all data from a paginated endpoint.

        CRITICALLY IMPORTANT: by default the Vultr API returns at most 100
        items! You must explicitly pass per_page=500 and iterate through the
        cursor until meta.links.next is empty.

        Args:
            endpoint: Relative path (e.g. "/instances")
            data_key: Key in the response (e.g. "instances")
            per_page: Number of items per page (max 500)

        Returns:
            List[Dict]: All items across every page
        """
        all_items: list[dict[str, Any]] = []
        cursor: str | None = None
        page = 0

        while True:
            page += 1

            # Guard against an infinite loop
            if page > self.MAX_PAGINATION_PAGES:
                logger.error(
                    f"Page limit exceeded ({self.MAX_PAGINATION_PAGES}) for {endpoint}. "
                    f"The API may have returned an invalid cursor. Aborting pagination."
                )
                break

            # Build the URL with query parameters
            url = f"{self.base_url}{endpoint}?per_page={per_page}"
            if cursor:
                url += f"&cursor={cursor}"

            # Perform the request with retry
            async def make_request() -> dict[str, Any]:
                """Issue a GET to the paginated endpoint URL.

                Returns:
                    dict[str, Any]: Parsed JSON response body.
                """
                client = await self._get_client()
                response = await client.get(url)
                response.raise_for_status()
                return response.json()

            data = await self._retry_with_backoff(make_request)

            # Append the items from the current page
            items = data.get(data_key, [])
            all_items.extend(items)

            # Check whether a next page exists
            # IMPORTANT: explicitly distinguish None from an empty string ""
            next_cursor = data.get("meta", {}).get("links", {}).get("next")

            # Verify that the cursor is a non-empty string
            # (guards against the empty string "", None and other falsy values)
            if not next_cursor or not isinstance(next_cursor, str) or not next_cursor.strip():
                break

            cursor = next_cursor

        return all_items

    def _parse_vultr_instance(self, instance: dict[str, Any]) -> Server:
        """
        Convert a Vultr instance into a Server model.

        Args:
            instance: Instance data from the Vultr API

        Returns:
            Server: The server object
        """
        return Server(
            id=instance["id"],
            provider=ProviderType.VULTR,
            provider_alias=self._alias,
            name=instance.get("label", instance["id"]),
            ip=instance.get("main_ip", "0.0.0.0"),
            region=instance.get("region", "unknown"),
            plan=instance.get("plan", "unknown"),
            status=ServerStatus.UNKNOWN,  # The real status is determined by ping
            os=instance.get("os"),
            ram_mb=instance.get("ram"),
            disk_gb=instance.get("disk"),
            vcpu_count=instance.get("vcpu_count"),
            power_status=instance.get("power_status"),  # Power status from the Vultr API
        )

    async def get_servers(self) -> list[Server]:
        """
        Fetch the list of all servers from the Vultr API.

        CRITICAL: uses pagination to fetch ALL servers!
        By default the Vultr API returns at most 100 servers.

        Returns:
            List[Server]: List of all servers

        Raises:
            httpx.HTTPError: On API errors
        """
        try:
            # Fetch all instances via pagination
            instances = await self._fetch_all_paginated(
                endpoint="/instances", data_key="instances", per_page=500
            )

            # Convert into Server models
            servers = [self._parse_vultr_instance(inst) for inst in instances]
            return servers

        except Exception as e:
            logger.error(f"Error fetching servers: {e}", exc_info=True)
            raise

    async def get_server(self, server_id: str) -> Server | None:
        """
        Fetch information about a specific server.

        Args:
            server_id: Server ID in Vultr

        Returns:
            Optional[Server]: The server object, or None if not found

        Raises:
            VultrAPIError: Re-raised for typed API errors other than not-found.
            Exception: Re-raised for unexpected failures.
        """
        try:

            async def make_request() -> dict[str, Any]:
                """GET a single instance by ID.

                Returns:
                    dict[str, Any]: Parsed JSON response body.
                """
                client = await self._get_client()
                url = f"{self.base_url}/instances/{server_id}"
                response = await client.get(url)
                response.raise_for_status()
                return response.json()

            data = await self._retry_with_backoff(make_request)

            instance = data.get("instance")
            if not instance:
                logger.warning(f"Server {server_id} not found in the API response")
                return None

            return self._parse_vultr_instance(instance)

        except VultrNotFoundError:
            # Server not found - this is normal, return None
            logger.warning(f"Server {server_id} not found")
            return None
        except (VultrAuthenticationError, VultrPermissionError, VultrAPIError) as e:
            # Critical API errors - re-raise
            logger.error(f"Error fetching server {server_id}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching server {server_id}: {e}", exc_info=True)
            raise

    async def _power_action(
        self,
        server_id: str,
        action_path: str,
        *,
        noun: str,
        gen: str,
        done: str,
    ) -> bool:
        """Perform a power operation on an instance (start/halt/reboot).

        Shared implementation for start/stop/reboot_server — they differ only
        by endpoint and the word forms used in the log messages.

        Args:
            server_id: Server ID
            action_path: Endpoint suffix (start/halt/reboot)
            noun: Action noun for the in-progress log (Starting/...)
            gen: Action noun for error logs (starting/...)
            done: Past participle for the success log (started/stopped/...)

        Returns:
            bool: True if the operation succeeded, False otherwise
        """
        logger.info(f"{noun} server {server_id}...")

        try:

            async def make_request() -> httpx.Response:
                """POST the power action endpoint.

                Returns:
                    httpx.Response: Response after raise_for_status() succeeds.
                """
                client = await self._get_client()
                url = f"{self.base_url}/instances/{server_id}/{action_path}"
                response = await client.post(url)
                response.raise_for_status()
                return response

            # Critical operation - 5 retries
            await self._retry_with_backoff(make_request, config=RetryConfig(max_retries=5))

            logger.info(f"Server {server_id} {done}")
            return True

        except (VultrAuthenticationError, VultrPermissionError) as e:
            logger.error(f"Critical error {gen} server {server_id}: {e}", exc_info=True)
            return False
        except VultrNotFoundError:
            logger.error(f"Server {server_id} not found for {gen}")
            return False
        except Exception as e:
            logger.error(f"Error {gen} server {server_id}: {e}", exc_info=True)
            return False

    async def start_server(self, server_id: str) -> bool:
        """Start a stopped server.

        Args:
            server_id: Vultr instance ID.

        Returns:
            bool: True if the operation succeeded, False otherwise.
        """
        return await self._power_action(
            server_id, "start", noun="Starting", gen="starting", done="started"
        )

    async def stop_server(self, server_id: str) -> bool:
        """Stop a running server.

        Args:
            server_id: Vultr instance ID.

        Returns:
            bool: True if the operation succeeded, False otherwise.
        """
        return await self._power_action(
            server_id, "halt", noun="Stopping", gen="stopping", done="stopped"
        )

    async def shutdown_server(self, server_id: str) -> bool:
        """
        Gracefully shut down a server (graceful shutdown).

        IMPORTANT: the Vultr API does not provide a dedicated endpoint for
        graceful shutdown. This method uses /halt (the same as stop_server),
        which is equivalent to poweroff.

        Args:
            server_id: Server ID

        Returns:
            bool: True if the operation succeeded, False otherwise
        """
        logger.info(
            f"Gracefully shutting down server {server_id} "
            f"(Vultr does not support graceful shutdown, using halt)..."
        )
        # Vultr does not distinguish shutdown from poweroff - use halt
        return await self.stop_server(server_id)

    async def reboot_server(self, server_id: str) -> bool:
        """Reboot a server.

        Args:
            server_id: Vultr instance ID.

        Returns:
            bool: True if the operation succeeded, False otherwise.
        """
        return await self._power_action(
            server_id, "reboot", noun="Rebooting", gen="rebooting", done="rebooted"
        )

    async def get_balance(self) -> PrepaidBalanceRecord | None:
        """
        Fetch account balance information.

        CRITICAL: Vultr returns the balance with a negative sign!
        For example, {"balance": -25.50} means you have $25.50.
        This method automatically converts it to a positive value.

        Returns:
            PrepaidBalanceRecord | None: Balance information, or None

        Raises:
            Exception: On API errors
        """
        try:

            async def make_request() -> dict[str, Any]:
                """GET the /account endpoint.

                Returns:
                    dict[str, Any]: Parsed JSON response body.
                """
                client = await self._get_client()
                url = f"{self.base_url}/account"
                response = await client.get(url)
                response.raise_for_status()
                return response.json()

            data = await self._retry_with_backoff(make_request)

            account = data.get("account", {})

            # Vultr reports balance as a negative credit (e.g. -25.50 => $25.50 left),
            # so flip the sign. A depleted/in-debt account makes the API value
            # positive, which would flip to a NEGATIVE real_balance and crash
            # PrepaidBalanceRecord (balance has ge=0) — clamp to 0.0 so the record
            # still constructs and the low-balance alert fires instead of being
            # silently skipped by balance_checker's except.
            api_balance = account.get("balance", 0.0)
            real_balance = max(0.0, -1 * api_balance)

            # Parse the last payment date
            last_payment_date_str = account.get("last_payment_date")
            last_payment_date = None
            if last_payment_date_str:
                try:
                    last_payment_date = datetime.fromisoformat(
                        last_payment_date_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    logger.warning(f"Failed to parse date: {last_payment_date_str}")

            # Read the API value once and convert its sign (Vultr reports payments
            # as negative amounts); leave it None when the field is absent. Clamp to
            # 0.0 like balance: a positive raw value (refund/adjustment) would flip
            # negative and crash the ge=0 field, which balance_checker would swallow.
            last_payment_amount_raw = account.get("last_payment_amount")
            last_payment_amount = (
                max(0.0, -1 * last_payment_amount_raw)
                if last_payment_amount_raw is not None
                else None
            )

            return PrepaidBalanceRecord(
                provider_type="vultr",
                provider_alias=self._alias,
                balance=real_balance,
                pending_charges=account.get("pending_charges", 0.0),
                last_payment_date=last_payment_date,
                last_payment_amount=last_payment_amount,
            )

        except Exception as e:
            logger.error(f"Error fetching balance: {e}", exc_info=True)
            raise

    async def health_check(self) -> bool:
        """
        Check Vultr API availability.

        Performs a lightweight request to /v2/account to verify that:
        - The API is reachable
        - The API token is valid

        Returns:
            bool: True if the API is reachable, False otherwise
        """
        try:
            client = await self._get_client()
            url = f"{self.base_url}/account"

            # Quick check with a short timeout
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            return True

        except httpx.HTTPStatusError as e:
            # health_check calls the API directly (no _retry_with_backoff), so the
            # raw httpx error surfaces here, not the typed VultrAuthenticationError.
            if e.response.status_code == 401:
                logger.error("Invalid Vultr API token!", exc_info=True)
            else:
                logger.warning(f"Vultr API unavailable: HTTP {e.response.status_code}")
            return False
        except httpx.RequestError as e:
            logger.warning(f"Network error while checking the Vultr API: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while checking the API: {e}", exc_info=True)
            return False

