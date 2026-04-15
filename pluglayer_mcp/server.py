"""
PlugLayer MCP Server

Exposes infrastructure management tools to AI assistants via the
Model Context Protocol (MCP). Users configure this with their
PLUGLAYER_API_KEY environment variable.

Run:
    uvx pluglayer-mcp
    # or
    PLUGLAYER_API_KEY=xxx pluglayer-mcp
"""
import sys
from mcp.server.fastmcp import FastMCP
from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.settings import settings

mcp = FastMCP(
    "PlugLayer",
    instructions="""You are the PlugLayer infrastructure operator.
You help users deploy, manage, and monitor their applications on PlugLayer.

Key concepts:
- Projects: isolated namespaces in the k3s cluster (like folders)
- Nodes: VMs that run the workloads (added via SSH or cloud providers)
- Deployments: applications running in a project
- Tasks: async operations — always poll them until complete

Workflow for deploying a new app:
1. List projects or create one if needed
2. Ensure the project has at least one node
3. Deploy the app (from image or docker-compose)
4. Poll the task until complete
5. Return the app URL to the user

Always be proactive about checking status and reporting URLs.
Confirm destructive actions (delete, rollback) before executing.
""",
)


def _client() -> PlugLayerClient:
    return PlugLayerClient(api_key=settings.PLUGLAYER_API_KEY)


# ── Projects ──────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_projects() -> str:
    """List all your PlugLayer projects with their status and app count."""
    try:
        data = await _client().get("/projects")
        if not data:
            return "No projects found. Create one with create_project()."
        lines = ["Your projects:\n"]
        for p in data:
            status_emoji = {"active": "✅", "provisioning": "⏳", "error": "❌"}.get(p.get("status", ""), "❓")
            lines.append(
                f"{status_emoji} **{p['name']}** (id: `{p['id']}`)\n"
                f"   Status: {p['status']} | Apps: {p.get('deployment_count', 0)} | "
                f"Nodes: {len(p.get('node_ids', []))}\n"
                f"   URL pattern: {p.get('base_url', 'N/A')}\n"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing projects: {e}"


@mcp.tool()
async def create_project(
    name: str,
    description: str = "",
    domain_type: str = "pluglayer",
) -> str:
    """
    Create a new PlugLayer project (k3s namespace).

    Args:
        name: Project name (e.g., "my-ecommerce-app")
        description: Optional description
        domain_type: "pluglayer" for *.apps.pluglayer.io or "custom" for your own domain

    Returns task_id to poll for provisioning completion.
    """
    try:
        data = await _client().post("/projects", {
            "name": name,
            "description": description,
            "domain_type": domain_type,
        })
        return (
            f"✅ Project **{name}** created!\n"
            f"Project ID: `{data['project']['id']}`\n"
            f"Namespace: `{data['project']['namespace']}`\n"
            f"Task ID: `{data['task_id']}`\n\n"
            f"⏳ Setting up k3s namespace... Poll `get_task_status('{data['task_id']}')` to check progress."
        )
    except Exception as e:
        return f"Error creating project: {e}"


@mcp.tool()
async def get_project(project_id: str) -> str:
    """Get details of a specific project including apps and nodes."""
    try:
        p = await _client().get(f"/projects/{project_id}")
        status_emoji = {"active": "✅", "provisioning": "⏳", "error": "❌"}.get(p.get("status", ""), "❓")
        return (
            f"{status_emoji} **{p['name']}**\n"
            f"ID: `{p['id']}`\n"
            f"Status: {p['status']}\n"
            f"Namespace: `{p['namespace']}`\n"
            f"URL pattern: {p.get('base_url', 'N/A')}\n"
            f"Apps: {p.get('deployment_count', 0)}\n"
            f"Nodes: {len(p.get('node_ids', []))}"
        )
    except Exception as e:
        return f"Error getting project: {e}"


# ── Nodes ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_nodes(project_id: str = "") -> str:
    """
    List all nodes (VMs) in your cluster.

    Args:
        project_id: Optional — filter by project
    """
    try:
        params = {"project_id": project_id} if project_id else {}
        data = await _client().get("/nodes", params=params)
        if not data:
            return "No nodes found. Add one with add_node_ssh()."
        lines = ["Your nodes:\n"]
        for n in data:
            status_emoji = {
                "ready": "✅", "provisioning": "⚙️", "joining": "🔗",
                "error": "❌", "offline": "💤",
            }.get(n.get("status", ""), "❓")
            hw = n.get("hardware", {})
            hw_str = ""
            if hw.get("cpu_cores"):
                hw_str = f" | {hw['cpu_cores']} CPU, {hw.get('ram_gb', '?')}GB RAM, {hw.get('storage_gb', '?')}GB disk"
            lines.append(
                f"{status_emoji} **{n['name']}** (id: `{n['id']}`)\n"
                f"   Provider: {n['provider']} | Status: {n['status']}{hw_str}\n"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing nodes: {e}"


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
    Add a VM to the cluster via SSH. PlugLayer will:
    1. Test the SSH connection
    2. Install k3s agent
    3. Join the node to the cluster

    Args:
        project_id: The project this node belongs to
        name: Friendly name for this node (e.g., "prod-node-01")
        host: IP address or hostname of the VM
        ssh_private_key: The SSH private key content (-----BEGIN RSA PRIVATE KEY-----)
        user: SSH username (default: root)
        port: SSH port (default: 22)

    Returns task_id — poll get_task_status() to track provisioning.
    """
    try:
        data = await _client().post("/nodes", {
            "project_id": project_id,
            "name": name,
            "provider": "ssh",
            "ssh_host": host,
            "ssh_port": port,
            "ssh_user": user,
            "ssh_private_key": ssh_private_key,
        })
        task_id = data.get("task_id")
        return (
            f"✅ SSH connection verified for {host}!\n"
            f"Node ID: `{data['node']['id']}`\n"
            f"Task ID: `{task_id}`\n\n"
            f"⚙️ Installing k3s agent... This takes 1–3 minutes.\n"
            f"Poll: `get_task_status('{task_id}')` to track progress."
        )
    except Exception as e:
        return f"❌ Failed to add node: {e}"


# ── Deployments ───────────────────────────────────────────────────────────────

@mcp.tool()
async def list_deployments(project_id: str = "") -> str:
    """
    List all deployments (apps) in your projects.

    Args:
        project_id: Optional — filter by project
    """
    try:
        params = {"project_id": project_id} if project_id else {}
        data = await _client().get("/deployments", params=params)
        if not data:
            return "No deployments found. Deploy an app with deploy_image() or deploy_compose()."
        lines = ["Your deployments:\n"]
        for d in data:
            status_emoji = {
                "running": "🕺", "pending": "😴", "deploying": "🚀",
                "failed": "💀", "crash_loop": "🥴", "terminated": "🪦",
            }.get(d.get("status", ""), "❓")
            url = d.get("primary_url", "")
            lines.append(
                f"{status_emoji} **{d['name']}** (id: `{d['id']}`)\n"
                f"   Status: {d['status']} | Image: {d['image']}:{d['tag']}\n"
                f"   URL: {url or 'not yet available'}\n"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing deployments: {e}"


@mcp.tool()
async def deploy_image(
    project_id: str,
    name: str,
    image: str,
    tag: str = "latest",
    ports: list[int] = None,
    env_vars: dict = None,
    replicas: int = 1,
    cpu_limit: str = "500m",
    memory_limit: str = "512Mi",
) -> str:
    """
    Deploy a Docker image as an app in a project.

    Args:
        project_id: The project to deploy into
        name: App name (e.g., "my-api")
        image: Docker image (e.g., "nginx", "ghcr.io/myorg/myapp")
        tag: Image tag (default: "latest")
        ports: List of ports to expose (e.g., [8000, 3000])
        env_vars: Environment variables dict (e.g., {"DATABASE_URL": "postgres://..."})
        replicas: Number of replicas (default: 1)
        cpu_limit: CPU limit (default: "500m" = 0.5 CPU)
        memory_limit: Memory limit (default: "512Mi")

    Returns task_id — poll get_task_status() to track deployment.
    """
    try:
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
            f"🚀 Deployment queued!\n"
            f"App: **{name}** (id: `{dep.get('id')}`)\n"
            f"Image: `{image}:{tag}`\n"
            f"Task ID: `{task_id}`\n\n"
            f"⏳ Deploying to k3s... Poll: `get_task_status('{task_id}')`"
        )
    except Exception as e:
        return f"❌ Deployment failed: {e}"


@mcp.tool()
async def deploy_compose(
    project_id: str,
    compose_yaml: str,
    app_name: str = "",
) -> str:
    """
    Deploy a docker-compose.yml to a project. PlugLayer converts it to k8s manifests automatically.

    Args:
        project_id: The project to deploy into
        compose_yaml: The full content of your docker-compose.yml file
        app_name: Optional name override for this deployment group

    Returns task_id — poll get_task_status() to track deployment.
    """
    try:
        data = await _client().post("/deployments/from-compose", {
            "project_id": project_id,
            "compose_yaml": compose_yaml,
            "app_name": app_name or None,
        })
        task_id = data.get("task_id")
        dep = data.get("deployment", {})
        return (
            f"🚀 Compose deployment queued!\n"
            f"Deployment ID: `{dep.get('id')}`\n"
            f"Task ID: `{task_id}`\n\n"
            f"⏳ Converting compose → k8s manifests and deploying...\n"
            f"Poll: `get_task_status('{task_id}')`"
        )
    except Exception as e:
        return f"❌ Compose deployment failed: {e}"


@mcp.tool()
async def get_deployment_status(deployment_id: str) -> str:
    """Get the current status and URL of a deployment."""
    try:
        d = await _client().get(f"/deployments/{deployment_id}/status")
        status_emoji = {
            "running": "🕺", "pending": "😴", "deploying": "🚀",
            "failed": "💀", "crash_loop": "🥴", "terminated": "🪦",
        }.get(str(d.get("db_status", "")), "❓")

        k8s = d.get("k8s_status", {}) or {}
        result = (
            f"{status_emoji} **Deployment Status**\n"
            f"Status: {d.get('db_status')}\n"
            f"URL: {d.get('primary_url') or 'not yet available'}\n"
        )
        if k8s:
            result += f"Replicas: {k8s.get('ready_replicas', 0)}/{k8s.get('replicas', 0)} ready\n"
        return result
    except Exception as e:
        return f"Error getting deployment status: {e}"


@mcp.tool()
async def get_logs(deployment_id: str, lines: int = 100) -> str:
    """
    Get recent logs from a deployment.

    Args:
        deployment_id: The deployment ID
        lines: Number of log lines to retrieve (default: 100)
    """
    try:
        data = await _client().get(f"/deployments/{deployment_id}/logs", params={"lines": lines})
        logs = data.get("logs", "No logs available")
        return f"📋 **Logs** (last {lines} lines):\n\n```\n{logs}\n```"
    except Exception as e:
        return f"Error getting logs: {e}"


@mcp.tool()
async def redeploy(deployment_id: str) -> str:
    """
    Redeploy an existing deployment (re-pull image and restart pods).

    Args:
        deployment_id: The deployment ID to redeploy
    """
    try:
        data = await _client().post(f"/deployments/{deployment_id}/redeploy")
        task_id = data.get("task_id")
        return f"🔄 Redeployment queued! Task ID: `{task_id}`\nPoll: `get_task_status('{task_id}')`"
    except Exception as e:
        return f"Error triggering redeploy: {e}"


@mcp.tool()
async def rollback(deployment_id: str, revision: int = None) -> str:
    """
    Roll back a deployment to a previous version.

    Args:
        deployment_id: The deployment ID
        revision: Specific revision number to roll back to (optional — defaults to previous)
    """
    try:
        params = {"revision": revision} if revision else {}
        data = await _client().post(f"/deployments/{deployment_id}/rollback", params)
        task_id = data.get("task_id")
        rev = data.get("rolled_back_to", {})
        return (
            f"⏪ Rollback queued!\n"
            f"Rolling back to: `{rev.get('image')}:{rev.get('tag')}` (revision {rev.get('revision')})\n"
            f"Task ID: `{task_id}`\n"
            f"Poll: `get_task_status('{task_id}')`"
        )
    except Exception as e:
        return f"Error triggering rollback: {e}"


@mcp.tool()
async def delete_deployment(deployment_id: str) -> str:
    """
    DESTRUCTIVE: Delete a deployment and remove it from k3s.
    This will stop the app and remove its ingress. Cannot be undone.

    Args:
        deployment_id: The deployment ID to delete
    """
    try:
        await _client().delete(f"/deployments/{deployment_id}")
        return f"🗑️ Deployment `{deployment_id}` deleted and removed from cluster."
    except Exception as e:
        return f"Error deleting deployment: {e}"


# ── Tasks ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_task_status(task_id: str) -> str:
    """
    Check the status of an async operation (provisioning, deployment, etc.)

    Args:
        task_id: The task ID returned from any async operation

    Returns current status, progress percentage, and result when complete.
    """
    try:
        t = await _client().get(f"/tasks/{task_id}")
        status_emoji = {
            "queued": "⏳", "in_progress": "⚙️",
            "completed": "✅", "failed": "❌", "cancelled": "🚫",
        }.get(t.get("status", ""), "❓")

        progress = t.get("progress", {})
        pct = progress.get("percentage", 0)
        msg = progress.get("message", "")
        step = progress.get("step", 0)
        total = progress.get("total_steps", 0)

        result_str = ""
        if t.get("result"):
            result = t["result"]
            if result.get("primary_url"):
                result_str = f"\n🌐 App URL: {result['primary_url']}"
            elif result.get("k3s_node_name"):
                result_str = f"\n🖥️ Node joined as: {result['k3s_node_name']}"

        error_str = ""
        if t.get("error_message"):
            error_str = f"\n❌ Error: {t['error_message']}"

        return (
            f"{status_emoji} **Task {t.get('type', '')}**\n"
            f"Status: {t['status']}\n"
            f"Progress: {round(pct)}% — {msg}\n"
            f"Steps: {step}/{total}"
            f"{result_str}{error_str}"
        )
    except Exception as e:
        return f"Error getting task: {e}"


# ── CI/CD ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def generate_github_actions(
    project_id: str,
    deployment_id: str,
    github_org: str = "your-org",
) -> str:
    """
    Generate a GitHub Actions workflow YAML for CI/CD.
    Automatically builds and pushes your Docker image, then deploys to PlugLayer.

    Args:
        project_id: Your project ID
        deployment_id: The deployment to update on each push
        github_org: Your GitHub organization or username

    Returns the workflow YAML to save as .github/workflows/deploy.yml
    """
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
            f"**Setup steps:**\n"
            f"1. Create this file in your repo\n"
            f"2. Add `PLUGLAYER_API_KEY` secret in GitHub repo settings\n"
            f"3. Push to main/master to trigger a deploy!"
        )
    except Exception as e:
        return f"Error generating pipeline: {e}"


# ── Utility ───────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_cluster_health() -> str:
    """Check the health of your PlugLayer cluster (k3s nodes, API status)."""
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
        return f"Cluster health check failed: {e}"


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

    # Run as HTTP transport for remote MCP
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
