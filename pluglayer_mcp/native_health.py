"""Bounded dependency probes and real stdio verification; no user data output."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def probe(command: list[str]) -> bool:
    try:
        environment = {key: value for key, value in os.environ.items() if key != "PLUGLAYER_API_KEY"}
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, env=environment)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def doctor() -> dict:
    docker = shutil.which("docker")
    git = shutil.which("git")
    result = {"git": bool(git and probe([git, "--version"])),
              "docker_cli": bool(docker),
              "docker_daemon": bool(docker and probe([docker, "info"])),
              "docker_buildx": bool(docker and probe([docker, "buildx", "version"]))}
    return {**result, "local_build_ready": all(result.values())}


async def tool_names() -> list[str]:
    from pluglayer_mcp.server import mcp
    return sorted(tool.name for tool in await mcp.list_tools())


def build_info() -> dict:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    path = base / "connector-build.json"
    return json.loads(path.read_text()) if path.exists() else {"release": "development", "tools": []}


async def verify_stdio(executable: Path, credentials: Path, expected: list[str]) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PLUGLAYER_API_KEY", "PLUGLAYER_API_URL"}}
    environment["PLUGLAYER_CREDENTIALS_FILE"] = str(credentials)
    # Source-mode tests use the same entrypoint; shipped connectors run directly.
    args = [] if getattr(sys, "frozen", False) else ["-m", "pluglayer_mcp.native"]
    params = StdioServerParameters(command=str(executable), args=args, env=environment)
    async with asyncio.timeout(90):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                if names != set(expected):
                    raise RuntimeError("Installed connector tool inventory does not match the release")
                for name in ("get_current_user", "list_projects"):
                    result = await session.call_tool(name, {})
                    content = "\n".join(item.text for item in result.content if hasattr(item, "text"))
                    if result.isError or not content.strip() or content.lower().startswith(("error", "❌")):
                        raise RuntimeError("Installed connector authentication/read verification failed")
