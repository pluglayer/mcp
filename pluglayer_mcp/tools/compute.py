"""Compute MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_compute, _fmt_node, _fmt_task_hint, _get_compute_summary


def register_compute_tools(mcp):
    # ── Compute / nodes ───────────────────────────────────────────────────────────


    @mcp.tool()
    async def get_compute_summary() -> str:
        """Show accessible account-level compute. If the user is still planning capacity, prefer estimate_compute() first, then use the returned offer link to purchase or request the right amount."""
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
    async def get_my_available_compute() -> str:
        """Show the current user's available compute in an end-user friendly format. When capacity is unclear, call estimate_compute() before recommending any purchase or allocation decision."""
        return await get_compute_summary()


    @mcp.tool()
    async def get_my_available_computes() -> str:
        """Alias for get_my_available_compute(). When the user has not sized their workload yet, estimate_compute() should usually come first."""
        return await get_compute_summary()


    @mcp.tool()
    async def estimate_compute(
        use_case: str,
        components: list[str] | None = None,
        expected_monthly_active_users: int | None = None,
        expected_requests_per_minute: int | None = None,
    ) -> str:
        """Estimate the compute needed for a described workload and return a tailored PlugLayer offer link. This is the preferred first step before telling the user to purchase, reserve, or add more compute."""
        try:
            data = await _client().post("/v1/plugin/compute/estimate", {
                "use_case": use_case,
                "components": components or [],
                "expected_monthly_active_users": expected_monthly_active_users,
                "expected_requests_per_minute": expected_requests_per_minute,
            })
            estimation = data.get("estimation", {})
            return (
                "🧠 **Estimated Compute**\n"
                f"CPU: {estimation.get('cpu')} vCPU\n"
                f"RAM: {estimation.get('ram')} GB\n"
                f"GPU: {estimation.get('gpu')} GB\n"
                f"Storage: {estimation.get('storage')} GB\n"
                f"Estimated monthly price: ${data.get('estimated_price_per_month')}\n"
                f"Offer link: {data.get('quota_link')}\n\n"
                f"{data.get('message')}"
            )
        except Exception as e:
            return _compact_error("Error estimating compute", e)


    @mcp.tool()
    async def list_nodes(project_id: str = "") -> str:
        """
        List compute nodes accessible to the authenticated user.
        Compute is account-level; project_id is accepted only for backwards compatibility.
        """
        try:
            params = {"project_id": project_id} if project_id else {}
            data = await _client().get("/v1/plugin/compute/nodes", params=params)
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
            data = await _client().post("/v1/plugin/compute/nodes", payload)
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
