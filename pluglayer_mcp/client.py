import json
from typing import Optional, Any

import httpx
from pluglayer_mcp.settings import settings


def _extract_error_detail(resp: httpx.Response) -> str:
    text = (resp.text or "").strip()
    try:
        payload = resp.json()
    except Exception:
        return text[:500]

    if isinstance(payload, dict):
        if isinstance(payload.get("detail"), str):
            return payload["detail"][:500]
        if isinstance(payload.get("message"), str):
            return payload["message"][:500]
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("detail", "message", "error_message", "error"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value[:500]
    return text[:500] or json.dumps(payload)[:500] or "No error body returned by PlugLayer API"


def _format_request_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    if isinstance(exc, httpx.TimeoutException):
        return "Request to PlugLayer timed out before a response was received"
    if isinstance(exc, httpx.RequestError):
        return "Network error while contacting PlugLayer API"
    return exc.__class__.__name__


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
            try:
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self.headers,
                    params=params,
                    json=data,
                )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                raise RuntimeError(_format_request_error(exc)) from exc
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _extract_error_detail(resp)
                raise RuntimeError(f"{resp.status_code} {resp.reason_phrase}: {detail}") from exc
            if resp.status_code == 204 or not resp.content:
                return {}
            data = resp.json()
            if isinstance(data, dict) and data.get("ok") is True and "data" in data:
                return data["data"]
            return data

    async def get(self, path: str, params: dict = None) -> Any:
        return await self._request("GET", path, params=params, timeout=30.0)

    async def post(self, path: str, data: dict = None, params: dict = None, timeout: float = 60.0) -> Any:
        return await self._request("POST", path, params=params, data=data or {}, timeout=timeout)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path, timeout=30.0)

    async def patch(self, path: str, data: dict) -> Any:
        return await self._request("PATCH", path, data=data, timeout=30.0)

    async def put(self, path: str, data: dict) -> Any:
        return await self._request("PUT", path, data=data, timeout=30.0)

    async def post_multipart(
        self,
        path: str,
        *,
        form_data: dict[str, Any],
        file_field: str,
        file_path: str,
        content_type: str = "application/octet-stream",
        timeout: float = 600.0,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "pluglayer-mcp/0.1.0",
        }
        with open(file_path, "rb") as fh:
            files = {
                file_field: (file_path.split("/")[-1], fh, content_type),
            }
            async with httpx.AsyncClient(timeout=timeout) as client:
                try:
                    resp = await client.post(
                        f"{self.base_url}{path}",
                        headers=headers,
                        data=form_data,
                        files=files,
                    )
                except (httpx.TimeoutException, httpx.RequestError) as exc:
                    raise RuntimeError(_format_request_error(exc)) from exc
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    detail = _extract_error_detail(resp)
                    raise RuntimeError(f"{resp.status_code} {resp.reason_phrase}: {detail}") from exc
                if resp.status_code == 204 or not resp.content:
                    return {}
                data = resp.json()
                if isinstance(data, dict) and data.get("ok") is True and "data" in data:
                    return data["data"]
                return data


def get_client(api_key: Optional[str] = None) -> PlugLayerClient:
    return PlugLayerClient(api_key=api_key)
