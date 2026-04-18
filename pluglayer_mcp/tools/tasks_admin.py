"""Tasks Admin MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_compute, _fmt_task_hint, _status_emoji


def register_task_admin_tools(mcp):
    # ── Tasks ─────────────────────────────────────────────────────────────────────


    @mcp.tool()
    async def get_task_status(task_id: str) -> str:
        """Check async operation status, progress, result URL, or error."""
        try:
            data = await _client().get(f"/v1/tasks/{task_id}")
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


    # ── Admin tools ────────────────────────────────────────────────────────────────


    @mcp.tool()
    async def admin_get_overview() -> str:
        """Admin only: summarize platform tasks, capacity events, nodes, and compute defaults."""
        try:
            tasks = await _client().get("/v1/admin/tasks", params={"limit": 10})
            events = await _client().get("/v1/admin/capacity-events", params={"limit": 10})
            nodes = await _client().get("/v1/admin/nodes")
            compute = await _client().get("/v1/admin/compute/settings")
            stats = tasks.get("stats", {})
            return (
                "🛡️ **Admin Overview**\n"
                f"Projects: {stats.get('projects', 0)} | Deployments: {stats.get('deployments', 0)} | Nodes: {stats.get('nodes', 0)} | Tasks today: {stats.get('tasks_today', 0)}\n"
                f"Unresolved capacity events: {events.get('unresolved_count', 0)}\n"
                f"Registered nodes: {len(nodes.get('nodes', []))}\n"
                f"Default quota: {_fmt_compute(compute.get('default_quota'))}\n"
            )
        except Exception as e:
            return _compact_error("Admin overview failed (requires pluglayer-admin or pluglayer-superadmin role)", e)


    @mcp.tool()
    async def admin_set_compute_defaults(
        cpu_cores: float,
        ram_gb: float,
        storage_gb: int,
        gpu_gb: float = 0,
        allow_shared_compute: bool = True,
    ) -> str:
        """Admin only: update default compute quota metadata shown to new users."""
        try:
            await _client().put("/v1/admin/compute/settings", {
                "allow_shared_compute": allow_shared_compute,
                "default_quota": {
                    "cpu_cores": cpu_cores,
                    "ram_gb": ram_gb,
                    "storage_gb": storage_gb,
                    "gpu_gb": gpu_gb,
                },
            })
            return f"✅ Default compute saved: {_fmt_compute({'cpu_cores': cpu_cores, 'ram_gb': ram_gb, 'storage_gb': storage_gb, 'gpu_gb': gpu_gb})}"
        except Exception as e:
            return _compact_error("Failed to update admin compute defaults", e)


    @mcp.tool()
    async def admin_set_node_shared(node_id: str, is_shared: bool = True) -> str:
        """Admin only: mark an existing node as shared PlugLayer compute or private."""
        try:
            data = await _client().patch(f"/v1/admin/nodes/{node_id}/sharing", {"is_shared": is_shared})
            warning = f"\nWarning: {data['warning']}" if data.get("warning") else ""
            return f"✅ Node `{node_id}` shared={data.get('is_shared', is_shared)}.{warning}"
        except Exception as e:
            return _compact_error("Failed to update node sharing", e)


    @mcp.tool()
    async def admin_add_shared_ssh_node(
        name: str,
        host: str,
        ssh_private_key: str,
        user: str = "root",
        port: int = 22,
    ) -> str:
        """Admin only: add an SSH node as PlugLayer-owned shared compute for all users."""
        if not name or not host or not ssh_private_key:
            return "Missing required fields: name, host, and ssh_private_key are required."
        try:
            data = await _client().post("/v1/admin/nodes/ssh", {
                "name": name,
                "provider": "ssh",
                "ssh_host": host,
                "ssh_port": port,
                "ssh_user": user,
                "ssh_private_key": ssh_private_key,
            })
            task_id = data.get("task_id")
            node = data.get("node", {})
            return (
                f"✅ Shared PlugLayer SSH node queued.\n"
                f"Node: **{node.get('name', name)}** (id: `{node.get('id')}`)\n"
                f"Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
            )
        except Exception as e:
            return _compact_error("Failed to add shared SSH node", e)
