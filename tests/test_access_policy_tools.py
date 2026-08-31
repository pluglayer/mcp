import asyncio
import json
from copy import deepcopy

import pytest
from mcp.server.fastmcp import FastMCP

from pluglayer_mcp.tools.deployment import access_policy


POLICY = {
    "http_rate_limit": {"average": 37, "burst": 81, "period_seconds": 60},
    "tcp_max_connections": 19,
    "allowed_cidrs": ["203.0.113.0/24", "2001:db8::/64"],
}


class Client:
    def __init__(self):
        self.app = {
            "id": "app-1", "name": "api", "project_id": "project-1",
            "access_policy": deepcopy(POLICY), "access_policy_protocols": ["http"],
            "env_vars": {"PASSWORD": "hidden-env"}, "compose_yaml": "hidden-compose",
            "database_details": {"connection_fields": ["hidden-connection"]},
        }
        self.writes = []
        self.failure = None

    async def get(self, path):
        assert path == "/v1/plugin/apps/app-1"
        return {"app": self.app}

    async def put(self, path, data):
        self.writes.append((path, data))
        if self.failure:
            raise RuntimeError(self.failure)
        self.app["access_policy"] = data
        return {"app": self.app, "access_policy": data, "applied_routes": 2}


def setup(monkeypatch):
    client = Client()
    monkeypatch.setattr(access_policy, "_client", lambda: client)
    mcp = FastMCP("test")
    access_policy.register_access_policy_tools(mcp)
    return client, mcp


def call(mcp, name, **args):
    blocks = asyncio.run(mcp.call_tool(name, args))
    if isinstance(blocks, tuple):
        blocks = blocks[0]
    return "\n".join(block.text for block in blocks if hasattr(block, "text"))


def update_args():
    return {
        "app_id": "app-1", "confirmed_app_name": "api", "http_average": 22,
        "http_burst": 81, "http_period_seconds": 60, "tcp_max_connections": 19,
        "allowed_cidrs": POLICY["allowed_cidrs"],
    }


def test_policy_read_excludes_app_secrets(monkeypatch):
    _, mcp = setup(monkeypatch)
    output = call(mcp, "get_app_access_policy", app_id="app-1")
    assert json.loads(output)["access_policy"] == POLICY
    assert "hidden-" not in output
    assert "env_vars" not in output


def test_rate_change_preserves_explicit_other_settings_and_filters_response(monkeypatch):
    client, mcp = setup(monkeypatch)
    output = call(mcp, "update_app_access_policy", **update_args())
    expected = deepcopy(POLICY)
    expected["http_rate_limit"]["average"] = 22
    assert client.writes == [("/v1/plugin/apps/app-1/access", expected)]
    assert json.loads(output)["access_policy"] == expected
    assert json.loads(output)["applied_routes"] == 2
    assert "hidden-" not in output


def test_missing_allowlist_is_rejected_but_explicit_empty_is_sent(monkeypatch):
    client, mcp = setup(monkeypatch)
    args = update_args()
    del args["allowed_cidrs"]
    with pytest.raises(Exception, match="allowed_cidrs"):
        call(mcp, "update_app_access_policy", **args)
    assert client.writes == []
    args["allowed_cidrs"] = []
    call(mcp, "update_app_access_policy", **args)
    assert client.writes[0][1]["allowed_cidrs"] == []


@pytest.mark.parametrize("failure", ["wrong-name", "missing-policy"])
def test_unknown_target_or_policy_never_writes(monkeypatch, failure):
    client, mcp = setup(monkeypatch)
    if failure == "wrong-name":
        client.app["name"] = "different-app"
    else:
        del client.app["access_policy"]
    assert call(mcp, "update_app_access_policy", **update_args()).startswith("Error")
    assert client.writes == []


@pytest.mark.parametrize("failure", ["403 Forbidden", "404 Not Found", "enforcement uncertain", "timeout"])
def test_failed_write_is_not_retried_or_reported_as_success(monkeypatch, failure):
    client, mcp = setup(monkeypatch)
    client.failure = failure
    output = call(mcp, "update_app_access_policy", **update_args())
    assert output.startswith("Error")
    assert "inspect current state before retrying" in output
    assert len(client.writes) == 1
