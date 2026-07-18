"""Deployment MCP tool registrations."""

import json
import os

from pluglayer_mcp.tools.deployment.helpers import (
    _build_template_env_overrides,
    _check_database_slug_availability,
    _compose_build_commands,
    _compose_db_env_overrides,
    _database_family_for_image,
    _database_preview_maps,
    _field_map,
    _find_database_template_for_family,
    _find_existing_project_app_match,
    _format_compose_plan,
    _patch_compose_env_vars,
    _post_deploy_suggestions,
    _preview_database_runtime,
    _render_exception_reason,
    _rewrite_single_service_compose_env,
    _slugify,
    _task_failure_reason,
)
from pluglayer_mcp.tools.shared import (
    _client,
    _compact_error,
    _fmt_task_hint,
    _get_compute_summary,
    _remember_context,
    _status_emoji,
)

def register_app_operations_tools(mcp, get_logs):
    @mcp.tool()
    async def get_app_logs(app_id: str, lines: int = 100) -> str:
        """Alias for get_logs() using app terminology."""
        return await get_logs(app_id, lines)

    @mcp.tool()
    async def exec_app_terminal(app_id: str, command: str) -> str:
        """Run a shell command inside the user's own deployed app container and return the result. Uses a fixed 360-second backend timeout. Keep input at or below 10,000 characters and about 350 lines. This is limited to the caller's app pod only."""
        try:
            data = await _client().post(
                f"/v1/plugin/apps/{app_id}/terminal",
                {"command": command, "timeout_seconds": 360},
                timeout=375.0,
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
    async def redeploy(deployment_id: str, confirmed_app_name: str, redeploy_strategy: str = "recreate") -> str:
        """Redeploy an existing app without changing its current slug. Confirm the exact app name with the user first and pass it here. Default to `recreate` to minimize temporary live compute usage; use `rolling` only when the user explicitly prefers lower-downtime rollout behavior."""
        try:
            app_data = await _client().get(f"/v1/plugin/apps/{deployment_id}")
            app = app_data.get("app", {})
            actual_name = app.get("name") or ""
            if confirmed_app_name.strip() != actual_name:
                return (
                    f"Redeploy blocked. The confirmed app name `{confirmed_app_name}` does not match the actual app name `{actual_name}`.\n"
                    "Ask the user to confirm the exact app name before redeploying."
                )
            data = await _client().post(
                f"/v1/plugin/apps/{deployment_id}/redeploy",
                {"redeploy_strategy": redeploy_strategy},
            )
            task_id = data.get("task_id")
            await _remember_context({"last_completed_task": {"type": "redeploy", "app_id": deployment_id, "app_name": actual_name}})
            return (
                f"🔄 Redeployment queued for **{actual_name}** without changing its slug.\n"
                f"Strategy: `{redeploy_strategy}`\n"
                f"Task ID: `{task_id}`\n"
                f"{_fmt_task_hint(task_id)}"
            )
        except Exception as e:
            return _compact_error("Error triggering redeploy", e)

    @mcp.tool()
    async def restart_app(app_id: str, redeploy_strategy: str = "recreate") -> str:
        """Restart an app by queueing a redeploy. Default to `recreate` to optimize compute usage; use `rolling` only when lower downtime matters more than temporary headroom."""
        try:
            data = await _client().post(
                f"/v1/plugin/apps/{app_id}/restart",
                {"redeploy_strategy": redeploy_strategy},
            )
            task_id = data.get("task_id")
            await _remember_context({"last_completed_task": {"type": "restart_app", "app_id": app_id}})
            return f"🔄 App restart queued.\nStrategy: `{redeploy_strategy}`\nTask ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
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

    @mcp.tool()
    async def delete_app(app_id: str) -> str:
        """Alias for remove_app() using app wording."""
        return await remove_app(app_id)
