"""End-to-end MCP smoke test using the local-folder stdio server."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[2]
MCP_DIR = ROOT / "pluglayer-mcp"


READ_ONLY_TOOLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("get_current_user", {}),
    ("list_projects", {}),
    ("get_my_projects", {}),
    ("get_compute_summary", {}),
    ("get_my_available_compute", {}),
    ("get_my_available_computes", {}),
    (
        "estimate_compute",
        {
            "use_case": "A SaaS app with two backend APIs, one React frontend, Postgres, and Redis.",
            "components": ["2 backend APIs", "1 frontend", "postgres", "redis"],
            "expected_monthly_active_users": 1500,
            "expected_requests_per_minute": 40,
        },
    ),
    ("list_nodes", {}),
    ("list_registries", {}),
    ("list_deployments", {}),
)


@dataclass(slots=True)
class BackendFixtures:
    project_id: str | None = None
    app_id: str | None = None
    domain_id: str | None = None
    task_id: str | None = None


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def build_stdio_server_parameters() -> StdioServerParameters:
    api_url = _env("PLUGLAYER_API_URL", "http://localhost:8000")
    api_key = _env("PLUGLAYER_API_KEY")
    if not api_key:
        raise RuntimeError("PLUGLAYER_API_KEY is required.")
    return StdioServerParameters(
        command="uv",
        args=["run", "--directory", str(MCP_DIR), "pluglayer-mcp"],
        env={
            "PLUGLAYER_API_KEY": api_key,
            "PLUGLAYER_API_URL": api_url,
            "UV_CACHE_DIR": _env("UV_CACHE_DIR", ".uv-cache"),
        },
    )


class MCPTester:
    def __init__(self, server: StdioServerParameters):
        self.server = server

    @asynccontextmanager
    async def session(self):
        async with stdio_client(self.server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[Any]:
        async with self.session() as session:
            result = await session.list_tools()
            return result.tools

    async def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> list[str]:
        async with self.session() as session:
            result = await session.call_tool(tool_name, arguments or {})
            rendered: list[str] = []
            for item in getattr(result, "content", []) or []:
                text = getattr(item, "text", None)
                rendered.append(text if text is not None else repr(item))
            return rendered


async def discover_backend_fixtures() -> BackendFixtures:
    api_url = _env("PLUGLAYER_API_URL", "http://localhost:8000").rstrip("/")
    api_key = _env("PLUGLAYER_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"}

    fixtures = BackendFixtures(
        project_id=_env("PLUGLAYER_TEST_PROJECT_ID") or None,
        app_id=_env("PLUGLAYER_TEST_APP_ID") or None,
        domain_id=_env("PLUGLAYER_TEST_DOMAIN_ID") or None,
        task_id=_env("PLUGLAYER_TEST_TASK_ID") or None,
    )

    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=20.0) as client:
        if not fixtures.project_id:
            resp = await client.get("/v1/plugin/projects")
            resp.raise_for_status()
            projects = resp.json().get("projects", [])
            if projects:
                fixtures.project_id = projects[0].get("id")

        if fixtures.project_id and not fixtures.app_id:
            resp = await client.get(f"/v1/plugin/projects/{fixtures.project_id}/apps")
            resp.raise_for_status()
            apps = resp.json().get("apps", [])
            if apps:
                fixtures.app_id = apps[0].get("id")

        if fixtures.project_id and not fixtures.domain_id:
            resp = await client.get(f"/v1/plugin/projects/{fixtures.project_id}/domains")
            resp.raise_for_status()
            domains = resp.json().get("domains", [])
            if domains:
                fixtures.domain_id = domains[0].get("id")

    return fixtures


def optional_calls(fixtures: BackendFixtures) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    if fixtures.project_id:
        calls.extend(
            [
                ("get_project", {"project_id": fixtures.project_id}),
                ("get_apps_by_project", {"project_id": fixtures.project_id}),
                ("list_project_domains", {"project_id": fixtures.project_id}),
            ]
        )

    if fixtures.project_id and fixtures.app_id:
        calls.append(
            (
                "generate_github_actions",
                {
                    "project_id": fixtures.project_id,
                    "app_id": fixtures.app_id,
                    "repo": _env("PLUGLAYER_TEST_GITHUB_REPO", "pluglayer/app-pluglayer"),
                },
            )
        )
        calls.append(("inspect_local_github_repo", {}))

    if fixtures.app_id:
        calls.extend(
            [
                ("get_deployment_status", {"deployment_id": fixtures.app_id}),
                ("get_logs", {"deployment_id": fixtures.app_id, "lines": 25}),
                ("get_app_logs", {"app_id": fixtures.app_id, "lines": 25}),
            ]
        )

    if fixtures.task_id:
        calls.append(("get_task_status", {"task_id": fixtures.task_id}))

    return calls


def mutation_calls(fixtures: BackendFixtures) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    if _env("PLUGLAYER_TEST_CREATE_PROJECT") == "1":
        calls.append(
            (
                "create_project",
                {
                    "name": _env("PLUGLAYER_TEST_PROJECT_NAME", "mcp-smoke-project"),
                    "description": "Temporary smoke-test project",
                    "domain_type": "pluglayer",
                },
            )
        )

    if fixtures.app_id and _env("PLUGLAYER_TEST_ALLOW_RESTART") == "1":
        calls.extend(
            [
                ("restart_app", {"app_id": fixtures.app_id}),
                ("redeploy", {"deployment_id": fixtures.app_id}),
                ("rollback", {"deployment_id": fixtures.app_id}),
            ]
        )

    if fixtures.project_id and _env("PLUGLAYER_TEST_ALLOW_DOMAIN_MUTATIONS") == "1":
        domain = _env("PLUGLAYER_TEST_DOMAIN")
        if domain:
            calls.append(
                (
                    "add_custom_domain",
                    {
                        "project_id": fixtures.project_id,
                        "domain": domain,
                        "mode": "single",
                        "app_id": fixtures.app_id or "",
                    },
                )
            )

    return calls


async def run_smoke_test(require_all: bool, include_mutations: bool) -> int:
    tester = MCPTester(build_stdio_server_parameters())
    tools = await tester.list_tools()
    tool_names = {tool.name for tool in tools}

    expected_tools = {name for name, _args in READ_ONLY_TOOLS}
    missing = sorted(expected_tools - tool_names)
    if missing:
        print("Missing expected MCP tools:")
        for name in missing:
            print(f"  - {name}")
        return 1

    fixtures = await discover_backend_fixtures()
    calls = list(READ_ONLY_TOOLS)
    calls.extend(optional_calls(fixtures))
    if include_mutations:
        calls.extend(mutation_calls(fixtures))

    skipped: list[str] = []
    failures: list[tuple[str, str]] = []

    for tool_name, arguments in calls:
        if tool_name not in tool_names:
            skipped.append(f"{tool_name} (not exposed)")
            continue
        print(f"Running {tool_name}...")
        try:
            content = await tester.call(tool_name, arguments)
        except Exception as exc:  # pragma: no cover - integration handling
            failures.append((tool_name, f"{type(exc).__name__}: {exc}"))
            continue

        if not content:
            failures.append((tool_name, "empty MCP response"))
            continue

        text = "\n".join(content)
        if "error" in text.lower() and "error:" in text.lower():
            failures.append((tool_name, text[:600]))
            continue

        print(f"  PASS {tool_name}")

    print("\nFixture discovery:")
    print(f"  project_id: {fixtures.project_id or 'none'}")
    print(f"  app_id:     {fixtures.app_id or 'none'}")
    print(f"  domain_id:  {fixtures.domain_id or 'none'}")
    print(f"  task_id:    {fixtures.task_id or 'none'}")

    if skipped:
        print("\nSkipped:")
        for item in skipped:
            print(f"  - {item}")

    if failures:
        print("\nFailures:")
        for tool_name, message in failures:
            print(f"  - {tool_name}: {message}")
        return 1

    if require_all:
        missing_fixtures = []
        if not fixtures.project_id:
            missing_fixtures.append("project_id")
        if not fixtures.app_id:
            missing_fixtures.append("app_id")
        if missing_fixtures:
            print("\nRequired full coverage fixtures missing:")
            for item in missing_fixtures:
                print(f"  - {item}")
            return 1

    print("\nAll executed MCP tool checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test PlugLayer MCP through the local-folder stdio server."
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail if no project/app fixtures were discoverable for the optional coverage set.",
    )
    parser.add_argument(
        "--include-mutations",
        action="store_true",
        help="Also run mutation tools that are explicitly enabled through env fixtures.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(
        run_smoke_test(
            require_all=args.require_all,
            include_mutations=args.include_mutations,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
