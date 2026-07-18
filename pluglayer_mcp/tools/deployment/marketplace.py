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

def register_marketplace_tools(mcp):
    @mcp.tool()
    async def list_marketplace_templates(
        category: str = "",
        search: str = "",
        featured_only: bool = False,
        test_state: str = "",
    ) -> str:
        """List deployable marketplace templates. Use this before deploying a ready-made template through PlugLayer."""
        try:
            params = {
                "category": category or None,
                "search": search or None,
                "featured": True if featured_only else None,
                "test_state": test_state or None,
            }
            data = await _client().get("/v1/plugin/marketplace/templates", params=params)
            templates = data.get("templates", [])
            if not templates:
                return "No marketplace templates matched that filter."
            lines = ["Marketplace templates:\n"]
            for template in templates:
                requirements = template.get("requirements") or {}
                exposure = template.get("exposure_config") or {}
                lines.append(
                    f"- **{template.get('name')}** (`{template.get('id')}`)\n"
                    f"  Category: {template.get('category')} | Exposure: {exposure.get('type') or 'https'}\n"
                    f"  Minimum: {requirements.get('min_cpu_cores', 0)} CPU, {requirements.get('min_ram_gb', 0)}GB RAM, {requirements.get('min_storage_gb', 0)}GB disk"
                )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing marketplace templates", e)

    @mcp.tool()
    async def get_marketplace_template(template_id_or_slug: str) -> str:
        """Get one marketplace template, including env var requirements. Use this before template deployment so you can resolve secrets and choose project flow correctly."""
        try:
            data = await _client().get(f"/v1/plugin/marketplace/templates/{template_id_or_slug}")
            template = data.get("template", {})
            requirements = template.get("requirements") or {}
            env_vars = template.get("template_env_vars") or []
            exposure = template.get("exposure_config") or {}
            lines = [
                f"📦 **Template**: {template.get('name')}",
                f"ID: `{template.get('id')}`",
                f"Category: {template.get('category')}",
                f"Exposure: {exposure.get('type') or 'https'}",
                f"Minimum: {requirements.get('min_cpu_cores', 0)} CPU, {requirements.get('min_ram_gb', 0)}GB RAM, {requirements.get('min_storage_gb', 0)}GB disk",
            ]
            if env_vars:
                lines.append("\nEnv vars:")
                for env_var in env_vars:
                    meta = []
                    if env_var.get("required"):
                        meta.append("required")
                    if env_var.get("sensitive"):
                        meta.append("sensitive")
                    if env_var.get("randomizable"):
                        meta.append("randomizable")
                    lines.append(
                        f"- `{env_var.get('key')}` = `{env_var.get('value') or ''}`"
                        + (f" ({', '.join(meta)})" if meta else "")
                    )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error getting marketplace template", e)

    @mcp.tool()
    async def deploy_marketplace_template(
        template_id: str,
        app_name: str,
        project_id: str = "",
        project_name: str = "",
        route_slug: str = "",
        compute_placement: str = "auto",
        cpu_limit: str = "",
        memory_limit: str = "",
        storage_gb: int = 0,
        env_overrides: dict[str, str] | None = None,
        tcp_allowed_cidrs: list[str] | None = None,
    ) -> str:
        """Deploy a marketplace template into an existing project or a brand-new project created during the same flow. Secret-like required env vars are auto-resolved here before the deploy request is sent."""
        try:
            if not project_id and not project_name:
                return "Template deployment needs either `project_id` or `project_name`."
            compute = await _get_compute_summary(project_id=project_id or None)
            if not compute.get("can_deploy"):
                suffix = (
                    " Use list_attachable_project_nodes() and attach_node_to_project(), or help the user add compute, then retry."
                    if project_id else " Help the user add compute before creating and deploying into the new project."
                )
                return f"Cannot deploy yet: {compute.get('message')}{suffix}"
            template_data = await _client().get(f"/v1/plugin/marketplace/templates/{template_id}")
            template = template_data.get("template", {})
            route_slug_value = route_slug or _slugify(app_name)
            resolved_overrides = _build_template_env_overrides(
                template,
                app_name=app_name,
                route_slug=route_slug_value,
                provided_overrides=env_overrides,
            )
            payload = {
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
            data = await _client().post(f"/v1/plugin/marketplace/templates/{template_id}/deploy", payload)
            task_id = data.get("task_id")
            app = data.get("app", {})
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "deploy_marketplace_template",
                        "project_id": data.get("project_id") or project_id,
                        "app_id": app.get("id"),
                        "app_name": app.get("name") or app_name,
                        "route_slug": app.get("route_slug") or route_slug_value,
                    }
                }
            )
            return (
                f"📦 Template deployment queued: **{app.get('name') or app_name}** (`{app.get('id')}`)\n"
                f"Project: `{data.get('project_id') or project_id or project_name}`\n"
                f"Task ID: `{task_id}`\n"
                f"{_fmt_task_hint(task_id)}\n"
                "Any required secret-like env vars were resolved at deploy time, including random credentials where the template asked for them."
            )
        except Exception as e:
            return _compact_error("Template deployment failed", e)
