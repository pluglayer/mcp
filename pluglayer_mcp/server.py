"""
PlugLayer MCP Server

Exposes PlugLayer project, compute, deployment, CI/CD, and admin tools to AI
assistants through the Model Context Protocol (MCP). The MCP intentionally goes
through the FastAPI backend endpoints so auth, roles, ownership, quotas, compute
checks, k3s orchestration, and admin guards stay in one backend implementation.
"""
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.settings import settings

mcp = FastMCP(
    "PlugLayer",
    instructions="""You are the PlugLayer infrastructure operator.
You help users deploy, manage, and monitor applications on PlugLayer.

Current PlugLayer rules:
- Authentik groups are exposed by PlugLayer as user.roles. Do not use groups/permissions fields.
- Admin tools require the user to have pluglayer-admin or pluglayer-superadmin in roles.
- Compute is account-level: personal SSH nodes and shared PlugLayer nodes can be used by all projects the user owns.
- A project is a k3s namespace. A deployment is an app inside a project.
- Async operations return task IDs; always poll get_task_status until completion.

Deployment workflow:
1. Run get_current_user and get_compute_summary.
2. List or create a project.
3. Ensure can_deploy is true. If false, add a personal SSH node or ask an admin to assign shared compute.
4. Deploy from image or docker-compose.
5. Poll the returned task and report the public URL.

Confirm destructive actions such as delete and rollback before executing them.
""",
)


# ── Shared helpers ────────────────────────────────────────────────────────────


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
    return await _client().get("/nodes/compute/summary")


# ── Identity / roles ─────────────────────────────────────────────────────────


@mcp.tool()
async def get_current_user() -> str:
    """Show the authenticated PlugLayer user and roles from Authentik."""
    try:
        user = await _client().get("/auth/me")
        roles = user.get("roles") or []
        return (
            "👤 **Current PlugLayer user**\n"
            f"Email: {user.get('email')}\n"
            f"Username: {user.get('username')}\n"
            f"Roles: {', '.join(roles) if roles else 'none'}\n"
            f"Superadmin: {'yes' if user.get('is_superuser') else 'no'}"
        )
    except Exception as e:
        return _compact_error("Error loading current user", e)


# ── Projects ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_projects() -> str:
    """List authenticated user's projects. Normal users see their projects; admins may see admin data via admin tools."""
    try:
        data = await _client().get("/projects")
        if not data:
            return "No projects found. Create one with create_project()."
        lines = ["Your projects:\n"]
        for p in data:
            status = p.get("status", "unknown")
            lines.append(
                f"{_status_emoji(status)} **{p.get('name')}** (id: `{p.get('id')}`)\n"
                f"   Status: {status} | Apps: {p.get('deployment_count', 0)}\n"
                f"   Namespace: `{p.get('namespace')}`\n"
                f"   URL pattern: {p.get('base_url', 'N/A')}\n"
            )
        return "\n".join(lines)
    except Exception as e:
        return _compact_error("Error listing projects", e)


@mcp.tool()
async def create_project(name: str, description: str = "", domain_type: str = "pluglayer") -> str:
    """
    Create a PlugLayer project namespace. Project creation only requires authentication.
    Deployment still requires account-level compute; check get_compute_summary before deploying.
    """
    try:
        data = await _client().post("/projects", {
            "name": name,
            "description": description,
            "domain_type": domain_type,
        })
        project = data.get("project", {})
        task_id = data.get("task_id")
        return (
            f"✅ Project **{project.get('name', name)}** created.\n"
            f"Project ID: `{project.get('id')}`\n"
            f"Namespace: `{project.get('namespace')}`\n"
            f"Task ID: `{task_id}`\n\n"
            f"⏳ Setting up namespace. {_fmt_task_hint(task_id)}"
        )
    except Exception as e:
        return _compact_error("Error creating project", e)


@mcp.tool()
async def get_project(project_id: str) -> str:
    """Get project details. Accessible to the project owner or a PlugLayer admin role."""
    try:
        p = await _client().get(f"/projects/{project_id}")
        status = p.get("status", "unknown")
        return (
            f"{_status_emoji(status)} **{p.get('name')}**\n"
            f"ID: `{p.get('id')}`\n"
            f"Status: {status}\n"
            f"Namespace: `{p.get('namespace')}`\n"
            f"URL pattern: {p.get('base_url', 'N/A')}\n"
            f"Apps: {p.get('deployment_count', 0)}\n"
            "Compute is account-level; use get_compute_summary() for available capacity."
        )
    except Exception as e:
        return _compact_error("Error getting project", e)


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
        data = await _client().get("/nodes", params=params)
        if not data:
            return "No accessible compute nodes found. Add one with add_node_ssh(), or ask an admin to assign shared compute."
        lines = ["Accessible compute nodes:\n"]
        lines.extend(_fmt_node(n) for n in data)
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
        data = await _client().post("/nodes", payload)
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


# ── Deployments ───────────────────────────────────────────────────────────────


@mcp.tool()
async def list_deployments(project_id: str = "") -> str:
    """List deployments/apps. Optionally filter by project_id."""
    try:
        params = {"project_id": project_id} if project_id else {}
        data = await _client().get("/deployments", params=params)
        if not data:
            return "No deployments found. Deploy an app with deploy_image() or deploy_compose()."
        lines = ["Your deployments:\n"]
        for d in data:
            status = d.get("status", "unknown")
            image = d.get("image") or "compose"
            tag = d.get("tag") or ""
            image_ref = f"{image}:{tag}" if tag else image
            lines.append(
                f"{_status_emoji(status)} **{d.get('name')}** (id: `{d.get('id')}`)\n"
                f"   Status: {status} | Source: {d.get('source_type', 'image')} | Image: {image_ref}\n"
                f"   URL: {d.get('primary_url') or 'not yet available'}\n"
            )
        return "\n".join(lines)
    except Exception as e:
        return _compact_error("Error listing deployments", e)


@mcp.tool()
async def deploy_image(
    project_id: str,
    name: str,
    image: str,
    tag: str = "latest",
    ports: list[int] | None = None,
    env_vars: dict[str, str] | None = None,
    replicas: int = 1,
    cpu_limit: str = "500m",
    memory_limit: str = "512Mi",
) -> str:
    """
    Deploy a Docker image into a project. Requires authentication, project ownership, and schedulable compute.
    Run get_compute_summary first if you are unsure compute is available.
    """
    try:
        compute = await _get_compute_summary()
        if not compute.get("can_deploy"):
            return f"Cannot deploy yet: {compute.get('message')}\nAdd personal compute with add_node_ssh(), or ask an admin for shared PlugLayer compute."

        data = await _client().post("/deployments/from-image", {
            "project_id": project_id,
            "name": name,
            "image": image,
            "tag": tag,
            "ports": ports or [],
            "env_vars": env_vars or {},
            "replicas": replicas,
            "cpu_limit": cpu_limit,
            "memory_limit": memory_limit,
        })
        task_id = data.get("task_id")
        dep = data.get("deployment", {})
        return (
            f"🚀 Deployment queued.\n"
            f"App: **{name}** (id: `{dep.get('id')}`)\n"
            f"Image: `{image}:{tag}`\n"
            f"Task ID: `{task_id}`\n\n"
            f"⏳ Deploying to k3s. {_fmt_task_hint(task_id)}"
        )
    except Exception as e:
        return _compact_error("Deployment failed", e)


@mcp.tool()
async def deploy_compose(project_id: str, compose_yaml: str, app_name: str = "") -> str:
    """Deploy docker-compose.yml into a project. Requires schedulable compute; PlugLayer converts compose to k8s manifests."""
    try:
        compute = await _get_compute_summary()
        if not compute.get("can_deploy"):
            return f"Cannot deploy yet: {compute.get('message')}\nAdd personal compute with add_node_ssh(), or ask an admin for shared PlugLayer compute."

        data = await _client().post("/deployments/from-compose", {
            "project_id": project_id,
            "compose_yaml": compose_yaml,
            "app_name": app_name or None,
        })
        task_id = data.get("task_id")
        dep = data.get("deployment", {})
        return (
            f"🚀 Compose deployment queued.\n"
            f"Deployment ID: `{dep.get('id')}`\n"
            f"Task ID: `{task_id}`\n\n"
            f"⏳ Converting compose to k8s and deploying. {_fmt_task_hint(task_id)}"
        )
    except Exception as e:
        return _compact_error("Compose deployment failed", e)


@mcp.tool()
async def get_deployment_status(deployment_id: str) -> str:
    """Get the current deployment status, k8s replica state, and public URL."""
    try:
        d = await _client().get(f"/deployments/{deployment_id}/status")
        status = d.get("db_status", "unknown")
        k8s = d.get("k8s_status", {}) or {}
        result = (
            f"{_status_emoji(status)} **Deployment Status**\n"
            f"Status: {status}\n"
            f"URL: {d.get('primary_url') or 'not yet available'}\n"
        )
        if k8s:
            result += f"Replicas: {k8s.get('ready_replicas', 0)}/{k8s.get('replicas', 0)} ready\n"
        return result
    except Exception as e:
        return _compact_error("Error getting deployment status", e)


@mcp.tool()
async def get_logs(deployment_id: str, lines: int = 100) -> str:
    """Get recent logs from a deployment."""
    try:
        data = await _client().get(f"/deployments/{deployment_id}/logs", params={"lines": lines})
        logs = data.get("logs", "No logs available")
        return f"📋 **Logs** (last {lines} lines):\n\n```\n{logs}\n```"
    except Exception as e:
        return _compact_error("Error getting logs", e)


@mcp.tool()
async def redeploy(deployment_id: str) -> str:
    """Redeploy an existing deployment. Requires owner/admin access and schedulable compute."""
    try:
        data = await _client().post(f"/deployments/{deployment_id}/redeploy")
        task_id = data.get("task_id")
        return f"🔄 Redeployment queued. Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
    except Exception as e:
        return _compact_error("Error triggering redeploy", e)


@mcp.tool()
async def rollback(deployment_id: str, revision: int | None = None) -> str:
    """Roll back a deployment to a previous revision. Confirm with the user before calling."""
    try:
        params = {"revision": revision} if revision else {}
        data = await _client().post(f"/deployments/{deployment_id}/rollback", params=params)
        task_id = data.get("task_id")
        rev = data.get("rolled_back_to", {})
        return (
            f"⏪ Rollback queued.\n"
            f"Rolling back to: `{rev.get('image')}:{rev.get('tag')}` (revision {rev.get('revision')})\n"
            f"Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        )
    except Exception as e:
        return _compact_error("Error triggering rollback", e)


@mcp.tool()
async def delete_deployment(deployment_id: str) -> str:
    """DESTRUCTIVE: Delete a deployment and remove it from k3s. Confirm with the user before calling."""
    try:
        await _client().delete(f"/deployments/{deployment_id}")
        return f"🗑️ Deployment `{deployment_id}` deleted and removed from cluster."
    except Exception as e:
        return _compact_error("Error deleting deployment", e)


# ── Tasks ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def get_task_status(task_id: str) -> str:
    """Check async operation status, progress, result URL, or error."""
    try:
        t = await _client().get(f"/tasks/{task_id}")
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
        error_str = f"\n❌ Error: {t['error_message']}" if t.get("error_message") else ""
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
        tasks = await _client().get("/admin/tasks", params={"limit": 10})
        events = await _client().get("/admin/capacity-events", params={"limit": 10})
        nodes = await _client().get("/admin/nodes")
        compute = await _client().get("/admin/compute/settings")
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
        await _client().put("/admin/compute/settings", {
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
        data = await _client().patch(f"/admin/nodes/{node_id}/sharing", {"is_shared": is_shared})
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
        data = await _client().post("/admin/nodes/ssh", {
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


# ── CI/CD ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def generate_github_actions(project_id: str, deployment_id: str, github_org: str = "your-org") -> str:
    """Generate a GitHub Actions workflow YAML for PlugLayer CI/CD."""
    try:
        data = await _client().get("/cicd/generate/github-actions", params={
            "project_id": project_id,
            "deployment_id": deployment_id,
            "repo": github_org,
        })
        workflow = data.get("workflow_yaml", "")
        filename = data.get("filename", ".github/workflows/deploy-pluglayer.yml")
        return (
            f"📋 **GitHub Actions Workflow**\n"
            f"Save as: `{filename}`\n\n"
            f"```yaml\n{workflow}\n```\n\n"
            "Setup steps:\n"
            "1. Create this file in your repo.\n"
            "2. Add `PLUGLAYER_API_KEY` as a GitHub secret.\n"
            "3. Push to main/master to trigger deploys."
        )
    except Exception as e:
        return _compact_error("Error generating pipeline", e)


# ── Utility ───────────────────────────────────────────────────────────────────


@mcp.tool()
async def get_cluster_health() -> str:
    """Check PlugLayer API and k3s health."""
    try:
        health = await _client().get("/health")
        k3s = await _client().get("/health/k3s")
        api_emoji = "✅" if health.get("api") == "ok" else "❌"
        db_emoji = "✅" if health.get("mongodb") == "ok" else "❌"
        node_count = len(k3s.get("node_list", []))
        k3s_status = k3s.get("k3s", "unknown")
        k3s_emoji = "✅" if k3s_status == "ok" else "❌"
        return (
            f"🏥 **Cluster Health**\n"
            f"{api_emoji} API: {health.get('api', 'unknown')}\n"
            f"{db_emoji} Database: {health.get('mongodb', 'unknown')}\n"
            f"{k3s_emoji} k3s: {k3s_status} ({node_count} nodes)\n"
        )
    except Exception as e:
        return _compact_error("Cluster health check failed", e)


def main():
    """Entry point for `pluglayer-mcp` command."""
    if not settings.PLUGLAYER_API_KEY:
        print(
            "WARNING: PLUGLAYER_API_KEY not set!\n"
            "Set it as an environment variable:\n"
            "  PLUGLAYER_API_KEY=your-token pluglayer-mcp\n\n"
            "Get your token from: https://portal.pluglayer.com/settings",
            file=sys.stderr,
        )

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
