"""Compute MCP tools."""

from typing import Any

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_compute, _fmt_node, _fmt_task_hint, _get_compute_summary


def _compute_value(compute: dict[str, Any] | None, key: str) -> float:
    try:
        return float((compute or {}).get(key, 0) or 0)
    except Exception:
        return 0.0


def _compute_int_value(compute: dict[str, Any] | None, key: str) -> int:
    try:
        return int(float((compute or {}).get(key, 0) or 0))
    except Exception:
        return 0


def _fmt_usage_over_allocated(used: dict[str, Any] | None, allocated: dict[str, Any] | None) -> str:
    return (
        f"{_compute_value(used, 'cpu_cores')}/{_compute_value(allocated, 'cpu_cores')} CPU, "
        f"{_compute_value(used, 'ram_gb')}/{_compute_value(allocated, 'ram_gb')}GB RAM, "
        f"{_compute_int_value(used, 'storage_gb')}/{_compute_int_value(allocated, 'storage_gb')}GB disk, "
        f"{_compute_value(used, 'gpu_gb')}/{_compute_value(allocated, 'gpu_gb')}GB GPU"
    )


def _fmt_project_scope(scope: dict[str, Any] | None) -> list[str]:
    """Format the project-scoped compute block returned for project_id queries."""
    if not scope:
        return []
    lines = [
        f"\n📁 **Project scope: {scope.get('project_name')}**",
        f"Nodes attached to this project: {scope.get('node_count', 0)}",
        (
            "Recorded project allocation: "
            f"{_fmt_usage_over_allocated(scope.get('used'), scope.get('capacity'))}"
            + (" (capacity includes the user's shared reservation)" if scope.get("includes_shared_reservation") else "")
        ),
    ]
    for node in scope.get("nodes") or []:
        kind = "shared" if node.get("is_shared") else "dedicated"
        used = node.get("used_by_project") or {}
        live_free = node.get("live_free")
        live_label = (
            f", live free: {_compute_value(live_free, 'cpu_cores')} CPU / "
            f"{_compute_value(live_free, 'ram_gb')}GB RAM"
            if live_free is not None
            else ", live free: unavailable"
        )
        lines.append(
            f"- {node.get('node_name')} ({kind}, {node.get('status')}): "
            f"{_compute_value(used, 'cpu_cores')} CPU / {_compute_value(used, 'ram_gb')}GB RAM used by this project, "
            f"{len(node.get('apps') or [])} app(s){live_label}"
        )
    return lines


def _fmt_catalog_node(node: dict) -> str:
    if "node_id" in node:
        price = node.get("monthly_price")
        price_label = f"${price}/mo" if price is not None else "price unavailable"
        location = node.get("datacenter_location") or "region pending"
        availability = "available" if node.get("available") else node.get("availability_reason", "unavailable")
        return (
            f"- **{node.get('node_name', 'unnamed')}** (`{node.get('node_id')}`) — {price_label}\n"
            f"  {node.get('cpu', 0)} vCPU, {node.get('ram', 0)}GB RAM, "
            f"{node.get('storage', 0)}GB storage, {node.get('gpu', 0)}GB GPU\n"
            f"  Location: {location} | Status: {availability}"
        )
    hardware = node.get("hardware") or {}
    price = node.get("monthly_price")
    price_label = f"${price}/mo" if price is not None else "price unavailable"
    size = node.get("tshirt_size") or "uncategorized"
    location = node.get("datacenter_location") or "region pending"
    tags = ", ".join(node.get("tags") or []) or "no tags"
    return (
        f"- **{node.get('name', 'unnamed')}** (`{node.get('id')}`) — {price_label}\n"
        f"  {hardware.get('cpu_cores', 0)} vCPU, {hardware.get('ram_gb', 0)}GB RAM, "
        f"{hardware.get('storage_gb', 0)}GB storage, {hardware.get('gpu_gb', 0)}GB GPU\n"
        f"  Size: {size} | Location: {location} | Tags: {tags}"
    )


def _fmt_dedicated_plan(plan: dict) -> str:
    lines = [
        "🧭 **Dedicated Compute Plan**",
        f"Status: {str(plan.get('status', 'unknown')).replace('_', ' ')}",
        f"Can deploy now: {'yes' if plan.get('can_deploy_now') else 'no'}",
        str(plan.get("message") or ""),
    ]
    for item in plan.get("assignments") or []:
        required = item.get("required") or {}
        lines.append(
            f"- {item.get('workload_name')} → {item.get('node_name')} ({item.get('action')}) | "
            f"{_compute_value(required, 'cpu_cores')} CPU, {_compute_value(required, 'ram_gb')}GB RAM, "
            f"{_compute_value(required, 'storage_gb')}GB storage, {_compute_value(required, 'gpu_gb')}GB GPU"
        )
    for item in plan.get("shortages") or []:
        required = item.get("required") or {}
        lines.append(
            f"- Unavailable: {item.get('workload_name')} needs {_compute_value(required, 'cpu_cores')} CPU, "
            f"{_compute_value(required, 'ram_gb')}GB RAM, {_compute_value(required, 'storage_gb')}GB storage, "
            f"and {_compute_value(required, 'gpu_gb')}GB GPU on one machine."
        )
    if plan.get("marketplace_nodes"):
        lines.append(f"Recommended marketplace total: ${float(plan.get('marketplace_monthly_total') or 0):.2f}/month")
    return "\n".join(line for line in lines if line)


def register_compute_tools(mcp):
    # ── Compute / nodes ───────────────────────────────────────────────────────────


    @mcp.tool()
    async def get_compute_summary(project_id: str = "") -> str:
        """Show accessible compute. Pass project_id for a project-scoped view that includes the nodes attached to that project and per-node usage. If the user is still planning capacity, prefer estimate_compute() first, then use the returned offer link to purchase or request the right amount."""
        try:
            data = await _get_compute_summary(project_id=project_id or None)
            counts = data.get("counts", {})
            lines = [
                "🧮 **Compute Summary**",
                f"Can deploy: {'yes' if data.get('can_deploy') else 'no'}",
                f"Message: {data.get('message')}",
                f"Accessible nodes: {counts.get('accessible', 0)} total, {counts.get('ready', 0)} ready",
                f"Personal nodes: {counts.get('personal', 0)} total, {counts.get('personal_ready', 0)} ready",
                f"PlugLayer shared nodes: {counts.get('pluglayer', 0)} total, {counts.get('pluglayer_ready', 0)} ready",
                f"Total available compute: {_fmt_compute(data.get('available_compute'))}",
                f"Total allocated compute: {_fmt_compute(data.get('allocated_compute'))}",
                f"Total used compute: {_fmt_compute(data.get('used_compute'))}",
                (
                    "PlugLayer shared compute usage: "
                    f"{_fmt_usage_over_allocated(data.get('used_shared_compute'), data.get('shared_reserved_compute'))}"
                ),
                f"PlugLayer shared compute available: {_fmt_compute(data.get('available_shared_compute'))}",
                (
                    "Personal compute usage: "
                    f"{_fmt_usage_over_allocated(data.get('used_personal_compute'), data.get('personal_capacity_compute'))}"
                ),
                f"Personal compute available: {_fmt_compute(data.get('available_personal_compute'))}",
            ]
            lines.extend(_fmt_project_scope(data.get("project")))
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
        use_case: str = "",
        components: list[str] | None = None,
        expected_monthly_active_users: int | None = None,
        expected_requests_per_minute: int | None = None,
        project_id: str = "",
    ) -> str:
        """Estimate workload resources, then use the backend-owned dedicated-machine plan. One app must fit wholly on one node; never add undersized machines together. Pass project_id so existing project capacity is reused before any purchase."""
        try:
            if not (use_case or "").strip():
                if components:
                    use_case = f"Workload composed of: {', '.join(components)}."
                else:
                    return (
                        "Please describe the workload first, for example: "
                        "`estimate_compute(use_case='Two backend APIs, one frontend, postgres, and redis for a SaaS app')`."
                    )
            data = await _client().post("/v1/plugin/compute/estimate", {
                "use_case": use_case,
                "project_id": project_id or None,
                "components": components or [],
                "expected_monthly_active_users": expected_monthly_active_users,
                "expected_requests_per_minute": expected_requests_per_minute,
            })
            estimation = data.get("estimation", {})
            nodes = data.get("marketplace_nodes") or []
            if not nodes:
                catalog = await _client().get(
                    "/v1/plugin/compute/catalog",
                    params={
                        "min_cpu_cores": estimation.get("cpu"),
                        "min_ram_gb": estimation.get("ram"),
                        "min_storage_gb": estimation.get("storage"),
                        "min_gpu_gb": estimation.get("gpu"),
                    },
                )
                nodes = catalog.get("nodes", [])
            suggested = nodes[:3]
            lines = [
                "🧠 **Estimated Compute**\n"
                f"CPU: {estimation.get('cpu')} vCPU\n"
                f"RAM: {estimation.get('ram')} GB\n"
                f"GPU: {estimation.get('gpu')} GB\n"
                f"Storage: {estimation.get('storage')} GB\n"
                f"Estimated monthly price: ${data.get('estimated_price_per_month')}\n"
            ]
            plan = data.get("dedicated_plan") or {}
            if plan:
                lines.append("\n" + _fmt_dedicated_plan(plan))
            if suggested and plan.get("marketplace_nodes"):
                lines.append("\nAdequate dedicated machine options right now:")
                lines.extend(_fmt_catalog_node(node) for node in suggested)
                lines.append("\nUse the offer page to recheck availability and confirm the reservation:")
                lines.append(f"Get or confirm your compute here: {data.get('quota_link')}\n")
            elif plan.get("extra_compute_request_available"):
                lines.append("\nNo active marketplace machine can host this app on one node. Ask the user whether to submit an Extra Compute Request, then call request_extra_compute(..., confirm=true).")
            lines.append(data.get("message"))
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error estimating compute", e)


    @mcp.tool()
    async def plan_dedicated_compute(
        workload_name: str,
        cpu_cores: float,
        ram_gb: float,
        storage_gb: float = 1,
        gpu_gb: float = 0,
        project_id: str = "",
        exclude_app_id: str = "",
    ) -> str:
        """Plan one app against project and account dedicated capacity, then active ready-to-buy marketplace machines. Existing capacity is used first. Every CPU/RAM/storage/GPU requirement must fit on one node. For a resize, pass project_id and exclude_app_id so the app's current reservation is replaced instead of counted twice."""
        if cpu_cores <= 0 or ram_gb <= 0 or storage_gb < 0 or gpu_gb < 0:
            return "CPU and RAM must be greater than zero; storage and GPU cannot be negative."
        try:
            data = await _client().post("/v1/plugin/compute/plan", {
                "project_id": project_id or None,
                "exclude_app_id": exclude_app_id or None,
                "workloads": [{
                    "id": "requested-workload",
                    "name": workload_name,
                    "cpu_cores": cpu_cores,
                    "ram_gb": ram_gb,
                    "storage_gb": storage_gb,
                    "gpu_gb": gpu_gb,
                }],
            })
            return _fmt_dedicated_plan(data)
        except Exception as e:
            return _compact_error("Error planning dedicated compute", e)


    @mcp.tool()
    async def request_extra_compute(
        workload_name: str,
        cpu_cores: float,
        ram_gb: float,
        storage_gb: float = 1,
        gpu_gb: float = 0,
        project_id: str = "",
        context: str = "",
        confirm: bool = False,
        exclude_app_id: str = "",
    ) -> str:
        """Submit an Extra Compute Request as authenticated user feedback when no active marketplace machine fits the app. First call plan_dedicated_compute. Set confirm=true only after the user explicitly asks to submit the request."""
        if not confirm:
            return "Confirmation required. Show the unmet one-node requirements, ask the user, then call request_extra_compute(..., confirm=true)."
        try:
            data = await _client().post("/v1/plugin/compute/requests", {
                "project_id": project_id or None,
                "exclude_app_id": exclude_app_id or None,
                "workloads": [{
                    "id": "requested-workload",
                    "name": workload_name,
                    "cpu_cores": cpu_cores,
                    "ram_gb": ram_gb,
                    "storage_gb": storage_gb,
                    "gpu_gb": gpu_gb,
                }],
                "context": context,
                "source": "plugin",
                "confirmed": True,
            })
            feedback = data.get("feedback") or {}
            return (
                "✅ Extra Compute Request submitted.\n"
                f"Ticket: `{feedback.get('id', 'unknown')}`\n"
                f"Status: {feedback.get('status', 'open')}\n"
                "PlugLayer will track it through the normal feedback workflow."
            )
        except Exception as e:
            return _compact_error("Error requesting extra compute", e)


    @mcp.tool()
    async def get_shared_compute_pricing() -> str:
        """Show the admin-defined unit pricing for shared compute reservations plus the currently unreserved shared pool. Read-only: direct the user to the PlugLayer web app (Compute -> Add Compute -> Buy shared compute) to actually purchase a reservation."""
        try:
            data = await _client().get("/v1/plugin/compute/shared/pricing")
            pricing = data.get("pricing") or {}
            pool = data.get("pool_available") or {}
            if not pricing.get("enabled"):
                return (
                    "Shared compute purchasing is not enabled yet. An admin must configure shared pricing "
                    "in Admin -> Compute -> Shared Compute Pricing first."
                )
            currency = pricing.get("currency", "USD")
            return "\n".join(
                [
                    "💳 **Shared Compute Pricing** (monthly)",
                    f"Per CPU core: {currency} {pricing.get('price_per_cpu_core', 0)}",
                    f"Per GB RAM: {currency} {pricing.get('price_per_ram_gb', 0)}",
                    f"Per 10GB storage: {currency} {pricing.get('price_per_storage_10gb', 0)}",
                    f"Per GB GPU: {currency} {pricing.get('price_per_gpu_gb', 0)}",
                    f"Unreserved shared pool right now: {_fmt_compute(pool)}",
                    "Purchase in the PlugLayer app: Compute -> Add Compute -> Buy shared compute.",
                ]
            )
        except Exception as e:
            return _compact_error("Error loading shared compute pricing", e)


    @mcp.tool()
    async def list_nodes(project_id: str = "") -> str:
        """
        List compute nodes accessible to the authenticated user.
        Pass project_id to list only the nodes backing that project (a dedicated
        node serves one project; shared nodes serve many projects at once).
        """
        try:
            params = {"project_id": project_id} if project_id else {}
            data = await _client().get("/v1/plugin/compute/nodes", params=params)
            nodes = data.get("nodes", [])
            if not nodes:
                if project_id:
                    return (
                        f"No compute nodes are attached to project `{project_id}`. "
                        "Call list_attachable_project_nodes(), attach an available node with attach_node_to_project(), "
                        "or help the user add/purchase compute before deploying."
                    )
                return "No accessible compute nodes found yet. If the user needs capacity, prefer estimate_compute() and the PlugLayer compute marketplace before discussing self-managed nodes."
            lines = ["Accessible compute nodes:\n"]
            lines.extend(_fmt_node(n) for n in nodes)
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing compute nodes", e)


    @mcp.tool()
    async def list_attachable_project_nodes(project_id: str) -> str:
        """List the authenticated project owner's dedicated nodes and whether each is available, already attached here, or attached to another project. Use this when project compute is missing before a deploy."""
        try:
            data = await _client().get(f"/v1/plugin/projects/{project_id}/compute/attachable")
            nodes = data.get("nodes") or []
            if not nodes:
                return (
                    f"No dedicated nodes exist for project owner of `{project_id}` yet. "
                    "Help the user estimate and add compute in the PlugLayer web app, then check again."
                )
            lines = [f"Dedicated node attachment options for project `{project_id}`:"]
            for node in nodes:
                state = node.get("attachment_state", "unknown").replace("_", " ")
                project = f" | current project: `{node.get('project_id')}`" if node.get("project_id") else ""
                blocker = node.get("attachment_blocker") or {}
                blocker_text = f" | blocked: {blocker.get('message')}" if blocker.get("message") else ""
                lines.append(f"{_fmt_node(node).rstrip()}   Attachment: {state}{project}{blocker_text}\n")
            lines.append("Only nodes marked available can be attached. A dedicated node can belong to one project at a time.")
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing attachable project nodes", e)


    @mcp.tool()
    async def attach_node_to_project(project_id: str, node_id: str) -> str:
        """Attach one available dedicated node to a project. Owner-only and idempotent. After attaching, call get_compute_summary(project_id) before deploying."""
        try:
            data = await _client().post(f"/v1/plugin/projects/{project_id}/compute/nodes/{node_id}/attach", {})
            node = data.get("node") or {}
            return (
                f"✅ {data.get('message') or 'Node attached.'}\n"
                f"Project: `{project_id}`\nNode: **{node.get('name')}** (`{node.get('id')}`)\n"
                "Next: call get_compute_summary(project_id) and deploy only when it reports enough project-scoped capacity."
            )
        except Exception as e:
            return _compact_error("Error attaching node to project", e)


    @mcp.tool()
    async def detach_node_from_project(project_id: str, node_id: str, confirm: bool = False) -> str:
        """Detach a dedicated node from a project. Active apps block detachment. Set confirm=true only after the user explicitly confirms this change."""
        if not confirm:
            return "Confirmation required. Ask the user, then call detach_node_from_project(..., confirm=true)."
        try:
            data = await _client().delete(f"/v1/plugin/projects/{project_id}/compute/nodes/{node_id}")
            return f"✅ {data.get('message') or 'Node detached.'} Project `{project_id}`, node `{node_id}`."
        except Exception as e:
            return _compact_error("Error detaching node from project", e)


    @mcp.tool()
    async def list_pluglayer_compute_options(
        min_cpu_cores: float = 0,
        min_ram_gb: float = 0,
        min_storage_gb: float = 0,
        min_gpu_gb: float = 0,
        tshirt_size: str = "",
        tags: str = "",
    ) -> str:
        """List PlugLayer marketplace compute options the user can buy. Use this after estimate_compute() when you want real purchasable machine choices instead of abstract resource units."""
        try:
            data = await _client().get(
                "/v1/plugin/compute/catalog",
                params={
                    "min_cpu_cores": min_cpu_cores or None,
                    "min_ram_gb": min_ram_gb or None,
                    "min_storage_gb": min_storage_gb or None,
                    "min_gpu_gb": min_gpu_gb or None,
                    "tshirt_size": tshirt_size or None,
                    "tags": tags or None,
                },
            )
            nodes = data.get("nodes", [])
            if not nodes:
                return "No PlugLayer marketplace compute options match that filter right now."
            lines = ["PlugLayer compute options:\n"]
            lines.extend(_fmt_catalog_node(node) for node in nodes)
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing PlugLayer compute options", e)
