"""Task status MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _status_emoji


def register_task_tools(mcp):
    # ── Tasks ─────────────────────────────────────────────────────────────────────


    @mcp.tool()
    async def get_task_status(task_id: str) -> str:
        """Check async operation status, progress, result URL, or error."""
        try:
            data = await _client().get(f"/v1/plugin/tasks/{task_id}")
            t = data.get("task", data)
            status = t.get("status", "unknown")
            progress = t.get("progress", {}) or {}
            result = t.get("result") or {}
            result_str = ""
            if result.get("primary_url"):
                result_str = f"\n🌐 App URL: {result['primary_url']}"
            elif result.get("k3s_node_name"):
                result_str = f"\n🖥️ Node joined as: {result['k3s_node_name']}"
            elif result:
                result_str = f"\nResult: {result}"
            error = t.get("error_message") or t.get("error")
            error_str = f"\n❌ Error: {error}" if error else ""
            return (
                f"{_status_emoji(status)} **Task {t.get('type', '')}**\n"
                f"Status: {status}\n"
                f"Progress: {round(progress.get('percentage', 0))}% — {progress.get('message', '')}\n"
                f"Steps: {progress.get('step', 0)}/{progress.get('total_steps', 0)}"
                f"{result_str}{error_str}"
            )
        except Exception as e:
            return _compact_error("Error getting task", e)
