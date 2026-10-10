"""Authenticated hosted MCP transport for the public PlugLayer service."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import uvicorn
from starlette.responses import JSONResponse

from pluglayer_mcp.credentials import reset_remote_api_key, set_remote_api_key
from pluglayer_mcp.server import mcp
from pluglayer_mcp.settings import settings


class BearerMiddleware:
    """Inject the request bearer into a context variable without leaking it."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _resource_metadata_url(scope) -> str:
        configured = (settings.MCP_RESOURCE_URL or "").strip()
        if configured:
            parsed = urlsplit(configured)
            if parsed.scheme and parsed.netloc:
                return urlunsplit((parsed.scheme, parsed.netloc, "/.well-known/oauth-protected-resource", "", ""))
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = headers.get(b"host", b"localhost").decode("latin-1")
        scheme = scope.get("scheme", "https")
        return f"{scheme}://{host}/.well-known/oauth-protected-resource"

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
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="'
                        f"{self._resource_metadata_url(scope)}"
                        '"'
                    ),
                    "Cache-Control": "no-store",
                },
            )
            await response(scope, receive, send)
            return
        bearer = token.strip()
        if not bearer.startswith("ploa_") or any(ord(character) < 32 or ord(character) == 127 for character in bearer):
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

    async def resource_metadata(request):
        resource = (settings.MCP_RESOURCE_URL or "").strip().rstrip("/")
        if not resource:
            resource = str(request.base_url).rstrip("/") + "/mcp"
        issuer = (settings.MCP_OAUTH_ISSUER or "").strip().rstrip("/")
        return JSONResponse({
            "resource": resource,
            "authorization_servers": [issuer] if issuer else [],
            "scopes_supported": ["pluglayer.read", "pluglayer.write"],
            "bearer_methods_supported": ["header"],
        }, headers={"Cache-Control": "public, max-age=300"})

    app.add_route("/healthz", health, methods=["GET"])
    app.add_route("/.well-known/oauth-protected-resource", resource_metadata, methods=["GET"])
    app.add_middleware(BearerMiddleware)
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", str(settings.MCP_PORT or 8787)))
    uvicorn.run(app, host=host, port=port, log_level="info")
