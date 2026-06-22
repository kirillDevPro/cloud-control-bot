"""AWS Provider for monitoring EC2 and Lightsail instances."""

import asyncio
import logging
from datetime import datetime, timedelta
from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)

from ..exceptions import (
    AWSAPIError,
    AWSAuthenticationError,
    AWSInvalidStateError,
    AWSNotFoundError,
    AWSPermissionError,
    AWSServiceError,
    AWSThrottlingError,
)
from ..models import Server, ServerStatus
from ..models.billing import BillingModel
from ..models.provider import ProviderType
from ..storage.balance import PostpaidBalanceRecord
from .base import BaseProvider
from .mixins import RetryConfig, RetryMixin

logger = logging.getLogger(__name__)

# Constants for the retry logic
MAX_RETRIES = 5
INITIAL_DELAY = 1.0
MAX_DELAY = 20.0  # AWS SDK standard

# Groups of AWS error codes for error classification (see _transform_client_error)
AWS_AUTH_ERROR_CODES = frozenset(
    {"InvalidClientTokenId", "SignatureDoesNotMatch", "UnrecognizedClientException"}
)
AWS_NOT_FOUND_CODES = frozenset({"InvalidInstanceID.NotFound", "NotFoundException"})
AWS_INVALID_STATE_CODES = frozenset({"IncorrectInstanceState", "OperationNotPermitted"})
AWS_THROTTLING_CODES = frozenset(
    {"Throttling", "RequestLimitExceeded", "TooManyRequestsException"}
)

# Maximum number of regions, as a safety limit
MAX_REGIONS = 50

# Limit on the number of concurrent requests to the AWS API
MAX_CONCURRENT_REQUESTS = 10

# Maximum number of pagination pages (guard against an infinite loop)
MAX_PAGINATION_PAGES = 100

# Regions where Lightsail is unavailable (determined automatically by a test).
# These regions are skipped when fetching Lightsail instances.
LIGHTSAIL_UNAVAILABLE_REGIONS = [
    "ap-northeast-3",  # Osaka, Japan
    "sa-east-1",  # São Paulo, Brazil
    "us-west-1",  # N. California
]

# Configuration for boto3 clients
BOTO3_CONFIG = Config(
    connect_timeout=10,  # Connection timeout
    read_timeout=30,  # Read timeout
    retries={"max_attempts": 0},  # Disable built-in retries (we use our own)
)


class AWSProvider(BaseProvider, RetryMixin):
    """
    Provider for working with AWS (EC2 + Lightsail).

    Supports:
    - EC2 instances
    - Lightsail instances
    - Multi-region monitoring
    - Cost Explorer for cost tracking
    - Automatic retry with exponential backoff
    """

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        regions: list[str] | None = None,
        enable_ec2: bool = True,
        enable_lightsail: bool = True,
        alias: str = "",
        display_name: str = "",
        emoji: str = "",
    ):
        """
        Initialize the AWS Provider.

        Args:
            access_key_id: AWS Access Key ID
            secret_access_key: AWS Secret Access Key
            regions: List of regions to monitor (None = all regions)
            enable_ec2: Enable monitoring of EC2 instances
            enable_lightsail: Enable monitoring of Lightsail instances
            alias: Unique identifier of this provider instance
            display_name: Display name for the UI
            emoji: ASCII emoji for the UI

        Raises:
            AWSAuthenticationError: If the credentials are invalid
        """
        super().__init__(alias=alias, display_name=display_name, emoji=emoji)
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.enable_ec2 = enable_ec2
        self.enable_lightsail = enable_lightsail

        # Cache for per-region clients
        self._ec2_clients: dict[str, Any] = {}
        self._lightsail_clients: dict[str, Any] = {}
        self._cost_explorer_client: Any | None = None

        # Lock protecting the caches from race conditions
        self._clients_lock = asyncio.Lock()

        # Regions to monitor
        self._target_regions: list[str] | None = regions
        self._all_regions_cache: list[str] | None = None

        # Semaphore limiting the number of concurrent requests
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        # Retry configuration for RetryMixin (AWS-specific values)
        self._retry_config = RetryConfig(
            max_retries=MAX_RETRIES,
            initial_delay=INITIAL_DELAY,
            max_delay=MAX_DELAY,
        )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _create_session(self) -> boto3.Session:
        """Create a boto3 session with the configured credentials.

        Returns:
            boto3.Session: Session configured with this provider's credentials.
        """
        return boto3.Session(
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
        )

    async def _get_all_regions(self) -> list[str]:
        """
        Fetch the list of all available AWS regions.

        Returns:
            List[str]: List of regions (e.g. ['us-east-1', 'eu-west-1'])

        Raises:
            AWSAPIError: On errors while fetching the list of regions
        """
        if self._all_regions_cache is not None:
            return self._all_regions_cache

        session = self._create_session()
        ec2 = None
        try:
            ec2 = session.client("ec2", region_name="us-east-1", config=BOTO3_CONFIG)
            # Fetch the list of regions with retry logic
            async def fetch_regions():
                """Call describe_regions in a worker thread and return the response."""
                response = await asyncio.to_thread(ec2.describe_regions, AllRegions=False)
                return response

            response = await self._retry_with_backoff(fetch_regions)

            regions = [r["RegionName"] for r in response.get("Regions", [])]

            if not regions:
                logger.warning("No AWS regions found")
                regions = ["us-east-1"]  # Fallback

            # Cap the count as a safety limit
            if len(regions) > MAX_REGIONS:
                logger.warning(
                    f"Found {len(regions)} regions, " f"capping at {MAX_REGIONS}"
                )
                regions = regions[:MAX_REGIONS]

            self._all_regions_cache = regions
            return regions

        except AWSAPIError:
            # An already-typed AWS error (including auth/permission) coming from
            # _retry_with_backoff — re-raise as is so the concrete type is not
            # lost for failure classification (is_transient_error).
            raise
        except Exception as e:
            raise AWSAPIError(f"Unexpected error while fetching regions: {e}") from e
        finally:
            # Guarantee that the temporary EC2 client is closed
            if ec2 is not None:
                try:
                    ec2.close()
                except Exception:
                    pass  # Ignore errors while closing

    async def _get_target_regions(self) -> list[str]:
        """
        Return the list of regions to monitor.

        Returns the explicitly configured regions if any were provided,
        otherwise falls back to all available regions.

        Returns:
            List[str]: List of regions
        """
        if self._target_regions is not None:
            return self._target_regions

        return await self._get_all_regions()

    async def _get_cached_client(self, cache: dict[str, Any], region: str, service: str) -> Any:
        """
        Return a cached boto3 client for a (service, region) pair.

        Creation follows the double-checked locking pattern: a fast check without
        the lock, then a second check while holding `_clients_lock`.

        Args:
            cache: Dictionary caching clients by region
            region: AWS region
            service: boto3 service name (e.g. "ec2" or "lightsail")

        Returns:
            Any: The boto3 client for the given service and region
        """
        # Fast check without the lock
        if region in cache:
            return cache[region]

        # Create the client while holding the lock
        async with self._clients_lock:
            # Double-check (another task may have created it while we waited for the lock)
            if region not in cache:
                session = self._create_session()
                # service is passed as a string variable, so the boto3 overload does not resolve
                cache[region] = session.client(  # type: ignore[call-overload]
                    service, region_name=region, config=BOTO3_CONFIG
                )

        return cache[region]

    async def _get_ec2_client(self, region: str) -> Any:
        """Return the cached EC2 client for a region.

        Args:
            region: AWS region.

        Returns:
            Any: EC2 boto3 client for the region.
        """
        return await self._get_cached_client(self._ec2_clients, region, "ec2")

    async def _get_lightsail_client(self, region: str) -> Any:
        """Return the cached Lightsail client for a region.

        Args:
            region: AWS region.

        Returns:
            Any: Lightsail boto3 client for the region.
        """
        return await self._get_cached_client(self._lightsail_clients, region, "lightsail")

    async def _get_cost_explorer_client(self) -> Any:
        """
        Return the Cost Explorer client (with thread-safe caching).

        Uses the double-checked locking pattern for thread safety.

        Returns:
            Any: The Cost Explorer (ce) boto3 client
        """
        # Fast check without the lock
        if self._cost_explorer_client is not None:
            return self._cost_explorer_client

        # Create the client while holding the lock
        async with self._clients_lock:
            # Double-check (another task may have created it while we waited for the lock)
            if self._cost_explorer_client is None:
                session = self._create_session()
                # Cost Explorer is only available in us-east-1
                self._cost_explorer_client = session.client(
                    "ce", region_name="us-east-1", config=BOTO3_CONFIG
                )

        return self._cost_explorer_client

    async def _retry_with_backoff(
        self,
        func: Callable,
        config: RetryConfig | None = None,
    ) -> Any:
        """Run RetryMixin with the AWS-specific default configuration.

        Error classification is delegated to the ``_should_retry`` and
        ``_transform_error`` hooks — the retry/backoff loop itself lives in
        RetryMixin.

        Args:
            func: The callable to execute with retries.
            config: Optional retry configuration; defaults to the AWS config.

        Returns:
            Any: The result returned by ``func``.
        """
        return await super()._retry_with_backoff(func, config or self._retry_config)

    def _should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:
        """Decide whether to retry the request (full jitter via RetryMixin).

        Retry-able: throttling, 5xx and network errors. Returns wait=0.0 so that
        RetryMixin applies full jitter + exponential backoff.

        Args:
            error: The exception raised by the attempt.
            attempt: The current attempt number (unused here).

        Returns:
            tuple[bool, float]: (should_retry, wait_seconds); wait is always 0.0
            so RetryMixin computes the backoff delay itself.
        """
        if isinstance(error, ClientError):
            error_code = error.response.get("Error", {}).get("Code", "Unknown")
            status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error_code in AWS_THROTTLING_CODES:
                return True, 0.0
            if status_code and status_code >= 500:
                return True, 0.0
            return False, 0.0
        if isinstance(error, EndpointConnectionError):
            return True, 0.0
        return False, 0.0

    def _transform_error(self, error: Exception) -> Exception:
        """Transform a boto3 error into a specific AWS exception.

        Args:
            error: The original exception raised by boto3.

        Returns:
            Exception: A typed AWS exception describing the error.
        """
        if isinstance(error, NoCredentialsError):
            logger.error("[FAIL] AWS credentials not found", exc_info=True)
            return AWSAuthenticationError()
        if isinstance(error, ClientError):
            return self._transform_client_error(error)
        if isinstance(error, EndpointConnectionError):
            logger.error(f"[FAIL] Network error: {error}", exc_info=True)
            return AWSAPIError(f"Network error: {error}")
        if isinstance(error, AWSAPIError):
            # Already transformed (e.g. in a nested call) — return as is
            return error
        if isinstance(error, BotoCoreError):
            logger.error(f"[FAIL] BotoCore error: {error}", exc_info=True)
            return AWSAPIError(f"BotoCore error: {error}")
        logger.error(f"[FAIL] Unexpected error: {error}", exc_info=True)
        return AWSAPIError(f"Unexpected error: {error}")

    def _transform_client_error(self, error: ClientError) -> Exception:
        """Map a ``ClientError`` error code to a concrete AWS exception.

        Args:
            error: The boto3 ``ClientError`` to classify.

        Returns:
            Exception: A typed AWS exception matching the error code or HTTP
            status (auth, permission, not-found, invalid-state, throttling,
            5xx service error, or a generic AWSAPIError).
        """
        error_code = error.response.get("Error", {}).get("Code", "Unknown")
        status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")

        if error_code in AWS_AUTH_ERROR_CODES:
            logger.error(f"[FAIL] Invalid AWS credentials: {error_code}", exc_info=True)
            return AWSAuthenticationError(str(error))
        if error_code == "UnauthorizedOperation":
            operation = error.operation_name or "unknown"
            logger.error(f"[FAIL] Insufficient permissions for {operation}", exc_info=True)
            return AWSPermissionError(operation, str(error))
        if error_code in ("AccessDenied", "AccessDeniedException"):
            # IAM-denied calls (incl. Cost Explorer ce:GetCostAndUsage) return
            # AccessDeniedException; map to a permission error so it is classified
            # persistent (immediate alert) and get_balance's IAM hint fires.
            operation = error.operation_name or "unknown"
            logger.error(f"[FAIL] Access denied for {operation}", exc_info=True)
            return AWSPermissionError(operation, str(error))
        if error_code in AWS_NOT_FOUND_CODES:
            logger.warning(f"[WARN] Resource not found: {error_code}")
            return AWSNotFoundError("Resource", "unknown", str(error))
        if error_code == "InvalidInstanceID.Malformed":
            return AWSNotFoundError("Instance", "malformed_id", str(error))
        if error_code in AWS_INVALID_STATE_CODES:
            logger.warning(f"[WARN] Invalid instance state: {error_code}")
            return AWSInvalidStateError(
                operation="unknown", current_state="unknown", response_body=str(error)
            )
        if error_code == "RequestExpired":
            logger.error("[FAIL] System time is not synchronized with AWS", exc_info=True)
            return AWSAuthenticationError("System time is not synchronized with AWS servers")
        if error_code in AWS_THROTTLING_CODES:
            logger.error(f"[FAIL] AWS throttling after {MAX_RETRIES} attempts", exc_info=True)
            return AWSThrottlingError(retry_after=int(MAX_DELAY), response_body=str(error))
        if status_code and status_code >= 500:
            logger.error(f"[FAIL] AWS server error (HTTP {status_code})", exc_info=True)
            return AWSServiceError(error_code, str(error))
        logger.error(f"[FAIL] AWS API error: {error_code}", exc_info=True)
        return AWSAPIError(
            f"AWS API error: {error_code}",
            error_code=error_code,
            response_body=str(error),
        )

    def _validate_composite_key(self, server_id: str) -> tuple[str, str] | None:
        """
        Validate and parse a composite key.

        Args:
            server_id: Composite ID in the format "{region}:{instance_id}"

        Returns:
            tuple[str, str]: (region, instance_id), or None on error
        """
        parts = server_id.split(":", 1)

        if len(parts) != 2:
            logger.error(f"[FAIL] Invalid AWS server_id (no ':'): {server_id}")
            return None

        region, instance_id = parts

        if not region:
            logger.error(f"[FAIL] Empty region in composite key: {server_id}")
            return None

        if not instance_id:
            logger.error(f"[FAIL] Empty instance_id in composite key: {server_id}")
            return None

        return region, instance_id

    # =========================================================================
    # INSTANCE PARSING
    # =========================================================================

    def _parse_ec2_instance(self, instance: dict[str, Any], region: str) -> Server:
        """
        Convert an EC2 instance into a Server object.

        Args:
            instance: EC2 instance data from the API
            region: Region of the instance

        Returns:
            Server: The server object
        """
        instance_id = instance["InstanceId"]

        # Read the name from the tags
        name = instance_id
        for tag in instance.get("Tags", []):
            if tag.get("Key") == "Name":
                name = tag.get("Value", instance_id)
                break

        # Determine the pingable address. A private / 0.0.0.0 address is not
        # reachable via ICMP from the bot host, so an instance without a public IP
        # is recorded but left disabled (monitoring it would report it perpetually
        # offline and raise false alerts).
        public_ip = instance.get("PublicIpAddress")
        if public_ip:
            ip = public_ip
            monitorable = True
        else:
            ip = instance.get("PrivateIpAddress") or "0.0.0.0"
            monitorable = False
            logger.warning(
                f"[WARN] EC2 {instance_id} ({region}) has no public IP; "
                f"monitoring disabled (address {ip} is not pingable)"
            )

        # State: pending, running, shutting-down, terminated, stopping, stopped
        power_status = instance.get("State", {}).get("Name", "unknown")

        # Instance type (e.g. t2.micro)
        plan = instance.get("InstanceType", "unknown")

        # Composite key with region: aws:us-east-1:i-1234567890abcdef0
        composite_id = f"{region}:{instance_id}"

        return Server(
            id=composite_id,
            provider=ProviderType.AWS,
            provider_alias=self._alias,
            name=name,
            ip=ip,
            region=region,
            plan=plan,
            status=ServerStatus.UNKNOWN,  # Determined by ping
            power_status=power_status,
            os=instance.get("PlatformDetails"),
            enabled=monitorable,
            added_at=datetime.now(),
        )

    def _parse_lightsail_instance(self, instance: dict[str, Any], region: str) -> Server:
        """
        Convert a Lightsail instance into a Server object.

        Args:
            instance: Lightsail instance data from the API
            region: Region of the instance

        Returns:
            Server: The server object
        """
        instance_id = instance["name"]  # Lightsail uses the name as the ID
        name = instance.get("name", instance_id)

        # Get the public IP. Lightsail without a public IP is not pingable from
        # the bot host, so record it but leave it disabled (see _parse_ec2_instance).
        public_ip = instance.get("publicIpAddress")
        if public_ip:
            ip = public_ip
            monitorable = True
        else:
            ip = "0.0.0.0"
            monitorable = False
            logger.warning(
                f"[WARN] Lightsail {instance_id} ({region}) has no public IP; "
                "monitoring disabled (0.0.0.0 is not pingable)"
            )

        # State: pending, running, stopping, stopped, terminated
        power_status = instance.get("state", {}).get("name", "unknown")

        # Bundle (plan)
        plan = instance.get("bundleId", "unknown")

        # RAM and disk
        ram_mb = instance.get("hardware", {}).get("ramSizeInGb", 0) * 1024
        disks = instance.get("hardware", {}).get("disks", [])
        disk_gb = disks[0].get("sizeInGb", 0) if disks else 0
        vcpu = instance.get("hardware", {}).get("cpuCount", 0)

        # Composite key: aws:us-east-1:my-lightsail-instance
        composite_id = f"{region}:{instance_id}"

        return Server(
            id=composite_id,
            provider=ProviderType.AWS,
            provider_alias=self._alias,
            name=name,
            ip=ip,
            region=region,
            plan=plan,
            status=ServerStatus.UNKNOWN,
            power_status=power_status,
            os=instance.get("blueprintName"),
            ram_mb=int(ram_mb),
            disk_gb=int(disk_gb),
            vcpu_count=vcpu,
            enabled=monitorable,
            added_at=datetime.now(),
        )

    # =========================================================================
    # FETCHING SERVERS
    # =========================================================================

    async def get_servers(self) -> list[Server]:
        """
        Fetch all EC2 and Lightsail instances across all regions.

        Returns:
            List[Server]: List of all servers

        Raises:
            AWSAuthenticationError: If persistent credential errors occur.
            AWSPermissionError: If persistent permission errors occur.
            AWSAPIError: On other fatal AWS API errors. Transient per-region
                failures are logged and skipped.
        """
        all_servers: list[Server] = []

        try:
            regions = await self._get_target_regions()

            # Build tasks to fetch servers from all regions in parallel
            tasks = []

            for region in regions:
                if self.enable_ec2:
                    tasks.append(self._get_ec2_instances_in_region(region))

                if self.enable_lightsail:
                    tasks.append(self._get_lightsail_instances_in_region(region))

            # Run all requests in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process the results, tracking how many region/service fetches SUCCEEDED.
            succeeded = 0
            transient_error: Exception | None = None
            for result in results:
                if isinstance(result, Exception):
                    # Persistent auth/permission → propagate immediately so servers_sync
                    # raises the immediate alert and does NOT treat a partial/empty list
                    # as success (which would delete this account's servers).
                    if isinstance(result, (AWSAuthenticationError, AWSPermissionError)):
                        raise result
                    # Transient region/service failure: remember it; keep per-region
                    # resilience only if at least one other fetch actually succeeds.
                    logger.error(f"[FAIL] Error fetching servers: {result}")
                    transient_error = transient_error or result
                    continue

                # Type guard: verify that result is a list of servers
                if isinstance(result, list):
                    succeeded += 1
                    all_servers.extend(result)

            # If EVERY enabled region/service fetch failed transiently (e.g. a network
            # outage across all regions), raise instead of returning an empty "success":
            # is_transient_error then classifies it transient (debounced alert) and
            # servers_sync skips removals for this alias rather than wiping its servers.
            if transient_error is not None and succeeded == 0:
                raise transient_error

            return all_servers

        except AWSAPIError:
            # An already-typed AWS error (including auth/permission) — re-raise so
            # is_transient_error can distinguish permanent errors from transient ones.
            raise
        except Exception as e:
            logger.error(f"[FAIL] Critical error fetching AWS servers: {e}")
            raise AWSAPIError(f"Failed to get AWS servers: {e}") from e

    async def _get_instances_in_region(
        self,
        region: str,
        client_getter: Callable[[str], Any],
        sync_paginate: Callable[[Any], list[dict[str, Any]]],
        is_terminated: Callable[[dict[str, Any]], bool],
        parse_instance: Callable[[dict[str, Any], str], Server],
        service_label: str,
    ) -> list[Server]:
        """
        Shared skeleton for fetching instances from a region.

        semaphore → get client → fetch with retry → filter terminated → parse.
        Service-specific behavior (pagination, state key, parser) is supplied via
        callbacks.

        Args:
            region: AWS region
            client_getter: Async function returning a client for the region
            sync_paginate: Synchronous pagination function (run in to_thread)
            is_terminated: Predicate "instance is in the terminated state"
            parse_instance: Parser converting a raw instance into a Server
            service_label: Service label for logs (e.g. "EC2")

        Returns:
            list[Server]: Parsed, non-terminated instances; empty list if the
            region is unavailable or an error occurs.

        Raises:
            AWSAuthenticationError: If credentials are invalid.
            AWSPermissionError: If IAM permissions are insufficient.
        """
        # Use the semaphore to limit the number of concurrent requests
        async with self._semaphore:
            try:
                client = await client_getter(region)

                instances = await self._retry_with_backoff(
                    lambda: asyncio.to_thread(sync_paginate, client)
                )

                # Filter out terminated instances
                instances = [inst for inst in instances if not is_terminated(inst)]

                return [parse_instance(inst, region) for inst in instances]

            except (AWSAuthenticationError, AWSPermissionError):
                # Persistent auth/permission errors MUST propagate instead of
                # collapsing into an empty list: otherwise get_servers returns []
                # as "success" and servers_sync removes every server of this account
                # (and wipes its stats). Mirrors _get_all_regions / get_server.
                raise
            except Exception as e:
                # Transient failures (5xx/throttling/network/...) must propagate too,
                # so get_servers can tell a FAILED region from a legitimately-empty one
                # and never report a total outage as an empty "success" (which would
                # delete every server of this account). It re-raises only if EVERY
                # enabled fetch failed; otherwise it keeps per-region resilience.
                logger.error(
                    f"[FAIL] Error fetching {service_label} in {region}: {e}", exc_info=True
                )
                if isinstance(e, AWSAPIError):
                    raise
                raise AWSAPIError(f"Failed to fetch {service_label} in {region}: {e}") from e

    async def _get_ec2_instances_in_region(self, region: str) -> list[Server]:
        """Fetch the EC2 instances in a specific region.

        Args:
            region: AWS region.

        Returns:
            list[Server]: Parsed EC2 instances from the region.
        """

        def sync_paginate(ec2: Any) -> list[dict[str, Any]]:
            """Paginate describe_instances and return the flattened instance list.

            Args:
                ec2: EC2 boto3 client.

            Returns:
                list[dict[str, Any]]: Raw EC2 instance dictionaries.
            """
            # Use a paginator to handle a large number of instances.
            # ALL iteration must happen inside asyncio.to_thread.
            paginator = ec2.get_paginator("describe_instances")
            all_instances: list[dict[str, Any]] = []
            # Iterate over pages (MaxResults is the page size)
            for page in paginator.paginate(MaxResults=100):
                for reservation in page.get("Reservations", []):
                    all_instances.extend(reservation.get("Instances", []))
            return all_instances

        return await self._get_instances_in_region(
            region,
            self._get_ec2_client,
            sync_paginate,
            lambda inst: inst.get("State", {}).get("Name") == "terminated",
            self._parse_ec2_instance,
            "EC2",
        )

    async def _get_lightsail_instances_in_region(self, region: str) -> list[Server]:
        """Fetch the Lightsail instances in a specific region.

        Args:
            region: AWS region.

        Returns:
            list[Server]: Parsed Lightsail instances from the region, or an
            empty list when Lightsail is unavailable there.
        """
        # Skip regions where Lightsail is unavailable
        if region in LIGHTSAIL_UNAVAILABLE_REGIONS:
            return []

        def sync_paginate(lightsail: Any) -> list[dict[str, Any]]:
            """Page through get_instances via pageToken and return all instances.

            Args:
                lightsail: Lightsail boto3 client.

            Returns:
                list[dict[str, Any]]: Raw Lightsail instance dictionaries.
            """
            # Lightsail supports pagination via pageToken
            all_instances: list[dict[str, Any]] = []
            page_token = None
            page_count = 0

            while True:
                page_count += 1
                if page_count > MAX_PAGINATION_PAGES:
                    logger.error(
                        f"[FAIL] Page limit exceeded ({MAX_PAGINATION_PAGES}) "
                        f"for Lightsail in region {region}"
                    )
                    break

                params: dict[str, str] = {}
                if page_token:
                    params["pageToken"] = page_token

                response = lightsail.get_instances(**params)
                all_instances.extend(response.get("instances", []))

                # Check whether there are more pages
                page_token = response.get("nextPageToken")

                # Guard against None, empty string, whitespace (as in Vultr)
                if not page_token or not isinstance(page_token, str) or not page_token.strip():
                    break

            return all_instances

        return await self._get_instances_in_region(
            region,
            self._get_lightsail_client,
            sync_paginate,
            lambda inst: inst.get("state", {}).get("name") == "terminated",
            self._parse_lightsail_instance,
            "Lightsail",
        )

    async def get_server(self, server_id: str) -> Server | None:
        """
        Fetch information about a specific server.

        Args:
            server_id: Composite ID in the format "{region}:{instance_id}"

        Returns:
            Optional[Server]: The server object, or None if it is not found or
            an API error is logged.

        Raises:
            None intentionally; AWS API errors are logged and converted to None.
        """
        try:
            # Parse and validate the composite key
            parsed = self._validate_composite_key(server_id)
            if not parsed:
                return None

            region, instance_id = parsed

            # Try EC2
            if self.enable_ec2:
                try:
                    ec2 = await self._get_ec2_client(region)

                    async def fetch_ec2():
                        """Describe the instance via EC2 and return its data or None."""
                        response = await asyncio.to_thread(
                            ec2.describe_instances, InstanceIds=[instance_id]
                        )

                        reservations = response.get("Reservations", [])
                        if reservations:
                            instances = reservations[0].get("Instances", [])
                            if instances:
                                return instances[0]
                        return None

                    instance = await self._retry_with_backoff(fetch_ec2)

                    if instance:
                        return self._parse_ec2_instance(instance, region)

                except AWSNotFoundError:
                    # Handle:
                    # - InvalidInstanceID.Malformed (Lightsail ID != EC2 ID format)
                    # - InvalidInstanceID.NotFound (EC2 instance does not exist)
                    # Then try Lightsail
                    logger.debug(f"Server {server_id} not found in EC2, trying Lightsail")
                except (AWSAuthenticationError, AWSPermissionError, AWSThrottlingError):
                    # Critical errors - re-raise
                    raise
                except AWSAPIError as e:
                    # Other API errors: log them and fall through to Lightsail
                    logger.warning(f"[WARN] EC2 API error for {server_id}: {e}, trying Lightsail")
                    pass

            # Try Lightsail
            if self.enable_lightsail:
                try:
                    lightsail = await self._get_lightsail_client(region)

                    async def fetch_lightsail():
                        """Get the instance via Lightsail and return its data or None."""
                        response = await asyncio.to_thread(
                            lightsail.get_instance, instanceName=instance_id
                        )
                        return response.get("instance")

                    instance = await self._retry_with_backoff(fetch_lightsail)

                    if instance:
                        return self._parse_lightsail_instance(instance, region)

                except AWSNotFoundError:
                    logger.debug(f"Server {server_id} not found in Lightsail either")

            logger.warning(f"[WARN] AWS server {server_id} not found")
            return None

        except Exception as e:
            logger.error(f"[FAIL] Error fetching AWS server {server_id}: {e}", exc_info=True)
            return None

    # =========================================================================
    # SERVER MANAGEMENT
    # =========================================================================

    async def _try_ec2_then_lightsail(
        self,
        server_id: str,
        ec2_operation: Callable[[str, str], Any],
        lightsail_operation: Callable[[str, str], Any],
        operation_name: str,
    ) -> bool:
        """
        Try to perform an operation on EC2 first, then on Lightsail.

        Args:
            server_id: Composite ID in the format "{region}:{instance_id}"
            ec2_operation: Async function for EC2 (region, instance_id) -> Any
            lightsail_operation: Async function for Lightsail (region, instance_id) -> Any
            operation_name: Name of the operation, used for logging

        Returns:
            bool: True if the operation succeeded
        """
        parsed = self._validate_composite_key(server_id)
        if not parsed:
            return False

        region, instance_id = parsed

        # Try EC2
        if self.enable_ec2:
            try:
                await ec2_operation(region, instance_id)
                logger.info(f"[OK] AWS EC2 server {server_id} {operation_name}")
                return True
            except (AWSNotFoundError, AWSAPIError) as e:
                # It may be a Lightsail ID
                logger.debug(f"EC2 {operation_name} failed for {server_id}: {e}, trying Lightsail")

        # Try Lightsail
        if self.enable_lightsail:
            try:
                await lightsail_operation(region, instance_id)
                logger.info(f"[OK] AWS Lightsail server {server_id} {operation_name}")
                return True
            except (AWSNotFoundError, AWSAPIError) as e:
                logger.debug(f"Lightsail {operation_name} also failed for {server_id}: {e}")

        logger.error(f"[FAIL] AWS server {server_id} not found")
        return False

    async def start_server(self, server_id: str) -> bool:
        """
        Start a stopped server.

        Args:
            server_id: Composite ID in the format "{region}:{instance_id}"

        Returns:
            bool: True on success
        """

        async def ec2_op(region: str, instance_id: str) -> None:
            """Start the EC2 instance with retry.

            Args:
                region: AWS region.
                instance_id: EC2 instance ID.
            """
            ec2 = await self._get_ec2_client(region)
            await self._retry_with_backoff(
                lambda: asyncio.to_thread(ec2.start_instances, InstanceIds=[instance_id])
            )

        async def lightsail_op(region: str, instance_id: str) -> None:
            """Start the Lightsail instance with retry.

            Args:
                region: AWS region.
                instance_id: Lightsail instance name.
            """
            ls = await self._get_lightsail_client(region)
            await self._retry_with_backoff(
                lambda: asyncio.to_thread(ls.start_instance, instanceName=instance_id)
            )

        try:
            return await self._try_ec2_then_lightsail(server_id, ec2_op, lightsail_op, "started")
        except AWSInvalidStateError as e:
            logger.warning(f"[WARN] Server {server_id} is already running: {e}")
            return False
        except Exception as e:
            logger.error(f"[FAIL] Error starting AWS server {server_id}: {e}", exc_info=True)
            return False

    async def stop_server(self, server_id: str) -> bool:
        """
        Stop a running server (hard stop).

        Args:
            server_id: Composite ID in the format "{region}:{instance_id}"

        Returns:
            bool: True on success
        """

        async def ec2_op(region: str, instance_id: str) -> None:
            """Force-stop the EC2 instance with retry.

            Args:
                region: AWS region.
                instance_id: EC2 instance ID.
            """
            ec2 = await self._get_ec2_client(region)
            await self._retry_with_backoff(
                lambda: asyncio.to_thread(ec2.stop_instances, InstanceIds=[instance_id], Force=True)
            )

        async def lightsail_op(region: str, instance_id: str) -> None:
            """Force-stop the Lightsail instance with retry.

            Args:
                region: AWS region.
                instance_id: Lightsail instance name.
            """
            ls = await self._get_lightsail_client(region)
            await self._retry_with_backoff(
                lambda: asyncio.to_thread(ls.stop_instance, instanceName=instance_id, force=True)
            )

        try:
            return await self._try_ec2_then_lightsail(server_id, ec2_op, lightsail_op, "stopped")
        except AWSInvalidStateError as e:
            logger.warning(f"[WARN] Server {server_id} is already stopped: {e}")
            return False
        except Exception as e:
            logger.error(f"[FAIL] Error stopping AWS server {server_id}: {e}", exc_info=True)
            return False

    async def shutdown_server(self, server_id: str) -> bool:
        """
        Graceful shutdown of a server (EC2 only, Lightsail is unsupported).

        Args:
            server_id: Composite ID in the format "{region}:{instance_id}"

        Returns:
            bool: True on success
        """
        try:
            parsed = self._validate_composite_key(server_id)
            if not parsed:
                return False

            region, instance_id = parsed

            # Only EC2 supports graceful shutdown
            if self.enable_ec2:
                try:
                    ec2 = await self._get_ec2_client(region)

                    async def shutdown_ec2():
                        """Stop the EC2 instance gracefully (ACPI, Force=False)."""
                        await asyncio.to_thread(
                            ec2.stop_instances, InstanceIds=[instance_id], Force=False
                        )

                    await self._retry_with_backoff(shutdown_ec2)
                    logger.info(f"[OK] AWS EC2 server {server_id} shutdown")
                    return True

                except AWSNotFoundError:
                    logger.warning(
                        f"[WARN] EC2 instance {server_id} not found for graceful shutdown "
                        f"(it may be Lightsail - graceful shutdown is not supported)"
                    )
                    return False
                except AWSAPIError as e:
                    # Transient/permanent AWS API failure — do NOT confuse with 'unsupported'
                    logger.error(
                        f"[FAIL] AWS API error during graceful shutdown {server_id}: {e}",
                        exc_info=True,
                    )
                    return False

            logger.warning(f"[WARN] Graceful shutdown unavailable for {server_id} (EC2 disabled)")
            return False

        except Exception as e:
            logger.error(f"[FAIL] Error during shutdown of AWS server {server_id}: {e}", exc_info=True)
            return False

    async def reboot_server(self, server_id: str) -> bool:
        """
        Reboot a server.

        Args:
            server_id: Composite ID in the format "{region}:{instance_id}"

        Returns:
            bool: True on success
        """

        async def ec2_op(region: str, instance_id: str) -> None:
            """Reboot the EC2 instance with retry.

            Args:
                region: AWS region.
                instance_id: EC2 instance ID.
            """
            ec2 = await self._get_ec2_client(region)
            await self._retry_with_backoff(
                lambda: asyncio.to_thread(ec2.reboot_instances, InstanceIds=[instance_id])
            )

        async def lightsail_op(region: str, instance_id: str) -> None:
            """Reboot the Lightsail instance with retry.

            Args:
                region: AWS region.
                instance_id: Lightsail instance name.
            """
            ls = await self._get_lightsail_client(region)
            await self._retry_with_backoff(
                lambda: asyncio.to_thread(ls.reboot_instance, instanceName=instance_id)
            )

        try:
            return await self._try_ec2_then_lightsail(
                server_id, ec2_op, lightsail_op, "rebooted"
            )
        except Exception as e:
            logger.error(f"[FAIL] Error rebooting AWS server {server_id}: {e}", exc_info=True)
            return False

    def supports_graceful_shutdown(self, server_id: str | None = None) -> bool:
        """
        AWS supports graceful shutdown only for EC2
        (stop_instances with Force=False). Lightsail does not support it.

        Because an account may contain both EC2 and Lightsail at the same time,
        when a server_id is supplied the check is made per-instance: an EC2
        instance_id always starts with "i-", while Lightsail uses the instance name.

        Args:
            server_id: Composite ID "{region}:{instance_id}", or None (capability)

        Returns:
            bool: True if graceful shutdown is supported
        """
        if not self.enable_ec2:
            return False
        if server_id is None:
            # Provider-level capability: yes, EC2 instances are supported
            return True
        parsed = self._validate_composite_key(server_id)
        if not parsed:
            return False
        _region, instance_id = parsed
        # Only EC2 (i-...) supports graceful shutdown, not Lightsail
        return instance_id.startswith("i-")

    # =========================================================================
    # BALANCE AND BILLING
    # =========================================================================

    def get_billing_model(self) -> BillingModel:
        """
        AWS uses a postpaid billing model.

        Payment happens at the end of the month based on actual usage. There is
        no notion of a "balance" — instead, costs are tracked (monthly_costs).

        Returns:
            BillingModel: POSTPAID
        """
        return BillingModel.POSTPAID

    async def get_balance(self) -> PostpaidBalanceRecord | None:
        """
        Fetch cost information via AWS Cost Explorer.

        IMPORTANT:
        - AWS uses a postpaid billing model (paid at the end of the month)
        - Cost Explorer returns Month-To-Date (MTD) costs, not an account balance
        - Cost Explorer has a delay of ~24 hours

        Returns:
            PostpaidBalanceRecord | None: Cost information, or None
        """
        try:
            ce = await self._get_cost_explorer_client()

            # Get the costs for the current month (Month-To-Date)
            today = datetime.now().date()
            start_of_month = today.replace(day=1)
            # End in Cost Explorer is exclusive (it does not include the given date),
            # so we use today + 1 day to include the current day.
            end_date = today + timedelta(days=1)

            async def fetch_cost():
                """Query Cost Explorer for the MTD unblended cost and return the response."""
                response = await asyncio.to_thread(
                    ce.get_cost_and_usage,
                    TimePeriod={
                        "Start": start_of_month.strftime("%Y-%m-%d"),
                        "End": end_date.strftime("%Y-%m-%d"),
                    },
                    Granularity="MONTHLY",
                    Metrics=["UnblendedCost"],
                )
                return response

            response = await self._retry_with_backoff(fetch_cost)

            # Parse the results
            results = response.get("ResultsByTime", [])
            if not results:
                logger.warning("[WARN]Cost Explorer returned no data")
                return None

            # Read the cost amount
            amount = results[0].get("Total", {}).get("UnblendedCost", {}).get("Amount")

            if amount is None:
                logger.warning("[WARN]Cost Explorer returned no amount")
                return None

            cost = float(amount)

            return PostpaidBalanceRecord(
                timestamp=datetime.now(),
                provider_type="aws",
                provider_alias=self._alias,
                monthly_costs=cost,
            )

        except AWSPermissionError:
            logger.warning(
                "[WARN] No permissions for the Cost Explorer API. "
                "Add 'ce:GetCostAndUsage' to the IAM policy."
            )
            return None
        except Exception as e:
            logger.error(f"[FAIL] Error fetching AWS costs: {e}", exc_info=True)
            return None

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    async def close(self) -> None:
        """Explicitly close all boto3 clients to release the connection pool."""
        errors: list[str] = []

        # Close EC2 clients
        for region, client in self._ec2_clients.items():
            try:
                await asyncio.to_thread(client.close)
            except Exception as e:
                errors.append(f"EC2 ({region}): {e}")

        # Close Lightsail clients
        for region, client in self._lightsail_clients.items():
            try:
                await asyncio.to_thread(client.close)
            except Exception as e:
                errors.append(f"Lightsail ({region}): {e}")

        # Close Cost Explorer
        if self._cost_explorer_client:
            try:
                await asyncio.to_thread(self._cost_explorer_client.close)
            except Exception as e:
                errors.append(f"Cost Explorer: {e}")

        # ALWAYS clear the caches, even if closing failed
        self._ec2_clients.clear()
        self._lightsail_clients.clear()
        self._cost_explorer_client = None

        # Log all errors in a single message
        if errors:
            logger.warning(
                f"Errors during AWS close ({len(errors)} total):\n"
                + "\n".join(f"  - {err}" for err in errors)
            )

    def supports_balance(self) -> bool:
        """Return whether AWS balance/cost reporting is supported.

        Returns:
            bool: True because AWS costs are fetched through Cost Explorer.
        """
        return True

    async def health_check(self) -> bool:
        """
        Check whether the AWS API is reachable.

        Returns:
            bool: True if the API is available
        """
        try:
            await self._get_all_regions()
            return True
        except Exception as e:
            logger.error(f"[FAIL] AWS health check failed: {e}", exc_info=True)
            return False

    def get_provider_name(self) -> str:
        """Return the provider name.

        Returns:
            str: Static provider name, "aws".
        """
        return "aws"
