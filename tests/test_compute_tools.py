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


def test_plan_dedicated_compute_surfaces_one_node_requirement(monkeypatch):
    class FakeClient:
        async def post(self, path, data):
            assert path == "/v1/plugin/compute/plan"
            assert data["workloads"][0]["cpu_cores"] == 2.5
            return {
                "status": "unavailable",
                "can_deploy_now": False,
                "message": "No machine fits.",
                "assignments": [],
                "marketplace_nodes": [],
                "shortages": [{
                    "workload_name": "API",
                    "required": {"cpu_cores": 2.5, "ram_gb": 3, "storage_gb": 10, "gpu_gb": 0},
                }],
            }

    monkeypatch.setattr(compute_tools, "_client", lambda: FakeClient())
    mcp = FakeMCP()
    register_compute_tools(mcp)

    output = asyncio.run(mcp.tools["plan_dedicated_compute"]("API", 2.5, 3, 10, 0, "project-1"))

    assert "Can deploy now: no" in output
    assert "needs 2.5 CPU" in output
    assert "on one machine" in output


def test_extra_compute_request_requires_confirmation(monkeypatch):
    mcp = FakeMCP()
    register_compute_tools(mcp)

    output = asyncio.run(mcp.tools["request_extra_compute"]("API", 2.5, 3))

    assert "Confirmation required" in output
