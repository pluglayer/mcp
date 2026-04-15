import httpx
from typing import Optional, Any
from pluglayer_mcp.settings import settings


class PlugLayerClient:
    """HTTP client for the PlugLayer API."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.PLUGLAYER_API_KEY
        self.base_url = (base_url or settings.PLUGLAYER_API_URL).rstrip("/")

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "pluglayer-mcp/0.1.0",
        }

    async def get(self, path: str, params: dict = None) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self.base_url}{path}", headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, data: dict = None) -> Any:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}{path}", headers=self.headers, json=data or {})
            resp.raise_for_status()
            return resp.json()

    async def delete(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(f"{self.base_url}{path}", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def patch(self, path: str, data: dict) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(f"{self.base_url}{path}", headers=self.headers, json=data)
            resp.raise_for_status()
            return resp.json()


def get_client(api_key: Optional[str] = None) -> PlugLayerClient:
    return PlugLayerClient(api_key=api_key)
