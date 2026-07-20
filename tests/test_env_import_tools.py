import asyncio

from pluglayer_mcp.tools.deployment import env_import
from pluglayer_mcp.tools.deployment.env_import import register_env_import_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register


def test_apply_app_env_vars_sends_content_without_echoing_values(monkeypatch):
    secret = "do-not-echo"

    class FakeClient:
        async def post(self, path, data=None, params=None, timeout=60.0):
            assert path == "/v1/plugin/apps/app-1/env/import"
            assert data["content"] == f"TOKEN={secret}"
            assert data["input_format"] == "dotenv"
            return {
                "app_name": "api",
                "imported_count": 1,
                "imported_keys": ["TOKEN"],
                "merge": True,
                "restart_mode": "restart",
                "task_id": "task-1",
            }

    monkeypatch.setattr(env_import, "_client", lambda: FakeClient())
    mcp = FakeMCP()
    register_env_import_tools(mcp)

    output = asyncio.run(
        mcp.tools["apply_app_env_vars"](
            app_id="app-1",
            env_content=f"TOKEN={secret}",
            input_format="dotenv",
        )
    )

    assert "TOKEN" in output
    assert "task-1" in output
    assert secret not in output


def test_apply_app_env_vars_accepts_direct_mapping(monkeypatch):
    class FakeClient:
        async def post(self, path, data=None, params=None, timeout=60.0):
            assert data["env_vars"] == {"PORT": "8000"}
            return {"app_name": "api", "imported_count": 1, "imported_keys": ["PORT"], "merge": False}

    monkeypatch.setattr(env_import, "_client", lambda: FakeClient())
    mcp = FakeMCP()
    register_env_import_tools(mcp)

    output = asyncio.run(mcp.tools["apply_app_env_vars"]("app-1", env_vars={"PORT": "8000"}, merge=False, restart_mode="none"))

    assert "replace" in output
    assert "No restart" in output


def test_apply_app_env_vars_rejects_implicit_clear_all():
    mcp = FakeMCP()
    register_env_import_tools(mcp)

    output = asyncio.run(mcp.tools["apply_app_env_vars"]("app-1", merge=False, restart_mode="none"))

    assert "explicit source" in output
