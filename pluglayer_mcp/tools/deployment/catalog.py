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

def register_catalog_tools(mcp):
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
    async def check_slug_availability(project_id: str, slug: str, exclude_app_id: str = "") -> str:
        """Check whether a PlugLayer slug is available inside a project before deploying or renaming an app/database."""
        try:
            data = await _client().get(
                "/v1/plugin/apps/slug-availability",
                params={"project_id": project_id, "slug": slug, "exclude_app_id": exclude_app_id or None},
            )
            if data.get("available"):
                return f"✅ Slug `{data.get('slug')}` is available in project `{project_id}`."
            return f"❌ Slug `{data.get('slug')}` is not available in project `{project_id}`. {data.get('message') or ''}".strip()
        except Exception as e:
            return _compact_error("Error checking slug availability", e)
