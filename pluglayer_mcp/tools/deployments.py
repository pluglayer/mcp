"""Deployment/app MCP tools backed by PlugLayer v1 apps API."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_task_hint, _get_compute_summary, _status_emoji


def register_deployment_tools(mcp):
    @mcp.tool()
    async def list_registries() -> str:
        """List registry destinations available to the current user."""
        try:
            data = await _client().get("/v1/plugin/registries")
            registries = data.get("registries", [])
            if not registries:
                return "No registries are available to you yet. Ask an admin to configure a system or personal registry first."
            lines = ["Available registries:\n"]
            for registry in registries:
                lines.append(
                    f"- **{registry.get('name')}** (`{registry.get('id')}`)\n"
                    f"  Provider: {registry.get('provider')} | Scope: {registry.get('scope')} | Namespace: {registry.get('namespace')}\n"
                    f"  Last test: {registry.get('last_test', {}).get('message') or 'unknown'}\n"
                )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing registries", e)

    @mcp.tool()
    async def list_deployments(project_id: str = "") -> str:
        """List apps. Optionally filter by project_id."""
        try:
            params = {"project_id": project_id} if project_id else {}
            data = await _client().get("/v1/plugin/apps", params=params)
            apps = data.get("apps", [])
            if not apps:
                return "No apps found. Deploy one with deploy_image() or deploy_compose()."
            lines = ["Your apps:\n"]
            for app in apps:
                status = app.get("status", "unknown")
                image = app.get("image") or "compose"
                tag = app.get("tag") or ""
                lines.append(
                    f"{_status_emoji(status)} **{app.get('name')}** (id: `{app.get('id')}`)\n"
                    f"   Status: {status} | Source: {app.get('source_type', 'image')} | Image: {image}:{tag}\n"
                    f"   URL: {app.get('primary_url') or 'not yet available'}\n"
                )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing apps", e)

    @mcp.tool()
    async def deploy_image(
        project_id: str,
        name: str,
        image: str,
        tag: str = "latest",
        ports: list[int] | None = None,
        env_vars: dict[str, str] | None = None,
        replicas: int = 1,
        route_slug: str = "",
        cpu_limit: str = "500m",
        memory_limit: str = "512Mi",
        compute_placement: str = "auto",
        push_to_pluglayer_registry: bool = True,
        registry_id: str = "",
    ) -> str:
        """Deploy a Docker image into a project. By default, mirror it into PlugLayer's managed registry first."""
        try:
            compute = await _get_compute_summary()
            if not compute.get("can_deploy"):
                return f"Cannot deploy yet: {compute.get('message')}"
            payload = {
                "name": name,
                "route_slug": route_slug or None,
                "compute_placement": compute_placement,
                "registry_id": registry_id or None,
                "source": {
                    "type": "image",
                    "image": image,
                    "tag": tag,
                    "ports": ports or [],
                    "env_vars": env_vars or {},
                    "replicas": replicas,
                    "cpu_limit": cpu_limit,
                    "memory_limit": memory_limit,
                },
            }
            endpoint = (
                f"/v1/plugin/projects/{project_id}/apps/push-image"
                if push_to_pluglayer_registry
                else f"/v1/plugin/projects/{project_id}/apps"
            )
            data = await _client().post(endpoint, payload)
            task_id = data.get("task_id")
            app = data.get("app", {})
            mirrored = data.get("mirrored_image")
            lines = [f"🚀 App queued: **{name}** (id: `{app.get('id')}`). Task ID: `{task_id}`"]
            if mirrored:
                lines.append(f"Mirrored image: `{mirrored}`")
            lines.append(_fmt_task_hint(task_id))
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Deployment failed", e)

    @mcp.tool()
    async def deploy_compose(
        project_id: str,
        compose_yaml: str,
        app_name: str = "",
        route_slug: str = "",
        compute_placement: str = "auto",
    ) -> str:
        """Deploy docker-compose.yml into a project."""
        try:
            compute = await _get_compute_summary()
            if not compute.get("can_deploy"):
                return f"Cannot deploy yet: {compute.get('message')}"
            data = await _client().post(f"/v1/plugin/projects/{project_id}/apps", {
                "name": app_name or "compose-app",
                "route_slug": route_slug or None,
                "compute_placement": compute_placement,
                "source": {"type": "compose", "compose_yaml": compose_yaml},
            })
            task_id = data.get("task_id")
            app = data.get("app", {})
            return f"🚀 Compose app queued (id: `{app.get('id')}`). Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        except Exception as e:
            return _compact_error("Compose deployment failed", e)

    @mcp.tool()
    async def get_deployment_status(deployment_id: str) -> str:
        """Get current app/deployment status and public URL."""
        try:
            data = await _client().get(f"/v1/plugin/apps/{deployment_id}/status")
            app = data.get("app", {})
            k8s = (data.get("runtime") or {}).get("k8s_status") or {}
            status = app.get("status", "unknown")
            result = f"{_status_emoji(status)} **App Status**\nStatus: {status}\nURL: {app.get('primary_url') or 'not yet available'}\n"
            if k8s:
                result += f"Replicas: {k8s.get('ready_replicas', 0)}/{k8s.get('replicas', 0)} ready\n"
            return result
        except Exception as e:
            return _compact_error("Error getting app status", e)

    @mcp.tool()
    async def get_logs(deployment_id: str, lines: int = 100) -> str:
        """Get recent logs from an app."""
        try:
            data = await _client().get(f"/v1/plugin/apps/{deployment_id}/logs", params={"tail": lines})
            return f"📋 **Logs** (last {lines} lines):\n\n```\n{data.get('logs', 'No logs available')}\n```"
        except Exception as e:
            return _compact_error("Error getting logs", e)

    @mcp.tool()
    async def redeploy(deployment_id: str) -> str:
        """Redeploy an existing app."""
        try:
            data = await _client().post(f"/v1/plugin/apps/{deployment_id}/redeploy")
            task_id = data.get("task_id")
            return f"🔄 Redeployment queued. Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        except Exception as e:
            return _compact_error("Error triggering redeploy", e)

    @mcp.tool()
    async def rollback(deployment_id: str, revision: int | None = None) -> str:
        """Roll back an app to a previous revision."""
        try:
            params = {"revision": revision} if revision else {}
            data = await _client().post(f"/v1/plugin/apps/{deployment_id}/rollback", params=params)
            task_id = data.get("task_id")
            return f"⏪ Rollback queued. Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        except Exception as e:
            return _compact_error("Error triggering rollback", e)

    @mcp.tool()
    async def delete_deployment(deployment_id: str) -> str:
        """DESTRUCTIVE: delete an app and remove it from k3s."""
        try:
            await _client().delete(f"/v1/plugin/apps/{deployment_id}")
            return f"🗑️ App `{deployment_id}` deleted and removed from cluster."
        except Exception as e:
            return _compact_error("Error deleting app", e)
