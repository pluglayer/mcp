"""Compute MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_compute, _fmt_node, _fmt_task_hint, _get_compute_summary


def register_compute_tools(mcp):
    # ── Compute / nodes ───────────────────────────────────────────────────────────


    @mcp.tool()
    async def get_compute_summary() -> str:
        """Show accessible account-level compute: personal SSH nodes plus shared PlugLayer nodes."""
        try:
            data = await _get_compute_summary()
            counts = data.get("counts", {})
            lines = [
                "🧮 **Compute Summary**",
                f"Can deploy: {'yes' if data.get('can_deploy') else 'no'}",
                f"Message: {data.get('message')}",
                f"Accessible nodes: {counts.get('accessible', 0)} total, {counts.get('ready', 0)} ready",
                f"Personal nodes: {counts.get('personal', 0)} total, {counts.get('personal_ready', 0)} ready",
                f"PlugLayer shared nodes: {counts.get('pluglayer', 0)} total, {counts.get('pluglayer_ready', 0)} ready",
                f"Total ready compute: {_fmt_compute(data.get('total_compute'))}",
                f"Personal ready compute: {_fmt_compute(data.get('personal_compute'))}",
                f"Shared ready compute: {_fmt_compute(data.get('pluglayer_compute'))}",
            ]
            purchase = data.get("purchase") or {}
            if purchase.get("message"):
                lines.append(f"Purchase: {purchase['message']}")
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error loading compute summary", e)


    @mcp.tool()
    async def list_nodes(project_id: str = "") -> str:
        """
        List compute nodes accessible to the authenticated user.
        Compute is account-level; project_id is accepted only for backwards compatibility.
        """
        try:
            params = {"project_id": project_id} if project_id else {}
            data = await _client().get("/v1/compute/nodes", params=params)
            nodes = data.get("nodes", [])
            if not nodes:
                return "No accessible compute nodes found. Add one with add_node_ssh(), or ask an admin to assign shared compute."
            lines = ["Accessible compute nodes:\n"]
            lines.extend(_fmt_node(n) for n in nodes)
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing compute nodes", e)


    @mcp.tool()
    async def add_node_ssh(
        project_id: str,
        name: str,
        host: str,
        ssh_private_key: str,
        user: str = "root",
        port: int = 22,
    ) -> str:
        """
        Add a personal SSH node/VM as account-level compute.

        project_id is optional/backwards-compatible setup context. The node belongs to the authenticated
        user and can be used by all of that user's projects. Pass an empty string when no project context is needed.
        """
        if not name or not host or not ssh_private_key:
            return "Missing required fields: name, host, and ssh_private_key are required."
        try:
            payload = {
                "name": name,
                "provider": "ssh",
                "ssh_host": host,
                "ssh_port": port,
                "ssh_user": user,
                "ssh_private_key": ssh_private_key,
            }
            if project_id:
                payload["project_id"] = project_id
            data = await _client().post("/v1/compute/nodes", payload)
            task_id = data.get("task_id")
            node = data.get("node", {})
            return (
                f"✅ SSH node queued as personal account compute.\n"
                f"Node: **{node.get('name', name)}** (id: `{node.get('id')}`)\n"
                f"Task ID: `{task_id}`\n\n"
                f"⚙️ Installing k3s agent and detecting CPU/RAM/storage/GPU. {_fmt_task_hint(task_id)}"
            )
        except Exception as e:
            return _compact_error("Failed to add SSH node", e)
