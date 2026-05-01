import httpx
from typing import Optional, Any
from pluglayer_mcp.settings import settings


class PlugLayerClient:
    """HTTP client for the PlugLayer API."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.PLUGLAYER_API_KEY
        self.base_url = (base_url or settings.resolved_api_base_url).rstrip("/")

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "pluglayer-mcp/0.1.0",
        }

    async def _request(self, method: str, path: str, *, params: dict = None, data: dict = None, timeout: float = 30.0) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                params=params,
                json=data,
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = resp.text[:500]
                raise RuntimeError(f"{resp.status_code} {resp.reason_phrase}: {detail}") from exc
            if resp.status_code == 204 or not resp.content:
                return {}
            data = resp.json()
            if isinstance(data, dict) and data.get("ok") is True and "data" in data:
                return data["data"]
            return data

    async def get(self, path: str, params: dict = None) -> Any:
        return await self._request("GET", path, params=params, timeout=30.0)

    async def post(self, path: str, data: dict = None, params: dict = None) -> Any:
        return await self._request("POST", path, params=params, data=data or {}, timeout=60.0)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path, timeout=30.0)

    async def patch(self, path: str, data: dict) -> Any:
        return await self._request("PATCH", path, data=data, timeout=30.0)

    async def put(self, path: str, data: dict) -> Any:
        return await self._request("PUT", path, data=data, timeout=30.0)


def get_client(api_key: Optional[str] = None) -> PlugLayerClient:
    return PlugLayerClient(api_key=api_key)