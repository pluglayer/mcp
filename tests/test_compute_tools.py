import asyncio

from pluglayer_mcp.tools import compute as compute_tools
from pluglayer_mcp.tools.compute import register_compute_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register


def test_attachable_nodes_surface_duplicate_physical_worker_blocker(monkeypatch):
    class FakeClient:
        async def get(self, path, params=None):
            assert path == "/v1/plugin/projects/project-1/compute/attachable"
            return {
                "nodes": [
                    {
                        "id": "node-duplicate",
                        "name": "worker-1",
                        "status": "ready",
                        "attachment_state": "duplicate_physical_node",
                        "attachment_blocker": {
                            "code": "duplicate_physical_node",
                            "message": "Ask an administrator to run duplicate-node cleanup.",
                        },
                    }
                ]
            }

    monkeypatch.setattr(compute_tools, "_client", lambda: FakeClient())
    mcp = FakeMCP()
    register_compute_tools(mcp)

    output = asyncio.run(mcp.tools["list_attachable_project_nodes"]("project-1"))

    assert "duplicate physical node" in output
    assert "blocked: Ask an administrator" in output
