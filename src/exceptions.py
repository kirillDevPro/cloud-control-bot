"""Custom exceptions for the server monitoring system."""


class MonitoringError(Exception):
    """Base exception for the entire monitoring system."""

    def __init__(self, message: str, details: dict | None = None):
        """
        Initialize the exception.

        Args:
            message: Error message text
            details: Additional error details (optional)
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return the string representation of the error.

        Returns:
            str: Error message, including details when present.
        """
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


# ========== VULTR API ERRORS ==========


class VultrAPIError(MonitoringError):
    """Base exception for Vultr API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        """
        Initialize a Vultr API error.

        Args:
            message: Error message text
            status_code: HTTP status code
            response_body: Response body from the API
        """
        details: dict = {}
        if status_code:
            details["status_code"] = status_code
        if response_body:
            details["response_body"] = response_body

        super().__init__(message, details)
        self.status_code: int | None = status_code
        self.response_body: str | None = response_body


class VultrAuthenticationError(VultrAPIError):
    """
    Authentication error (HTTP 401).

    Raised when the API token is invalid or missing.
    Requires checking VULTR_{ALIAS}_API_KEY in the environment variables.
    """

    def __init__(self, response_body: str | None = None):
        """
        Initialize the error with a fixed 401 message and status code.

        Args:
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message="Invalid Vultr API token. Check VULTR_{ALIAS}_API_KEY in the .env file.",
            status_code=401,
            response_body=response_body,
        )


class VultrPermissionError(VultrAPIError):
    """
    Permission error (HTTP 403).

    Raised when the API token lacks the rights required to perform the operation.
    """

    def __init__(self, operation: str, response_body: str | None = None):
        """
        Initialize the error for a forbidden operation.

        Args:
            operation: Name of the operation that was denied
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Insufficient permissions for operation: {operation}",
            status_code=403,
            response_body=response_body,
        )
        self.operation = operation


class VultrNotFoundError(VultrAPIError):
    """
    "Not found" error (HTTP 404).

    Raised when the requested resource (server, balance) does not exist.
    """

    def __init__(self, resource_type: str, resource_id: str, response_body: str | None = None):
        """
        Initialize the error for a missing resource.

        Args:
            resource_type: Type of the resource that was not found
            resource_id: Identifier of the missing resource
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"{resource_type} with ID '{resource_id}' not found",
            status_code=404,
            response_body=response_body,
        )
        self.resource_type = resource_type
        self.resource_id = resource_id


class VultrRateLimitError(VultrAPIError):
    """
    Rate limit exceeded error (HTTP 429).

    Raised when the Vultr API rate limit is exceeded.
    Requires an exponential backoff retry.
    """

    def __init__(self, retry_after: int | None = None, response_body: str | None = None):
        """
        Initialize the rate-limit error.

        Args:
            retry_after: Suggested wait time in seconds before retrying (optional)
            response_body: Response body from the API (optional)
        """
        message = "Vultr API rate limit exceeded"
        if retry_after:
            message += f". Retry after {retry_after} seconds"

        super().__init__(message=message, status_code=429, response_body=response_body)
        self.retry_after = retry_after


class VultrServerError(VultrAPIError):
    """
    Vultr server-side error (HTTP 500-503).

    Raised when there is a problem on Vultr's side.
    Requires a delayed retry.
    """

    def __init__(self, status_code: int, response_body: str | None = None):
        """
        Initialize the server-side error.

        Args:
            status_code: HTTP status code returned by the server
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Vultr API server-side error (HTTP {status_code})",
            status_code=status_code,
            response_body=response_body,
        )


# ========== HETZNER API ERRORS ==========


class HetznerAPIError(MonitoringError):
    """Base exception for Hetzner Cloud API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        """
        Initialize a Hetzner API error.

        Args:
            message: Error message text
            status_code: HTTP status code
            response_body: Response body from the API
        """
        details: dict = {}
        if status_code:
            details["status_code"] = status_code
        if response_body:
            details["response_body"] = response_body

        super().__init__(message, details)
        self.status_code: int | None = status_code
        self.response_body: str | None = response_body


class HetznerAuthenticationError(HetznerAPIError):
    """
    Authentication error (HTTP 401).

    Raised when the API token is invalid or missing.
    Requires checking HETZNER_{ALIAS}_API_KEY in the environment variables.
    """

    def __init__(self, response_body: str | None = None):
        """
        Initialize the error with a fixed 401 message and status code.

        Args:
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message="Invalid Hetzner API token. Check HETZNER_{ALIAS}_API_KEY in the .env file.",
            status_code=401,
            response_body=response_body,
        )


class HetznerPermissionError(HetznerAPIError):
    """
    Permission error (HTTP 403).

    Raised when the API token lacks the rights required to perform the operation.
    """

    def __init__(self, operation: str, response_body: str | None = None):
        """
        Initialize the error for a forbidden operation.

        Args:
            operation: Name of the operation that was denied
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Insufficient permissions for operation: {operation}",
            status_code=403,
            response_body=response_body,
        )
        self.operation = operation


class HetznerNotFoundError(HetznerAPIError):
    """
    "Not found" error (HTTP 404).

    Raised when the requested resource (server) does not exist.
    """

    def __init__(self, resource_type: str, resource_id: str, response_body: str | None = None):
        """
        Initialize the error for a missing resource.

        Args:
            resource_type: Type of the resource that was not found
            resource_id: Identifier of the missing resource
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"{resource_type} with ID '{resource_id}' not found",
            status_code=404,
            response_body=response_body,
        )
        self.resource_type = resource_type
        self.resource_id = resource_id


class HetznerRateLimitError(HetznerAPIError):
    """
    Rate limit exceeded error (HTTP 429).

    Raised when the Hetzner API rate limit (3600 req/hour) is exceeded.
    Requires an exponential backoff retry.
    """

    def __init__(self, retry_after: int | None = None, response_body: str | None = None):
        """
        Initialize the rate-limit error.

        Args:
            retry_after: Suggested wait time in seconds before retrying (optional)
            response_body: Response body from the API (optional)
        """
        message = "Hetzner API rate limit exceeded (3600 req/hour)"
        if retry_after:
            message += f". Retry after {retry_after} seconds"

        super().__init__(message=message, status_code=429, response_body=response_body)
        self.retry_after = retry_after


class HetznerServerError(HetznerAPIError):
    """
    Hetzner server-side error (HTTP 500-503).

    Raised when there is a problem on Hetzner Cloud's side.
    Requires a delayed retry.
    """

    def __init__(self, status_code: int, response_body: str | None = None):
        """
        Initialize the server-side error.

        Args:
            status_code: HTTP status code returned by the server
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Hetzner API server-side error (HTTP {status_code})",
            status_code=status_code,
            response_body=response_body,
        )


class HetznerConflictError(HetznerAPIError):
    """
    State conflict error (HTTP 409).

    Raised when the server is in a state that does not allow the operation,
    for example attempting to power off an already powered-off server.
    """

    def __init__(self, operation: str, server_status: str, response_body: str | None = None):
        """
        Initialize the state-conflict error.

        Args:
            operation: Name of the operation that could not be performed
            server_status: Current status of the server that caused the conflict
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Cannot perform operation '{operation}': server is in state '{server_status}'",
            status_code=409,
            response_body=response_body,
        )
        self.operation = operation
        self.server_status = server_status


class HetznerLockedError(HetznerAPIError):
    """
    Locked resource error (HTTP 423 or locked=true).

    Raised when the server is locked for modification (another operation is in progress).
    """

    def __init__(self, resource_id: str, response_body: str | None = None):
        """
        Initialize the locked-resource error.

        Args:
            resource_id: Identifier of the locked server
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Server {resource_id} is locked (another operation is in progress)",
            status_code=423,
            response_body=response_body,
        )
        self.resource_id = resource_id


# ========== AWS API ERRORS ==========


class AWSAPIError(MonitoringError):
    """Base exception for AWS API errors (EC2, Lightsail, Cost Explorer)."""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        response_body: str | None = None,
    ):
        """
        Initialize an AWS API error.

        Args:
            message: Error message text
            error_code: AWS error code (e.g. 'InvalidInstanceID.NotFound')
            response_body: Response body from the API
        """
        details: dict = {}
        if error_code:
            details["error_code"] = error_code
        if response_body:
            details["response_body"] = response_body

        super().__init__(message, details)
        self.error_code: str | None = error_code
        self.response_body: str | None = response_body


class AWSAuthenticationError(AWSAPIError):
    """
    AWS authentication error.

    Raised when AWS credentials are invalid (Access Key ID or Secret Access Key).
    Requires checking AWS_{ALIAS}_ACCESS_KEY_ID and AWS_{ALIAS}_SECRET_ACCESS_KEY
    in the environment variables.
    """

    def __init__(self, response_body: str | None = None):
        """
        Initialize the error with a fixed credentials message and error code.

        Args:
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message="Invalid AWS credentials. Check AWS_{ALIAS}_ACCESS_KEY_ID and AWS_{ALIAS}_SECRET_ACCESS_KEY in the .env file.",
            error_code="InvalidClientTokenId",
            response_body=response_body,
        )


class AWSPermissionError(AWSAPIError):
    """
    AWS permission error (UnauthorizedOperation).

    Raised when the IAM user lacks the rights required to perform the operation.
    IAM policy configuration is required.
    """

    def __init__(self, operation: str, response_body: str | None = None):
        """
        Initialize the error for a forbidden AWS operation.

        Args:
            operation: Name of the AWS operation that was denied
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Insufficient permissions for AWS operation: {operation}. Check the IAM policies.",
            error_code="UnauthorizedOperation",
            response_body=response_body,
        )
        self.operation = operation


class AWSNotFoundError(AWSAPIError):
    """
    AWS "not found" error.

    Raised when the requested resource (EC2 instance, Lightsail instance) does not exist.
    """

    def __init__(self, resource_type: str, resource_id: str, response_body: str | None = None):
        """
        Initialize the error for a missing AWS resource.

        Args:
            resource_type: Type of the resource that was not found
            resource_id: Identifier of the missing resource
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"{resource_type} with ID '{resource_id}' not found in AWS",
            error_code="InvalidInstanceID.NotFound",
            response_body=response_body,
        )
        self.resource_type = resource_type
        self.resource_id = resource_id


class AWSThrottlingError(AWSAPIError):
    """
    AWS API throttling error.

    Raised when the AWS API request limit is exceeded.
    AWS uses dynamic throttling rather than a fixed rate limit.
    Requires an exponential backoff retry.
    """

    def __init__(self, retry_after: int | None = None, response_body: str | None = None):
        """
        Initialize the throttling error.

        Args:
            retry_after: Suggested wait time in seconds before retrying (optional)
            response_body: Response body from the API (optional)
        """
        message = "AWS API request limit exceeded (throttling)"
        if retry_after:
            message += f". Retry after {retry_after} seconds"

        super().__init__(message=message, error_code="Throttling", response_body=response_body)
        self.retry_after = retry_after


class AWSServiceError(AWSAPIError):
    """
    AWS server-side error (InternalError, ServiceUnavailable).

    Raised on transient problems on AWS's side.
    Requires a delayed retry.
    """

    def __init__(self, error_code: str, response_body: str | None = None):
        """
        Initialize the server-side error.

        Args:
            error_code: AWS error code returned by the service
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"AWS API server-side error ({error_code})",
            error_code=error_code,
            response_body=response_body,
        )


class AWSInvalidStateError(AWSAPIError):
    """
    AWS invalid instance state error.

    Raised when the instance is in a state that does not allow the operation,
    for example attempting to start an already running instance.
    """

    def __init__(self, operation: str, current_state: str, response_body: str | None = None):
        """
        Initialize the invalid-state error.

        Args:
            operation: Name of the operation that could not be performed
            current_state: Current state of the instance that caused the conflict
            response_body: Response body from the API (optional)
        """
        super().__init__(
            message=f"Cannot perform operation '{operation}': instance is in state '{current_state}'",
            error_code="IncorrectInstanceState",
            response_body=response_body,
        )
        self.operation = operation
        self.current_state = current_state


# ========== STORAGE ERRORS ==========


class StorageError(MonitoringError):
    """Base exception for data storage errors."""

    pass


class DatabaseError(StorageError):
    """Error while working with the SQLite database."""

    pass


class FileStorageError(StorageError):
    """Error while working with JSON files."""

    pass


# ========== ERROR CLASSIFICATION ==========

# Explicitly PERSISTENT provider errors — they require human intervention
# (invalid token, insufficient permissions). The administrator is notified
# about these immediately.
_PERSISTENT_ERRORS = (
    VultrAuthenticationError,
    VultrPermissionError,
    HetznerAuthenticationError,
    HetznerPermissionError,
    AWSAuthenticationError,
    AWSPermissionError,
)


def is_transient_error(error: Exception) -> bool:
    """
    Determine whether a provider error is TRANSIENT (self-recovering).

    The classification is intentionally asymmetric: ONLY explicitly known
    critical errors (auth/permissions) are treated as PERSISTENT — these must
    raise an alert immediately. Everything else (5xx, rate limit, network/timeout,
    as well as wrapped and unclassified failures — for example the base
    ``AWSAPIError`` "Network error" into which the AWS provider wraps
    ``EndpointConnectionError``/``BotoCoreError``) is treated as TRANSIENT:
    such errors trigger a notification only when they persist (a cycle threshold
    in servers_sync_task).

    This default ("when unsure, treat as transient") guards against the main
    source of noise: one-off provider API failures that resolve on their own
    within minutes. If an unclassified error turns out to be sustained, the cycle
    threshold will still lead to a notification — just delayed rather than instant.

    Args:
        error: Exception raised by a provider method (usually after _transform_error)

    Returns:
        bool: True if the error is transient, False if it requires intervention
    """
    return not isinstance(error, _PERSISTENT_ERRORS)
