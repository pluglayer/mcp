import asyncio

import httpx

from pluglayer_mcp.client import PlugLayerClient, _extract_error_detail, _format_request_error


def test_extract_error_detail_reads_nested_dict_detail_message():
    response = httpx.Response(
        409,
        json={
            "detail": {
                "message": "Deployment for app 'hc-product-owner-agent' did not become ready within 120s.",
                "task_check": {
                    "task": {
                        "status": "failed",
                        "error_message": "ImagePullBackOff",
                    }
                },
            }
        },
        request=httpx.Request("POST", "https://pluglayer.test/v1/plugin/apps/app/upload-image-redeploy"),
    )

    assert _extract_error_detail(response) == "Deployment for app 'hc-product-owner-agent' did not become ready within 120s."


def test_format_request_error_handles_remote_protocol_error():
    exc = httpx.RemoteProtocolError("Server disconnected without sending a response")

    assert _format_request_error(exc) == "PlugLayer API closed the connection unexpectedly while processing the request"


def test_patch_sends_json_and_unwraps_envelope(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, *, headers, params, json):
            captured.update(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "json": json,
                }
            )
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "project": {
                            "id": "project-1",
                            "name": "Renamed",
                        }
                    },
                },
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr("pluglayer_mcp.client.httpx.AsyncClient", FakeAsyncClient)
    client = PlugLayerClient(api_key="test-key", base_url="https://api.example.test")

    result = asyncio.run(
        client.patch(
            "/v1/plugin/projects/project-1",
            {"name": "Renamed"},
        )
    )

    assert result["project"]["name"] == "Renamed"
    assert captured["method"] == "PATCH"
    assert captured["json"] == {"name": "Renamed"}
