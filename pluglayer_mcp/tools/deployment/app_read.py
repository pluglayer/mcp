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
    _looks_like_public_docker_hub_image,
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

def register_app_read_tools(mcp):
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
    async def get_app_connection_env_vars(app_id: str) -> str:
        """Get env vars and connection fields for an app. Use this after provisioning so you can update dependent apps with the right URLs or connection strings."""
        try:
            data = await _client().get(f"/v1/plugin/apps/{app_id}")
            app = data.get("app", {})
            env_vars = app.get("env_vars") or {}
            connection_fields = ((app.get("database_details") or {}).get("connection_fields")) or []
            lines = [
                f"🔐 **App connection/env details** for **{app.get('name') or app_id}**",
                f"Route slug: `{app.get('route_slug') or app.get('name')}`",
                f"Primary host: {app.get('primary_hostname') or 'not ready yet'}",
            ]
            if env_vars:
                lines.append("\nEnv vars:")
                lines.extend([f"- `{key}` = `{value}`" for key, value in env_vars.items()])
            if connection_fields:
                lines.append("\nConnection fields:")
                lines.extend([f"- `{field.get('key')}` = `{field.get('value')}`" for field in connection_fields])
            if not env_vars and not connection_fields:
                lines.append("\nNo env vars or connection fields are available yet.")
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error getting app connection/env vars", e)

    return get_logs
