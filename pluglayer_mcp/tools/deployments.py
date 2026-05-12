"""Deployment/app MCP tools backed by PlugLayer v1 apps API."""

import json
import os

from pluglayer_mcp.tools.shared import (
    _client,
    _compact_error,
    _fmt_task_hint,
    _get_compute_summary,
    _remember_context,
    _status_emoji,
)


def _looks_like_public_docker_hub_image(image: str) -> bool:
    candidate = (image or "").strip().lower()
    if not candidate:
        return False
    first = candidate.split("/", 1)[0]
    if "." in first or ":" in first:
        return first in {"docker.io", "index.docker.io", "registry-1.docker.io"}
    return True


def _post_deploy_suggestions(app: dict, project_apps: list[dict]) -> list[str]:
    others = [item for item in project_apps if item.get("id") != app.get("id")]
    if not others:
        return []
    app_name = app.get("name") or "this app"
    app_type = app.get("character_type") or ""
    suggestions: list[str] = []
    if app_type == "database":
        for other in others:
            suggestions.append(
                f"- Your database is deployed as **{app_name}**. Do you want me to update **{other.get('name') or 'another app'}** with the new connection string env vars?"
            )
            break
    elif app_type in {"api", "worker"}:
        for other in others:
            if (other.get("character_type") or "") == "web":
                suggestions.append(
                    f"- Your backend is deployed as **{app_name}**. Do you want me to update **{other.get('name') or 'frontend'}** with the deployed API URL env var?"
                )
                break
    elif app_type == "web":
        for other in others:
            if (other.get("character_type") or "") in {"api", "worker"}:
                suggestions.append(
                    f"- Your frontend is deployed as **{app_name}**. Do you want me to update its env vars so it points at **{other.get('name') or 'backend'}** correctly?"
                )
                break
    return suggestions


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
                return "No apps found. Deploy one with deploy_image(), upload_image_archive_and_deploy(), or deploy_compose()."
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
    async def get_apps_by_project(project_id: str) -> str:
        """List apps for a specific project. Use this before a new deploy when the project may already contain the same app and you need to clarify update vs replace vs separate new app. If the project already has a similar app and the namespace is full, prefer update or replace flow instead of a brand-new app."""
        try:
            data = await _client().get(f"/v1/plugin/projects/{project_id}/apps")
            apps = data.get("apps", [])
            if not apps:
                return f"No apps found in project `{project_id}` yet."
            lines = [f"Apps in project `{project_id}`:\n"]
            for app in apps:
                status = app.get("status", "unknown")
                lines.append(
                    f"{_status_emoji(status)} **{app.get('name')}** (id: `{app.get('id')}`)\n"
                    f"   Status: {status} | URL: {app.get('primary_url') or 'not yet available'}\n"
                )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing project apps", e)

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
        compute_placement: str = "personal",
        push_to_pluglayer_registry: bool = True,
        registry_id: str = "",
    ) -> str:
        """Deploy a pullable Docker image into a project. By default, mirror it into an allowed managed registry first, except for obvious public Docker Hub images such as common databases where direct pull is usually better. For a local-only image built on the user's machine, use upload_image_archive_and_deploy() instead."""
        try:
            compute = await _get_compute_summary()
            if not compute.get("can_deploy"):
                return f"Cannot deploy yet: {compute.get('message')}"
            should_mirror = push_to_pluglayer_registry and not _looks_like_public_docker_hub_image(image)
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
                if should_mirror
                else f"/v1/plugin/projects/{project_id}/apps"
            )
            data = await _client().post(endpoint, payload)
            task_id = data.get("task_id")
            app = data.get("app", {})
            mirrored = data.get("mirrored_image")
            project_apps = (await _client().get(f"/v1/plugin/projects/{project_id}/apps")).get("apps", [])
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "deploy_image",
                        "project_id": project_id,
                        "app_id": app.get("id"),
                        "app_name": app.get("name") or name,
                        "route_slug": app.get("route_slug") or route_slug or name,
                    },
                    "projects": {
                        project_id: {
                            "last_app_id": app.get("id"),
                            "last_app_name": app.get("name") or name,
                        }
                    },
                }
            )
            lines = [f"🚀 App queued: **{name}** (id: `{app.get('id')}`). Task ID: `{task_id}`"]
            if mirrored:
                lines.append(f"Mirrored image: `{mirrored}`")
            elif _looks_like_public_docker_hub_image(image):
                lines.append("Using the public image directly, so no mirror push was needed.")
            lines.append("This usually takes around 10 minutes. Feel free to keep working and ask me to check status later.")
            lines.append(_fmt_task_hint(task_id))
            lines.extend(_post_deploy_suggestions(app, project_apps))
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Deployment failed", e)

    @mcp.tool()
    async def upload_image_archive_and_deploy(
        project_id: str,
        name: str,
        image_archive_path: str,
        tag: str = "latest",
        ports: list[int] | None = None,
        env_vars: dict[str, str] | None = None,
        replicas: int = 1,
        route_slug: str = "",
        cpu_limit: str = "500m",
        memory_limit: str = "512Mi",
        compute_placement: str = "personal",
        registry_id: str = "",
    ) -> str:
        """Upload a locally built Docker image archive (for example from `docker save`) to PlugLayer, push it into an allowed configured registry, and deploy from the mirrored image."""
        try:
            if not os.path.exists(image_archive_path):
                return f"Image archive not found: {image_archive_path}"
            compute = await _get_compute_summary()
            if not compute.get("can_deploy"):
                return f"Cannot deploy yet: {compute.get('message')}"
            form_data = {
                "name": name,
                "tag": tag,
                "route_slug": route_slug or "",
                "compute_placement": compute_placement,
                "registry_id": registry_id or "",
                "ports_json": json.dumps(ports or []),
                "env_vars_json": json.dumps(env_vars or {}),
                "replicas": str(replicas),
                "cpu_limit": cpu_limit,
                "memory_limit": memory_limit,
            }
            data = await _client().post_multipart(
                f"/v1/plugin/projects/{project_id}/apps/upload-image",
                form_data=form_data,
                file_field="archive",
                file_path=image_archive_path,
                content_type="application/x-tar",
            )
            task_id = data.get("task_id")
            app = data.get("app", {})
            mirrored = data.get("mirrored_image")
            project_apps = (await _client().get(f"/v1/plugin/projects/{project_id}/apps")).get("apps", [])
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "upload_image_archive_and_deploy",
                        "project_id": project_id,
                        "app_id": app.get("id"),
                        "app_name": app.get("name") or name,
                        "route_slug": app.get("route_slug") or route_slug or name,
                    }
                }
            )
            lines = [f"🚀 Uploaded image app queued: **{name}** (id: `{app.get('id')}`). Task ID: `{task_id}`"]
            if mirrored:
                lines.append(f"Mirrored image: `{mirrored}`")
            lines.append("This usually takes around 10 minutes. Feel free to keep working and ask me to check status later.")
            lines.append(_fmt_task_hint(task_id))
            lines.extend(_post_deploy_suggestions(app, project_apps))
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Uploaded image deployment failed", e)

    @mcp.tool()
    async def deploy_compose(
        project_id: str,
        compose_yaml: str,
        app_name: str = "",
        route_slug: str = "",
        compute_placement: str = "personal",
    ) -> str:
        """Deploy docker-compose.yml into a project. Use this when multiple services should run together."""
        try:
            compute = await _get_compute_summary()
            if not compute.get("can_deploy"):
                return f"Cannot deploy yet: {compute.get('message')}"
            data = await _client().post(
                f"/v1/plugin/projects/{project_id}/apps",
                {
                    "name": app_name or "compose-app",
                    "route_slug": route_slug or None,
                    "compute_placement": compute_placement,
                    "source": {"type": "compose", "compose_yaml": compose_yaml},
                },
            )
            task_id = data.get("task_id")
            app = data.get("app", {})
            project_apps = (await _client().get(f"/v1/plugin/projects/{project_id}/apps")).get("apps", [])
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "deploy_compose",
                        "project_id": project_id,
                        "app_id": app.get("id"),
                        "app_name": app.get("name") or app_name or "compose-app",
                    }
                }
            )
            lines = [
                f"🚀 Compose app queued (id: `{app.get('id')}`). Task ID: `{task_id}`",
                "This usually takes around 10 minutes. Feel free to keep working and ask me to check status later.",
                _fmt_task_hint(task_id),
            ]
            lines.extend(_post_deploy_suggestions(app, project_apps))
            return "\n".join(lines)
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
    async def get_app_logs(app_id: str, lines: int = 100) -> str:
        """Alias for get_logs() using app terminology."""
        return await get_logs(app_id, lines)

    @mcp.tool()
    async def exec_app_terminal(app_id: str, command: str, timeout_seconds: int = 20) -> str:
        """Run a shell command inside the user's own deployed app container and return the result. This is limited to the caller's app pod only."""
        try:
            data = await _client().post(
                f"/v1/plugin/apps/{app_id}/terminal",
                {"command": command, "timeout_seconds": timeout_seconds},
            )
            return (
                f"🖥️ **App Terminal**\n"
                f"App: `{data.get('app_name')}` (`{data.get('app_id')}`)\n"
                f"Pod: `{data.get('pod_name')}` | Container: `{data.get('container_name')}`\n\n"
                f"```sh\n{data.get('output', '')}\n```"
            )
        except Exception as e:
            return _compact_error("Error executing app terminal command", e)

    @mcp.tool()
    async def redeploy(deployment_id: str, confirmed_app_name: str) -> str:
        """Redeploy an existing app. Confirm the exact app name with the user first and pass it here."""
        try:
            app_data = await _client().get(f"/v1/plugin/apps/{deployment_id}")
            app = app_data.get("app", {})
            actual_name = app.get("name") or ""
            if confirmed_app_name.strip() != actual_name:
                return (
                    f"Redeploy blocked. The confirmed app name `{confirmed_app_name}` does not match the actual app name `{actual_name}`.\n"
                    "Ask the user to confirm the exact app name before redeploying."
                )
            data = await _client().post(f"/v1/plugin/apps/{deployment_id}/redeploy")
            task_id = data.get("task_id")
            await _remember_context({"last_completed_task": {"type": "redeploy", "app_id": deployment_id, "app_name": actual_name}})
            return f"🔄 Redeployment queued for **{actual_name}**. Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        except Exception as e:
            return _compact_error("Error triggering redeploy", e)

    @mcp.tool()
    async def restart_app(app_id: str) -> str:
        """Restart an app by queueing a redeploy."""
        try:
            data = await _client().post(f"/v1/plugin/apps/{app_id}/restart")
            task_id = data.get("task_id")
            await _remember_context({"last_completed_task": {"type": "restart_app", "app_id": app_id}})
            return f"🔄 App restart queued. Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        except Exception as e:
            return _compact_error("Error restarting app", e)

    @mcp.tool()
    async def rollback(deployment_id: str, revision: int | None = None) -> str:
        """Roll back an app to a previous revision."""
        try:
            params = {"revision": revision} if revision else {}
            data = await _client().post(f"/v1/plugin/apps/{deployment_id}/rollback", params=params)
            task_id = data.get("task_id")
            await _remember_context({"last_completed_task": {"type": "rollback", "app_id": deployment_id, "revision": revision}})
            return f"⏪ Rollback queued. Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        except Exception as e:
            return _compact_error("Error triggering rollback", e)

    @mcp.tool()
    async def remove_app(app_id: str) -> str:
        """Remove one of the authenticated user's apps. This deletes the runtime workload and revokes its active routing while marking the app as removed in PlugLayer."""
        try:
            app_data = await _client().get(f"/v1/plugin/apps/{app_id}")
            app = app_data.get("app", {})
            await _client().delete(f"/v1/plugin/apps/{app_id}")
            await _remember_context({"last_completed_task": {"type": "remove_app", "app_id": app_id, "app_name": app.get("name")}})
            return f"🧹 App **{app.get('name') or app_id}** removed. Its runtime workload and active PlugLayer routing were torn down."
        except Exception as e:
            return _compact_error("Error removing app", e)

    @mcp.tool()
    async def delete_deployment(deployment_id: str) -> str:
        """Alias for remove_app() for clients still using deployment wording."""
        return await remove_app(deployment_id)
