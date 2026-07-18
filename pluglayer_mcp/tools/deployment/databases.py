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

def register_databases_tools(mcp):
    @mcp.tool()
    async def list_database_templates() -> str:
        """List database-ready marketplace templates. Use this first when the user asks to provision a database through PlugLayer."""
        try:
            data = await _client().get("/v1/plugin/databases/templates")
            templates = data.get("templates", [])
            if not templates:
                return "No database templates are available right now."
            lines = ["Available database templates:\n"]
            for template in templates:
                requirements = template.get("requirements") or {}
                config = template.get("database_config") or {}
                lines.append(
                    f"- **{template.get('name')}** (`{template.get('id')}`)\n"
                    f"  Engine: {config.get('engine') or template.get('category')} | Slug suggestion: `{template.get('slug')}`\n"
                    f"  Minimum: {requirements.get('min_cpu_cores', 0)} CPU, {requirements.get('min_ram_gb', 0)}GB RAM, {requirements.get('min_storage_gb', 0)}GB disk"
                )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing database templates", e)

    @mcp.tool()
    async def list_user_databases(project_id: str = "") -> str:
        """List the authenticated user's databases, optionally filtered to one project."""
        try:
            data = await _client().get("/v1/plugin/databases", params={"project_id": project_id} if project_id else None)
            databases = data.get("databases", [])
            if not databases:
                return "No databases found yet."
            lines = ["Your databases:\n"]
            for database in databases:
                lines.append(
                    f"{_status_emoji(database.get('status'))} **{database.get('name')}** (`{database.get('id')}`)\n"
                    f"   Engine: {((database.get('database_details') or {}).get('engine')) or 'database'} | Host: {database.get('primary_hostname') or 'provisioning'}\n"
                    f"   Project: `{database.get('project_id')}`"
                )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing user databases", e)

    @mcp.tool()
    async def create_database(
        template_id: str,
        app_name: str,
        project_id: str = "",
        project_name: str = "",
        route_slug: str = "",
        cpu_limit: str = "",
        memory_limit: str = "",
        storage_gb: int = 0,
        compute_placement: str = "auto",
        env_overrides: dict[str, str] | None = None,
        tcp_allowed_cidrs: list[str] | None = None,
    ) -> str:
        """Provision a database from a ready marketplace template. The MCP tool resolves required DB names and secret-like template fields here, including random password generation, before sending the deploy request."""
        try:
            if not project_id and not project_name:
                return "Database provisioning needs either `project_id` or `project_name`."
            compute = await _get_compute_summary(project_id=project_id or None)
            if not compute.get("can_deploy"):
                suffix = (
                    " Use list_attachable_project_nodes() and attach_node_to_project(), or help the user add compute, then retry."
                    if project_id else " Help the user add compute before provisioning into the new project."
                )
                return f"Cannot provision the database yet: {compute.get('message')}{suffix}"
            templates_data = await _client().get("/v1/plugin/databases/templates")
            templates = templates_data.get("templates", [])
            template = next(
                (
                    item
                    for item in templates
                    if item.get("id") == template_id or item.get("slug") == template_id
                ),
                None,
            )
            if not template:
                return f"Database template `{template_id}` was not found."
            route_slug_value = route_slug or _slugify(app_name)
            if project_id:
                availability = await _check_database_slug_availability(project_id, route_slug_value)
                if not availability.get("available"):
                    return (
                        f"❌ Database slug `{route_slug_value}` is not available in project `{project_id}`. "
                        f"{availability.get('message') or 'Choose another PlugLayer slug before provisioning.'}"
                    ).strip()
            resolved_overrides = _build_template_env_overrides(
                template,
                app_name=app_name,
                route_slug=route_slug_value,
                provided_overrides=env_overrides,
            )
            payload = {
                "template_id": template_id,
                "project_id": project_id or None,
                "project_name": project_name or None,
                "app_name": app_name,
                "route_slug": route_slug_value,
                "compute_placement": compute_placement,
                "env_overrides": resolved_overrides,
                "cpu_limit": cpu_limit or None,
                "memory_limit": memory_limit or None,
                "storage_gb": storage_gb or None,
                "tcp_allowed_cidrs": tcp_allowed_cidrs or [],
            }
            data = await _client().post("/v1/plugin/databases", payload)
            task_id = data.get("task_id")
            app = data.get("app", {})
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "create_database",
                        "project_id": data.get("project_id"),
                        "app_id": app.get("id"),
                        "app_name": app.get("name") or app_name,
                        "route_slug": app.get("route_slug") or route_slug_value,
                    }
                }
            )
            return (
                f"🗄️ Database queued: **{app.get('name') or app_name}** (`{app.get('id')}`)\n"
                f"Task ID: `{task_id}`\n"
                f"{_fmt_task_hint(task_id)}\n"
                "Required DB fields were resolved at deploy time, including generated secrets for password-like template env vars.\n"
                "After provisioning finishes, call get_database_connection_details() and update dependent apps with the new env vars or connection string."
            )
        except Exception as e:
            return _compact_error("Database provisioning failed", e)

    @mcp.tool()
    async def check_database_slug_availability(project_id: str, slug: str, exclude_database_id: str = "") -> str:
        """Check whether a database/Data Layer slug is available in a project before provisioning or renaming a database."""
        try:
            data = await _check_database_slug_availability(project_id, slug, exclude_database_id)
            if data.get("available"):
                return f"✅ Database slug `{data.get('slug')}` is available in project `{project_id}`."
            return f"❌ Database slug `{data.get('slug')}` is not available in project `{project_id}`. {data.get('message') or ''}".strip()
        except Exception as e:
            return _compact_error("Error checking database slug availability", e)

    @mcp.tool()
    async def get_database_connection_details(database_id: str) -> str:
        """Get a provisioned database's connection strings, env vars, and docs so you can wire other apps automatically."""
        try:
            data = await _client().get(f"/v1/plugin/databases/{database_id}")
            database = data.get("database", {})
            env_vars = data.get("env_vars") or {}
            connection_fields = data.get("connection_fields") or []
            lines = [
                f"🗄️ **Database details** for **{database.get('name') or database_id}**",
                f"Host: {database.get('primary_hostname') or 'not ready yet'}",
                f"Status: {database.get('status')}",
            ]
            if connection_fields:
                lines.append("\nConnection fields:")
                lines.extend([f"- `{field.get('key')}` = `{field.get('value')}`" for field in connection_fields])
            if env_vars:
                lines.append("\nEnv vars:")
                lines.extend([f"- `{key}` = `{value}`" for key, value in env_vars.items()])
            if data.get("documentation_url"):
                lines.append(f"\nDocs: {data.get('documentation_url')}")
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error getting database connection details", e)

    @mcp.tool()
    async def get_database_logs(database_id: str, lines: int = 100) -> str:
        """Get recent logs from a provisioned database."""
        try:
            data = await _client().get(f"/v1/plugin/databases/{database_id}/logs", params={"tail": lines})
            return f"📋 **Database logs** (last {lines} lines):\n\n```\n{data.get('logs', 'No logs available')}\n```"
        except Exception as e:
            return _compact_error("Error getting database logs", e)

    @mcp.tool()
    async def update_database_access(database_id: str, tcp_allowed_cidrs: list[str] | None = None) -> str:
        """Update a provisioned database's public TCP IP allowlist. Pass an empty list to allow all IPs again."""
        try:
            data = await _client().patch(
                f"/v1/plugin/databases/{database_id}/access",
                {"tcp_allowed_cidrs": tcp_allowed_cidrs or []},
            )
            cidrs = data.get("tcp_allowed_cidrs") or []
            if cidrs:
                return (
                    f"🔐 Updated database access rules for `{database_id}`.\n"
                    "Only these CIDRs/IPs can now connect:\n"
                    + "\n".join(f"- `{cidr}`" for cidr in cidrs)
                )
            return (
                f"🔓 Updated database access rules for `{database_id}`.\n"
                "The allowlist is empty, so public TCP access is open to all IPs again."
            )
        except Exception as e:
            return _compact_error("Error updating database access", e)

    @mcp.tool()
    async def restart_database(database_id: str) -> str:
        """Restart a provisioned database by queueing its redeploy/restart flow."""
        try:
            data = await _client().post(f"/v1/plugin/databases/{database_id}/restart")
            task_id = data.get("task_id")
            await _remember_context({"last_completed_task": {"type": "restart_database", "database_id": database_id}})
            return f"🔄 Database restart queued. Task ID: `{task_id}`\n{_fmt_task_hint(task_id)}"
        except Exception as e:
            return _compact_error("Error restarting database", e)

    @mcp.tool()
    async def remove_database(database_id: str) -> str:
        """Remove one of the caller's provisioned databases, including its runtime workload and active routing."""
        try:
            database_data = await _client().get(f"/v1/plugin/databases/{database_id}")
            database = database_data.get("database", {})
            await _client().delete(f"/v1/plugin/databases/{database_id}")
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "remove_database",
                        "database_id": database_id,
                        "database_name": database.get("name"),
                    }
                }
            )
            return f"🧹 Database **{database.get('name') or database_id}** removed. Its runtime workload and active PlugLayer routing were torn down."
        except Exception as e:
            return _compact_error("Error removing database", e)

    @mcp.tool()
    async def delete_database(database_id: str) -> str:
        """Alias for remove_database()."""
        return await remove_database(database_id)
