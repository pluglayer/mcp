import asyncio
import inspect

from pluglayer_mcp.tools.deployment import app_read, images as image_tools
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


def test_large_existing_app_archive_uses_retry_safe_chunk_session(monkeypatch, tmp_path):
    archive = tmp_path / "image.oci.tar"
    archive.write_bytes(b"abcdefghij")
    calls = {"chunks": []}

    class FakeClient:
        async def post(self, path, data=None, params=None, timeout=60.0):
            calls.setdefault("posts", []).append((path, data, timeout))
            if path.endswith("/image-upload-sessions"):
                return {"upload_id": "upload-1", "chunk_size": 4}
            return {"task_id": "task-1", "received": True}

        async def put_bytes(self, path, content, *, headers, timeout=300.0):
            calls["chunks"].append((path, content, headers))
            return {"received_bytes": int(headers["X-Upload-Offset"]) + len(content)}

    monkeypatch.setattr(image_tools, "_CHUNKED_UPLOAD_THRESHOLD_BYTES", 4)
    result = asyncio.run(
        image_tools._upload_existing_app_archive(
            FakeClient(),
            app_id="app-1",
            image_archive_path=str(archive),
            tag="release-1",
            registry_id="",
            redeploy_strategy="recreate",
            wait_seconds=0,
        )
    )

    assert result["task_id"] == "task-1"
    assert [content for _, content, _ in calls["chunks"]] == [b"abcd", b"efgh", b"ij"]
    assert [headers["X-Upload-Offset"] for _, _, headers in calls["chunks"]] == ["0", "4", "8"]
    assert calls["posts"][-1][0].endswith("/upload-1/complete-redeploy")
    assert calls["posts"][-1][2] == 1800.0


def test_large_new_app_archive_uses_retry_safe_chunk_session(monkeypatch, tmp_path):
    archive = tmp_path / "image.oci.tar"
    archive.write_bytes(b"abcdefghij")
    calls = {"chunks": []}

    class FakeClient:
        async def get(self, path, params=None):
            assert path == "/v1/plugin/projects/project-1/apps"
            return {"apps": []}

        async def post(self, path, data=None, params=None, timeout=60.0):
            calls.setdefault("posts", []).append((path, data, timeout))
            if path.endswith("/image-upload-sessions"):
                return {"upload_id": "upload-1", "chunk_size": 4}
            return {
                "task_id": "task-new",
                "app": {"id": "app-new", "name": "new-app", "route_slug": "new-app"},
                "mirrored_image": "registry.example/new-app:release-1",
            }

        async def put_bytes(self, path, content, *, headers, timeout=300.0):
            calls["chunks"].append((path, content, headers))
            return {"received_bytes": int(headers["X-Upload-Offset"]) + len(content)}

    async def ready_compute(*, project_id):
        return {"can_deploy": True}

    async def remember_context(update):
        calls["context"] = update

    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def register(function):
                self.tools[function.__name__] = function
                return function

            return register

    client = FakeClient()
    mcp = FakeMCP()
    monkeypatch.setattr(image_tools, "_CHUNKED_UPLOAD_THRESHOLD_BYTES", 4)
    monkeypatch.setattr(image_tools, "_client", lambda: client)
    monkeypatch.setattr(image_tools, "_get_compute_summary", ready_compute)
    monkeypatch.setattr(image_tools, "_remember_context", remember_context)
    register_images_tools(mcp)

    output = asyncio.run(
        mcp.tools["upload_image_archive_and_deploy"](
            project_id="project-1",
            name="new-app",
            image_archive_path=str(archive),
            tag="release-1",
            ports=[8080],
            route_slug="new-app",
        )
    )

    assert "task-new" in output
    assert [content for _, content, _ in calls["chunks"]] == [b"abcd", b"efgh", b"ij"]
    assert calls["posts"][0][0] == "/v1/plugin/projects/project-1/apps/image-upload-sessions"
    complete_path, complete_payload, complete_timeout = calls["posts"][-1]
    assert complete_path.endswith("/upload-1/complete-deploy")
    assert complete_payload["deploy_request"]["source"]["tag"] == "release-1"
    assert complete_payload["deploy_request"]["source"]["ports"] == [8080]
    assert complete_timeout == 1800.0


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
