"""Shared helpers for PlugLayer MCP tools."""

from typing import Any

from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.settings import settings


def _client() -> PlugLayerClient:
    return PlugLayerClient(api_key=settings.PLUGLAYER_API_KEY)


def _status_emoji(status: str) -> str:
    return {
        "active": "✅", "ready": "✅", "running": "🕺", "completed": "✅",
        "provisioning": "⏳", "pending": "😴", "queued": "⏳", "deploying": "🚀", "joining": "🔗",
        "in_progress": "⚙️", "scaling": "⚙️",
        "error": "❌", "failed": "💀", "crash_loop": "🥴", "offline": "💤",
        "terminated": "🪦", "terminating": "👻", "cancelled": "🚫", "suspended": "⏸️",
        "deleting": "🧹",
    }.get(str(status or ""), "❓")


def _fmt_compute(compute: dict[str, Any] | None) -> str:
    c = compute or {}
    return (
        f"{c.get('cpu_cores', 0)} CPU, "
        f"{c.get('ram_gb', 0)}GB RAM, "
        f"{c.get('storage_gb', 0)}GB disk, "
        f"{c.get('gpu_gb', 0)}GB GPU"
    )


def _fmt_node(node: dict[str, Any]) -> str:
    status = node.get("status", "unknown")
    owner = "shared PlugLayer" if node.get("is_shared") else "personal"
    return (
        f"{_status_emoji(status)} **{node.get('name', 'unnamed')}** (id: `{node.get('id')}`)\n"
        f"   Provider: {node.get('provider')} | Status: {status} | Scope: {owner}\n"
        f"   Compute: {_fmt_compute(node.get('hardware'))}\n"
    )


def _fmt_task_hint(task_id: str | None) -> str:
    return f"Poll: `get_task_status('{task_id}')`" if task_id else "No task id returned."


def _compact_error(prefix: str, exc: Exception) -> str:
    return f"{prefix}: {exc}"


async def _get_compute_summary() -> dict[str, Any]:
    return await _client().get("/v1/plugin/compute")
