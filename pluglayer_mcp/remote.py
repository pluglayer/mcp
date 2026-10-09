"""Authenticated hosted MCP transport for the public PlugLayer service."""

from __future__ import annotations

import os

import uvicorn
from starlette.responses import JSONResponse

from pluglayer_mcp.credentials import reset_remote_api_key, set_remote_api_key
from pluglayer_mcp.server import mcp
from pluglayer_mcp.settings import settings


class BearerMiddleware:
    """Inject the request bearer into a context variable without leaking it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path", "").rstrip("/") not in {"/mcp", ""}:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            response = JSONResponse(
                {"error": "authorization_required", "message": "Connect through the PlugLayer setup prompt."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        bearer = token.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in bearer):
            response = JSONResponse({"error": "invalid_authorization"}, status_code=401)
            await response(scope, receive, send)
            return
        context = set_remote_api_key(bearer)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_remote_api_key(context)


def serve() -> None:
    """Run the hosted MCP endpoint; API calls remain backend-owned."""
    app = mcp.streamable_http_app()

    async def health(_request):
        return JSONResponse({"status": "ok", "service": "pluglayer-mcp"})

    app.add_route("/healthz", health, methods=["GET"])
    app.add_middleware(BearerMiddleware)
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", str(settings.MCP_PORT or 8787)))
    uvicorn.run(app, host=host, port=port, log_level="info")
