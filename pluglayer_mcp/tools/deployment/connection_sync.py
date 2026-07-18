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

def register_connection_sync_tools(mcp):
    @mcp.tool()
    async def sync_database_env_to_app(database_id: str, app_id: str, add_missing_connection_fields: bool = False) -> str:
        """Update one deployed app's env vars using a provisioned database's concrete connection details, then restart the existing app."""
        try:
            db_data = await _client().get(f"/v1/plugin/databases/{database_id}")
            app_data = await _client().get(f"/v1/plugin/apps/{app_id}")
            app = app_data.get("app", {})
            current_env = {str(key): str(value) for key, value in (app.get("env_vars") or {}).items()}
            connection_fields = _field_map(db_data.get("connection_fields"))
            database_env = {str(key): str(value) for key, value in (db_data.get("env_vars") or {}).items()}
            next_env = dict(current_env)
            changed: list[str] = []

            for key, value in connection_fields.items():
                if key in next_env or add_missing_connection_fields:
                    if next_env.get(key) != value:
                        next_env[key] = value
                        changed.append(key)
            for key, value in database_env.items():
                if key in next_env and next_env.get(key) != value:
                    next_env[key] = value
                    changed.append(key)

            if not changed:
                return (
                    f"No matching env vars needed changes on app `{app.get('name') or app_id}` "
                    f"from database `{(db_data.get('database') or {}).get('name') or database_id}`."
                )

            await _client().patch(f"/v1/plugin/apps/{app_id}/env", {"env_vars": next_env})
            restart_data = await _client().post(f"/v1/plugin/apps/{app_id}/restart")
            task_id = restart_data.get("task_id")
            return (
                f"🔁 Updated app **{app.get('name') or app_id}** with database-derived env vars from "
                f"**{(db_data.get('database') or {}).get('name') or database_id}**.\n"
                f"Changed keys: {', '.join(f'`{key}`' for key in sorted(set(changed)))}\n"
                "Action: env vars updated in place, then the existing app was restarted.\n"
                f"Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
            )
        except Exception as e:
            return _compact_error("Error syncing database env vars to app", e)
