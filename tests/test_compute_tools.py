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


def test_plan_dedicated_compute_surfaces_purchase_link(monkeypatch):
    class FakeClient:
        async def post(self, path, data):
            assert path == "/v1/plugin/compute/plan"
            return {
                "status": "purchase_required",
                "can_deploy_now": False,
                "message": "Purchase the recommended machine.",
                "assignments": [{
                    "workload_name": "API",
                    "node_id": "node-1",
                    "node_name": "Medium",
                    "action": "purchase",
                    "required": {"cpu_cores": 1, "ram_gb": 2, "storage_gb": 10, "gpu_gb": 0},
                    "purchase_url": "https://portal.example/marketplace?intent=compute-catalog&node_id=node-1",
                }],
                "marketplace_nodes": [{
                    "node_id": "node-1",
                    "node_name": "Medium",
                    "monthly_price": 24,
                    "purchase_url": "https://portal.example/marketplace?intent=compute-catalog&node_id=node-1",
                }],
                "marketplace_monthly_total": 24,
                "shortages": [],
            }

    monkeypatch.setattr(compute_tools, "_client", lambda: FakeClient())
    mcp = FakeMCP()
    register_compute_tools(mcp)

    output = asyncio.run(mcp.tools["plan_dedicated_compute"]("API", 1, 2, 10))

    assert "Purchase this recommended machine" in output
    assert "intent=compute-catalog&node_id=node-1" in output


def test_estimate_compute_always_surfaces_saved_offer_link(monkeypatch):
    class FakeClient:
        async def post(self, path, data):
            assert path == "/v1/plugin/compute/estimate"
            return {
                "estimation": {"cpu": 1, "ram": 2, "storage": 10, "gpu": 0},
                "estimated_price_per_month": 24,
                "quota_link": "https://portal.example/marketplace?intent=compute-offer&offer_id=offer-1",
                "message": "Estimate ready.",
                "marketplace_nodes": [],
                "dedicated_plan": {"status": "ready", "can_deploy_now": True, "message": "Capacity is ready."},
            }

        async def get(self, path, params=None):
            assert path == "/v1/plugin/compute/catalog"
            return {"nodes": []}

    monkeypatch.setattr(compute_tools, "_client", lambda: FakeClient())
    mcp = FakeMCP()
    register_compute_tools(mcp)

    output = asyncio.run(mcp.tools["estimate_compute"](use_case="A small production API"))

    assert "Open this saved compute offer" in output
    assert "offer_id=offer-1" in output


def test_extra_compute_request_requires_confirmation(monkeypatch):
    mcp = FakeMCP()
    register_compute_tools(mcp)

    output = asyncio.run(mcp.tools["request_extra_compute"]("API", 2.5, 3))

    assert "Confirmation required" in output
