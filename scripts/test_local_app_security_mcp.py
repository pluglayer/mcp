"""Read-only app security smoke using the real local stdio server and saved credentials.

Checks tool schemas and calls live inventory/status/logs/policy reads. Never changes
customer policy, prints logs, or returns credentials. Writes need separate release
validation on an explicitly authorized disposable app.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

MCP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MCP_DIR))

from pluglayer_mcp.client import get_client
from pluglayer_mcp.credentials import resolve_api_base_url, resolve_api_key


async def run(app_id: str | None) -> int:
    key, url = resolve_api_key(), resolve_api_base_url()
    if not app_id:
        inventory = await get_client().get("/v1/plugin/apps")
        candidates = [app for app in inventory.get("apps", []) if app.get("status") != "removed"]
        if candidates:
            app_id = candidates[0]["id"]

    server = StdioServerParameters(
        command=sys.executable, args=["-m", "pluglayer_mcp.server"],
        env={"PYTHONPATH": str(MCP_DIR), "PLUGLAYER_API_KEY": key, "PLUGLAYER_API_URL": url},
    )
    failures = []
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            needed = {"get_app_access_policy", "update_app_access_policy", "get_app_logs",
                      "get_deployment_status", "list_deployments"}
            if not needed.issubset(tools):
                print(f"Missing tools: {sorted(needed - tools.keys())}")
                return 1
            required = set(tools["update_app_access_policy"].inputSchema.get("required", []))
            if not {"app_id", "confirmed_app_name", "allowed_cidrs", "http_average",
                    "http_burst", "http_period_seconds", "tcp_max_connections"}.issubset(required):
                print("FAIL: update schema permits an incomplete policy")
                return 1
            print("App security tool registration and complete-policy schema: PASS")
            calls = [("list_deployments", {})]
            if app_id:
                calls += [
                    ("get_app_access_policy", {"app_id": app_id}),
                    ("get_deployment_status", {"deployment_id": app_id}),
                    ("get_app_logs", {"app_id": app_id, "lines": 20}),
                ]
            else:
                print("FAIL: no accessible app available for live policy read")
                failures.append("no-app")
            for name, args in calls:
                result = await session.call_tool(name, args)
                content = "\n".join(item.text for item in result.content if hasattr(item, "text"))
                failed = bool(result.isError) or content.lower().startswith("error")
                if name == "get_app_access_policy" and not failed:
                    view = json.loads(content)
                    failed = not isinstance(view.get("access_policy", {}).get("allowed_cidrs"), list)
                    failed |= any(key in view for key in ("env_vars", "compose_yaml", "database_details"))
                if failed:
                    failures.append(name)
                    status = next((str(code) for code in (401, 403, 404, 422, 500, 502, 503)
                                   if str(code) in content), "unknown")
                    print(f"{name}: FAIL (status {status}; private response withheld)")
                else:
                    print(f"{name}: PASS (private response withheld)")
    print("No policy writes performed; deployed update route and enforcement are not validated by this smoke.")
    return int(bool(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args.app_id)))
    except Exception as exc:
        # Transport errors may embed URLs or private responses; report only the type.
        print(f"App security smoke failed: {type(exc).__name__}; private details withheld")
        raise SystemExit(1)
