"""Authenticated hosted MCP transport for the public PlugLayer service."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import uvicorn
from starlette.responses import JSONResponse

from pluglayer_mcp.credentials import reset_remote_api_key, set_remote_api_key
from pluglayer_mcp.server import mcp
from pluglayer_mcp.settings import settings
from pluglayer_mcp.remote_auth import BearerValidator


def oauth_authorization_server_metadata() -> dict[str, object]:
    """Build compatibility discovery from the configured API OAuth issuer."""
    issuer = (settings.MCP_OAUTH_ISSUER or "").strip().rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize" if issuer else "",
        "token_endpoint": f"{issuer}/token" if issuer else "",
        "registration_endpoint": f"{issuer}/register" if issuer else "",
        "revocation_endpoint": f"{issuer}/revoke" if issuer else "",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "authorization_response_iss_parameter_supported": True,
        "scopes_supported": ["pluglayer.read", "pluglayer.write"],
    }


class BearerMiddleware:
    """Inject the request bearer into a context variable without leaking it."""

    def __init__(self, app):
        self.app = app
        self.validator = BearerValidator()

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
            status = 401
        else:
            status = await self.validator.validate(bearer)
        if status != 200:
            headers = {"Cache-Control": "no-store"}
            if status == 401:
                headers["WWW-Authenticate"] = (
                    f'Bearer error="invalid_token", resource_metadata="{self._resource_metadata_url(scope)}"'
                )
            response = JSONResponse(
                {"error": "authentication_unavailable" if status == 503 else "invalid_authorization"},
                status_code=status, headers=headers,
            )
            await response(scope, receive, send)
            return
        # SDK session tasks outlive this HTTP request and inherit its ContextVars.
        # Keep the validated credential on the request too, so tool dispatch can
        # bind the current request's token after OAuth refresh within a session.
        scope.setdefault("state", {})["pluglayer_api_key"] = bearer
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

    async def authorization_server_metadata(_request):
        """Expose a compatibility discovery copy at the resource host.

        The configured API issuer remains authoritative.  Some native clients
        cache or fall back to authorization-server discovery at the MCP origin;
        returning the exact API endpoints prevents them from constructing
        ``https://mcp.pluglayer.com/authorize``.
        """
        return JSONResponse(oauth_authorization_server_metadata(), headers={"Cache-Control": "public, max-age=300"})

    app.add_route("/healthz", health, methods=["GET"])
    app.add_route("/.well-known/oauth-protected-resource", resource_metadata, methods=["GET"])
    app.add_route("/.well-known/oauth-authorization-server", authorization_server_metadata, methods=["GET"])
    app.add_middleware(BearerMiddleware)
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", str(settings.MCP_PORT or 8787)))
    uvicorn.run(app, host=host, port=port, log_level="info")
