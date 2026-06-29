import httpx

from pluglayer_mcp.client import _extract_error_detail, _format_request_error


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
