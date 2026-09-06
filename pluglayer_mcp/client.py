import json
from typing import Optional, Any

import httpx

from pluglayer_mcp.credentials import resolve_api_base_url, resolve_api_key

_USER_AGENT = "pluglayer-mcp/0.1.14"


def _stringify_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail[:500]
    if isinstance(detail, dict):
        for key in ("message", "error_message", "reason", "error"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value[:500]
        task_check = detail.get("task_check")
        if isinstance(task_check, dict):
            task = task_check.get("task") or {}
            value = task.get("error_message")
            if isinstance(value, str) and value.strip():
                return value[:500]
    return ""


def _extract_error_detail(resp: httpx.Response) -> str:
    text = (resp.text or "").strip()
    try:
        payload = resp.json()
    except Exception:
        return text[:500]

    if isinstance(payload, dict):
        detail_text = _stringify_detail(payload.get("detail"))
        if detail_text:
            return detail_text
        if isinstance(payload.get("message"), str):
            return payload["message"][:500]
        detail = payload.get("detail")
        if isinstance(detail, dict):
            data = detail.get("task_check") if isinstance(detail.get("task_check"), dict) else detail.get("data")
            if isinstance(data, dict):
                nested = _stringify_detail(data)
                if nested:
                    return nested
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("detail", "message", "error_message", "error"):
                value = data.get(key)
                detail_text = _stringify_detail(value)
                if detail_text:
                    return detail_text
    return text[:500] or json.dumps(payload)[:500] or "No error body returned by PlugLayer API"


def _format_request_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "Request to PlugLayer timed out before a response was received"
    if isinstance(exc, httpx.RemoteProtocolError):
        return "PlugLayer API closed the connection unexpectedly while processing the request"
    if isinstance(exc, (httpx.ReadError, httpx.WriteError)):
        return "PlugLayer API connection failed while streaming the request or response body"
    message = str(exc).strip()
    if message:
        return message
    if isinstance(exc, httpx.RequestError):
        return "Network error while contacting PlugLayer API"
    return exc.__class__.__name__


class PlugLayerClient:
    """HTTP client for the PlugLayer API."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self._explicit_api_key = api_key
        self._explicit_base_url = base_url

    @property
    def api_key(self) -> str:
        return resolve_api_key(self._explicit_api_key)

    @property
    def base_url(self) -> str:
        return resolve_api_base_url(self._explicit_base_url).rstrip("/")

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        }

    async def _request(self, method: str, path: str, *, params: dict = None, data: dict = None, timeout: float = 30.0) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self.headers,
                    # httpx serializes None as an empty value, which breaks
                    # FastAPI's optional bool/number filters. Keep False and 0.
                    params={key: value for key, value in params.items() if value is not None} if params is not None else None,
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

    async def patch(self, path: str, data: dict = None, params: dict = None, timeout: float = 60.0) -> Any:
        return await self._request("PATCH", path, params=params, data=data or {}, timeout=timeout)

    async def post_form(self, path: str, data: dict[str, Any], timeout: float = 60.0) -> Any:
        """POST an application/x-www-form-urlencoded body to a PlugLayer endpoint."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": _USER_AGENT,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}{path}",
                    headers=headers,
                    data=data,
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
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
                return payload["data"]
            return payload

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path, timeout=30.0)

    async def patch(self, path: str, data: dict) -> Any:
        return await self._request("PATCH", path, data=data, timeout=30.0)

    async def put(self, path: str, data: dict) -> Any:
        return await self._request("PUT", path, data=data, timeout=30.0)

    async def put_bytes(
        self,
        path: str,
        content: bytes,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 300.0,
    ) -> Any:
        request_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/octet-stream",
            "User-Agent": _USER_AGENT,
            **(headers or {}),
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.put(
                    f"{self.base_url}{path}",
                    headers=request_headers,
                    content=content,
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
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
                return payload["data"]
            return payload

    async def post_multipart(
        self,
        path: str,
        *,
        form_data: dict[str, Any],
        file_field: str,
        file_path: str,
        content_type: str = "application/octet-stream",
        timeout: float = 1800.0,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": _USER_AGENT,
        }
        with open(file_path, "rb") as fh:
            files = {
                file_field: (file_path.split("/")[-1], fh, content_type),
            }
            upload_timeout = httpx.Timeout(
                connect=30.0,
                read=timeout,
                write=timeout,
                pool=30.0,
            )
            async with httpx.AsyncClient(timeout=upload_timeout) as client:
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
