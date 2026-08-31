import asyncio

import httpx
import pytest

from pluglayer_mcp.client import PlugLayerClient, _extract_error_detail, _format_request_error


@pytest.mark.parametrize("method", ["get", "post"])
def test_optional_query_values_are_omitted_without_dropping_false_or_zero(monkeypatch, method):
    captured = []

    async def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "data": {}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "pluglayer_mcp.client.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    params = {"featured": None, "min_cpu_cores": None, "min_ram_gb": 0,
              "min_storage_gb": 2.5, "enabled": False, "search": "redis"}
    client = PlugLayerClient(api_key="test-key", base_url="https://api.example.test")
    asyncio.run(getattr(client, method)("/v1/plugin/catalog", params=params))
    assert dict(captured[0].url.params) == {
        "min_ram_gb": "0", "min_storage_gb": "2.5", "enabled": "false", "search": "redis",
    }
    assert params["featured"] is None


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


def test_multipart_uses_long_streaming_timeouts(monkeypatch, tmp_path):
    captured = {}
    archive = tmp_path / "image.tar"
    archive.write_bytes(b"archive")

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, data, files):
            captured.update({"url": url, "data": data, "files": files})
            return httpx.Response(
                200,
                json={"ok": True, "data": {"task_id": "task-1"}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("pluglayer_mcp.client.httpx.AsyncClient", FakeAsyncClient)
    client = PlugLayerClient(api_key="test-key", base_url="https://api.example.test")

    result = asyncio.run(
        client.post_multipart(
            "/v1/plugin/apps/app-1/upload-image-redeploy",
            form_data={"wait_seconds": "0"},
            file_field="archive",
            file_path=str(archive),
        )
    )

    assert result == {"task_id": "task-1"}
    assert captured["timeout"].connect == 30.0
    assert captured["timeout"].pool == 30.0
    assert captured["timeout"].read == 1800.0
    assert captured["timeout"].write == 1800.0
