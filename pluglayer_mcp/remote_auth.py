"""Backend-owned bearer validation before accepting hosted MCP sessions."""

import hashlib
import time
from collections import OrderedDict

import httpx

from pluglayer_mcp.settings import settings


class BearerValidator:
    """Bounded positive-only cache; never retain plaintext bearer credentials."""

    def __init__(self, ttl: float = 15.0, limit: int = 1024):
        self.ttl = ttl
        self.limit = limit
        self.cache: OrderedDict[str, float] = OrderedDict()

    async def validate(self, bearer: str) -> int:
        key = hashlib.sha256(bearer.encode()).hexdigest()
        if self.cache.get(key, 0) > time.monotonic():
            return 200
        self.cache.pop(key, None)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    settings.resolved_api_base_url.rstrip("/") + "/v1/plugin/me",
                    headers={"Authorization": f"Bearer {bearer}"},
                )
        except httpx.RequestError:
            return 503
        if response.status_code in (401, 403):
            return response.status_code
        if response.status_code != 200:
            return 503
        self.cache[key] = time.monotonic() + self.ttl
        while len(self.cache) > self.limit:
            self.cache.popitem(last=False)
        return 200
