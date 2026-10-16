"""Exercise rotated credentials through a real, persistent SDK HTTP session."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pluglayer_mcp.credentials import resolve_api_key
from pluglayer_mcp.remote import BearerMiddleware, BearerValidator
from pluglayer_mcp.tool_metadata import PublicFastMCP


@pytest.mark.parametrize("json_response", [True, False])
def test_existing_http_session_uses_each_requests_bearer(monkeypatch, json_response):
    validator = AsyncMock(return_value=200)
    monkeypatch.setattr(BearerValidator, "validate", validator)
    server = PublicFastMCP("refresh-test", json_response=json_response)
    seen = []

    @server.tool()
    def current_credential() -> str:
        bearer = resolve_api_key()
        seen.append(bearer)
        return bearer

    app = server.streamable_http_app()
    app.add_middleware(BearerMiddleware)

    async def run():
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8787") as client:
                headers = {
                    "Authorization": "Bearer ploa_initial",
                    "Accept": "application/json, text/event-stream",
                }
                initialized = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "refresh-test", "version": "1"},
                    },
                })
                assert initialized.status_code == 200
                headers["Mcp-Session-Id"] = initialized.headers["Mcp-Session-Id"]
                headers["MCP-Protocol-Version"] = "2025-03-26"
                notification = await client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "method": "notifications/initialized",
                })
                assert notification.status_code == 202
                async def call(request_id, bearer):
                    response = await client.post("/mcp", headers={**headers, "Authorization": f"Bearer {bearer}"}, json={
                        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                        "params": {"name": "current_credential", "arguments": {}},
                    })
                    return response

                def check(response, bearer):
                    assert response.status_code == 200
                    payload = response.json() if json_response else json.loads(next(
                        line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")
                    ))
                    result = payload["result"]
                    assert not result.get("isError")
                    assert result["content"][0]["text"] == bearer

                for request_id, bearer in enumerate(("ploa_initial", "ploa_refreshed", "ploa_rotated_again"), 2):
                    check(await call(request_id, bearer), bearer)
                # Concurrent requests must not overwrite each other's context.
                bearers = ("ploa_parallel_one", "ploa_parallel_two")
                responses = await asyncio.gather(*(call(i, bearer) for i, bearer in enumerate(bearers, 5)))
                for response, bearer in zip(responses, bearers):
                    check(response, bearer)
                assert len(seen) == 5
                validator.return_value = 401
                rejected = await call(7, "ploa_expired")
                assert rejected.status_code == 401
                assert 'error="invalid_token"' in rejected.headers["WWW-Authenticate"]
                assert len(seen) == 5

    asyncio.run(run())
