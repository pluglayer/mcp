import asyncio

import httpx

from pluglayer_mcp import client as client_module
from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.tools import feedback as feedback_tools
from pluglayer_mcp.tools.feedback import _feedback_description, _redact_sensitive, register_feedback_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register


def test_redact_sensitive_feedback_context():
    text = (
        "Authorization: Bearer top-secret\n"
        "PLUGLAYER_API_KEY=abc123 password='hidden' "
        '"access_token": "also-hidden"'
    )

    redacted = _redact_sensitive(text)

    assert "top-secret" not in redacted
    assert "abc123" not in redacted
    assert "hidden" not in redacted
    assert "also-hidden" not in redacted
    assert redacted.count("[REDACTED]") == 4


def test_feedback_description_adds_structured_mcp_context():
    description = _feedback_description(
        "The action stopped unexpectedly.",
        affected_tool="deploy_image",
        expected_behavior="The app becomes ready.",
        actual_behavior="The task failed.",
        error_summary="Bearer secret-token timed out",
    )

    assert "Source: PlugLayer MCP/plugin" in description
    assert "Affected MCP tool: deploy_image" in description
    assert "Expected behavior: The app becomes ready." in description
    assert "Actual behavior: The task failed." in description
    assert "secret-token" not in description


def test_feedback_tools_submit_and_read(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.form = None

        async def post_form(self, path, data):
            assert path == "/v1/plugin/feedback"
            self.form = data
            return {
                "feedback": {
                    "id": "feedback-1",
                    "title": data["title"],
                    "category": data["category"],
                    "status": "open",
                }
            }

        async def get(self, path, params=None):
            if path == "/v1/plugin/feedback":
                assert params == {"limit": 100}
                return {
                    "feedback": [
                        {
                            "id": "feedback-1",
                            "title": "Deployment timed out",
                            "category": "bug",
                            "status": "open",
                        }
                    ]
                }
            assert path == "/v1/plugin/feedback/feedback-1"
            return {
                "feedback": {
                    "id": "feedback-1",
                    "title": "Deployment timed out",
                    "description": "The rollout did not complete.",
                    "category": "bug",
                    "status": "resolving",
                    "page_path": "/apps/app-1",
                    "resolution_note": "Investigating rollout readiness.",
                }
            }

    fake_client = FakeClient()
    monkeypatch.setattr(feedback_tools, "_client", lambda: fake_client)
    mcp = FakeMCP()
    register_feedback_tools(mcp)

    submitted = asyncio.run(
        mcp.tools["submit_feedback"](
            "Deployment timed out",
            "The rollout stopped while waiting for readiness.",
            "bug",
            affected_tool="redeploy_app",
            error_summary="PLUGLAYER_API_KEY=secret-value timeout",
        )
    )
    listed = asyncio.run(mcp.tools["list_my_feedback"](150))
    loaded = asyncio.run(mcp.tools["get_feedback"]("feedback-1"))

    assert "feedback-1" in submitted
    assert "secret-value" not in fake_client.form["description"]
    assert "Deployment timed out" in listed
    assert "Investigating rollout readiness" in loaded


def test_post_form_uses_form_encoding_and_unwraps_envelope(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, data):
            captured.update({"url": url, "headers": headers, "data": data})
            return httpx.Response(
                200,
                json={"ok": True, "data": {"feedback": {"id": "feedback-1"}}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeAsyncClient)
    client = PlugLayerClient(api_key="test-key", base_url="https://api.example.test")

    result = asyncio.run(client.post_form("/v1/plugin/feedback", {"title": "Useful title"}, timeout=12))

    assert result == {"feedback": {"id": "feedback-1"}}
    assert captured["data"] == {"title": "Useful title"}
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "Content-Type" not in captured["headers"]
    assert captured["timeout"] == 12
