import asyncio

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from pluglayer_mcp import remote


def _app(seen=None):
    async def endpoint(_request):
        if seen is not None:
            from pluglayer_mcp.credentials import resolve_api_key

            seen.append(resolve_api_key())
        return JSONResponse({"ok": True})

    return remote.BearerMiddleware(Starlette(routes=[Route("/mcp", endpoint, methods=["GET"])]))


def test_remote_api_key_is_request_scoped():
    seen = []

    async def run():
        async with AsyncClient(transport=ASGITransport(app=_app(seen)), base_url="http://test") as client:
            response = await client.get("/mcp", headers={"Authorization": "Bearer plk_remote_test"})
            assert response.status_code == 200

    asyncio.run(run())
    assert seen == ["plk_remote_test"]


def test_remote_requires_bearer():
    async def run():
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
            response = await client.get("/mcp")
            assert response.status_code == 401
            assert response.json()["error"] == "authorization_required"

    asyncio.run(run())


def test_remote_health_is_public_for_readiness_checks():
    from pluglayer_mcp import remote

    app = remote.mcp.streamable_http_app()

    async def health(_request):
        return remote.JSONResponse({"status": "ok"})

    app.add_route("/healthz", health, methods=["GET"])
    app.add_middleware(remote.BearerMiddleware)

    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/healthz")
            assert response.status_code == 200

    asyncio.run(run())
