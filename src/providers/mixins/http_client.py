"""HTTP client mixin.

Provides a singleton httpx.AsyncClient for providers.
"""

from typing import Any

import httpx


class HttpClientMixin:
    """
    Mixin that gives a provider an HTTP client.

    Provides lazy initialization of an httpx.AsyncClient using the singleton
    pattern. Providers must define the base_url and headers properties.

    Usage example:
        class VultrProvider(BaseProvider, HttpClientMixin):
            @property
            def base_url(self) -> str:
                return "https://api.vultr.com/v2"

            @property
            def headers(self) -> dict[str, str]:
                return {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }

            async def get_servers(self):
                client = await self._get_client()
                response = await client.get(f"{self.base_url}/instances")
                return response.json()
    """

    _client: httpx.AsyncClient | None = None
    _default_timeout: float = 30.0

    @property
    def base_url(self) -> str:
        """
        Base URL of the provider's API.

        Providers MUST override this property.

        Returns:
            str: Base URL (e.g. "https://api.vultr.com/v2").
        """
        raise NotImplementedError("Subclasses must define base_url property")

    @property
    def headers(self) -> dict[str, str]:
        """
        HTTP headers for requests.

        Providers MUST override this property to add authorization.

        Returns:
            dict[str, str]: Request headers.
        """
        raise NotImplementedError("Subclasses must define headers property")

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Return the HTTP client (singleton).

        Creates the client on the first call, then reuses it.

        Returns:
            httpx.AsyncClient: The HTTP client.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self._default_timeout,
            )
        return self._client

    async def _get_json(self, url: str) -> dict[str, Any]:
        """Perform a GET request and decode its JSON response."""
        client = await self._get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async def _post_json(self, url: str) -> dict[str, Any]:
        """Perform a POST request and decode its JSON response."""
        client = await self._get_client()
        response = await client.post(url)
        response.raise_for_status()
        return response.json()

    async def _post_without_json(self, url: str) -> httpx.Response:
        """Perform a POST request without decoding the response body."""
        client = await self._get_client()
        response = await client.post(url)
        response.raise_for_status()
        return response

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> int | None:
        """Extract the Retry-After header as a number of seconds (None if absent)."""
        retry_after = response.headers.get("Retry-After")
        return int(retry_after) if retry_after else None

    @staticmethod
    def _split_resource_path(path: str) -> tuple[str, str]:
        """
        Split a URL path into (resource_type, resource_id) from its last segments.

        Empty segments (e.g. a leading "/") are ignored.
        For example "/servers/123" -> ("servers", "123"), "/account" -> ("resource", "account").
        """
        parts = [segment for segment in path.split("/") if segment]
        resource_id = parts[-1] if parts else "unknown"
        resource_type = parts[-2] if len(parts) > 1 else "resource"
        return resource_type, resource_id
