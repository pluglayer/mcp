"""Codex copies server instructions onto every tool. Keep that catalog small enough to load."""

import asyncio

from pluglayer_mcp.server import mcp

# Codex Desktop loaded a 41-tool alphabetical prefix whose stamped descriptions
# were this large, then dropped list_projects. Stay well under that proven budget.
PROVEN_CODEX_CATALOG_CHARS = 613_551
STAMPED_CATALOG_LIMIT = 90_000


def test_server_instructions_leave_room_for_every_tool():
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    instructions = mcp.instructions or ""

    assert "list_projects" in names
    assert "get_my_projects" in names
    assert "list_projects" in instructions
    assert "browser" in instructions
    assert "get_task_status" in instructions
    assert "Run setup only" in instructions
    assert "Leave unrelated work alone" in instructions

    stamped = sum(len(instructions) + len(tool.description or "") for tool in tools)
    assert len(instructions) < 700
    assert stamped < STAMPED_CATALOG_LIMIT
    assert stamped < PROVEN_CODEX_CATALOG_CHARS
