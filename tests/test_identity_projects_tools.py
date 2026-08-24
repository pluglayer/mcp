import asyncio

from pluglayer_mcp.tools import identity_projects
from pluglayer_mcp.tools.identity_projects import register_identity_project_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register


def test_rename_project_uses_plugin_patch_and_preserves_routing_identity(monkeypatch):
    calls = {}

    class FakeClient:
        async def patch(self, path, data):
            calls["patch"] = (path, data)
            return {
                "project": {
                    "id": "project-1",
                    "name": "Customer Portal",
                    "slug": "original-project",
                    "namespace": "pl-alice-original-project",
                }
            }

    async def fake_remember_context(payload):
        calls["context"] = payload

    monkeypatch.setattr(identity_projects, "_client", lambda: FakeClient())
    monkeypatch.setattr(identity_projects, "_remember_context", fake_remember_context)
    mcp = FakeMCP()
    register_identity_project_tools(mcp)

    output = asyncio.run(
        mcp.tools["rename_project"](
            project_id="project-1",
            new_name="  Customer Portal  ",
        )
    )

    assert calls["patch"] == (
        "/v1/plugin/projects/project-1",
        {"name": "Customer Portal"},
    )
    assert calls["context"]["projects"]["project-1"]["name"] == "Customer Portal"
    assert "Customer Portal" in output
    assert "original-project" in output
    assert "pl-alice-original-project" in output
    assert "Existing app URLs are unchanged" in output


def test_rename_project_rejects_invalid_display_name_without_api_call(monkeypatch):
    class UnexpectedClient:
        async def patch(self, path, data):
            raise AssertionError("invalid names must not reach the API")

    monkeypatch.setattr(identity_projects, "_client", lambda: UnexpectedClient())
    mcp = FakeMCP()
    register_identity_project_tools(mcp)

    output = asyncio.run(mcp.tools["rename_project"]("project-1", " "))

    assert "between 2 and 50 characters" in output


def test_update_project_metadata_uses_existing_project_patch_and_remembers_context(monkeypatch):
    calls = {}

    class FakeClient:
        async def patch(self, path, data):
            calls["patch"] = (path, data)
            return {
                "project": {
                    "id": "project-1",
                    "name": "Customer Platform",
                    "description": "Production services and supporting workers.",
                    "slug": "original-project",
                    "namespace": "pl-alice-original-project",
                }
            }

    async def fake_remember_context(payload):
        calls["context"] = payload

    monkeypatch.setattr(identity_projects, "_client", lambda: FakeClient())
    monkeypatch.setattr(identity_projects, "_remember_context", fake_remember_context)
    mcp = FakeMCP()
    register_identity_project_tools(mcp)

    output = asyncio.run(
        mcp.tools["update_project_metadata"](
            project_id="project-1",
            name="  Customer Platform  ",
            description="  Production services and supporting workers.  ",
        )
    )

    assert calls["patch"] == (
        "/v1/plugin/projects/project-1",
        {
            "name": "Customer Platform",
            "description": "Production services and supporting workers.",
        },
    )
    assert calls["context"]["projects"]["project-1"] == {
        "name": "Customer Platform",
        "description": "Production services and supporting workers.",
        "namespace": "pl-alice-original-project",
    }
    assert "Project metadata updated" in output
    assert "original-project" in output
    assert "Existing app URLs and custom-domain routing are unchanged" in output


def test_update_project_metadata_can_clear_description(monkeypatch):
    calls = {}

    class FakeClient:
        async def patch(self, path, data):
            calls["patch"] = (path, data)
            return {
                "project": {
                    "id": "project-1",
                    "name": "Customer Platform",
                    "description": "",
                    "slug": "customer-platform",
                    "namespace": "pl-alice-customer-platform",
                }
            }

    async def fake_remember_context(payload):
        return None

    monkeypatch.setattr(identity_projects, "_client", lambda: FakeClient())
    monkeypatch.setattr(identity_projects, "_remember_context", fake_remember_context)
    mcp = FakeMCP()
    register_identity_project_tools(mcp)

    output = asyncio.run(
        mcp.tools["update_project_metadata"](
            project_id="project-1",
            clear_description=True,
        )
    )

    assert calls["patch"] == (
        "/v1/plugin/projects/project-1",
        {"description": ""},
    )
    assert "Description: not set" in output


def test_update_project_metadata_rejects_ambiguous_or_empty_changes(monkeypatch):
    class UnexpectedClient:
        async def patch(self, path, data):
            raise AssertionError("invalid metadata must not reach the API")

    monkeypatch.setattr(identity_projects, "_client", lambda: UnexpectedClient())
    mcp = FakeMCP()
    register_identity_project_tools(mcp)

    empty = asyncio.run(mcp.tools["update_project_metadata"]("project-1"))
    conflicting = asyncio.run(
        mcp.tools["update_project_metadata"](
            "project-1",
            description="Keep this",
            clear_description=True,
        )
    )

    assert "Provide a project name, description" in empty
    assert "not both" in conflicting
