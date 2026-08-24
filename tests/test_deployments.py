import asyncio
import inspect

from pluglayer_mcp.tools.deployment import app_read
from pluglayer_mcp.tools.deployment.app_operations import register_app_operations_tools
from pluglayer_mcp.tools.deployment.app_read import register_app_read_tools
from pluglayer_mcp.tools.deployment.images import register_images_tools
from pluglayer_mcp.tools.deployments import _compose_build_commands, _find_existing_project_app_match


def test_compose_build_commands_formats_local_build_steps():
    plan = {
        "services": [
            {
                "service_name": "worker",
                "strategy": "local_build_image",
                "build_context": ".",
                "build_dockerfile": "Dockerfile.worker",
                "command_args": ["python worker.py"],
            }
        ]
    }

    output = _compose_build_commands(plan, "/repo", "my-stack")

    assert "docker" in output
    assert "Dockerfile.worker" in output
    assert ".pluglayer/worker.oci.tar" in output
    assert 'local_image_archives={"worker": "/repo/.pluglayer/worker.oci.tar"}' in output


def test_find_existing_project_app_match_prefers_exact_slug():
    apps = [
        {"id": "1", "name": "agents-marketplace-api-r22", "route_slug": "agents-marketplace-api-r22"},
        {"id": "2", "name": "agents-marketplace-api", "route_slug": "agents-marketplace-api"},
    ]

    match = _find_existing_project_app_match(
        apps,
        name="agents-marketplace-api-r22",
        route_slug="agents-marketplace-api",
    )

    assert match
    assert match["id"] == "2"


def test_find_existing_project_app_match_falls_back_to_name():
    apps = [
        {"id": "9", "name": "billing-worker", "route_slug": "billing-worker-live"},
    ]

    match = _find_existing_project_app_match(
        apps,
        name="billing-worker",
        route_slug="",
    )

    assert match
    assert match["id"] == "9"


def test_uploaded_image_redeploy_queues_without_synchronous_wait_by_default():
    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def register(function):
                self.tools[function.__name__] = function
                return function

            return register

    mcp = FakeMCP()
    register_images_tools(mcp)

    signature = inspect.signature(mcp.tools["upload_image_archive_and_redeploy_app"])

    assert signature.parameters["wait_seconds"].default == 0


def test_get_app_logs_preserves_get_logs_alias(monkeypatch):
    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def register(function):
                self.tools[function.__name__] = function
                return function

            return register

    class FakeClient:
        async def get(self, path, params=None):
            assert path == "/v1/plugin/apps/app-1/logs"
            assert params == {"tail": 25}
            return {"logs": "hello"}

    mcp = FakeMCP()
    get_logs = register_app_read_tools(mcp)
    register_app_operations_tools(mcp, get_logs)
    monkeypatch.setattr(app_read, "_client", lambda: FakeClient())

    output = asyncio.run(mcp.tools["get_app_logs"]("app-1", 25))

    assert "hello" in output
