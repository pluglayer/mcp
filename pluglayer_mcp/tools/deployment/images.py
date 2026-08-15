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

def register_images_tools(mcp):
    @mcp.tool()
    async def deploy_image(
        project_id: str,
        name: str,
        image: str,
        tag: str = "latest",
        ports: list[int] | None = None,
        env_vars: dict[str, str] | None = None,
        command_args: list[str] | None = None,
        replicas: int = 1,
        route_slug: str = "",
        cpu_limit: str = "500m",
        memory_limit: str = "512Mi",
        compute_placement: str = "personal",
        redeploy_strategy: str = "recreate",
        registry_id: str = "",
    ) -> str:
        """Deploy a pullable Docker image after PlugLayer mirrors it into a verified private managed repository. There is no public/direct-image bypass. For a local-only image built on the user's machine, use upload_image_archive_and_deploy() instead."""
        try:
            database_family = _database_family_for_image(image)
            if database_family:
                route_slug_value = route_slug or _slugify(name)
                template = await _find_database_template_for_family(database_family)
                if template:
                    resolved_overrides = _build_template_env_overrides(
                        template,
                        app_name=name,
                        route_slug=route_slug_value,
                        provided_overrides=env_vars,
                    )
                    routed_compute_placement = "auto" if compute_placement == "personal" else compute_placement
                    data = await _client().post(
                        "/v1/plugin/databases",
                        {
                            "template_id": template.get("id") or template.get("slug"),
                            "project_id": project_id,
                            "app_name": name,
                            "route_slug": route_slug_value,
                            "compute_placement": routed_compute_placement,
                            "env_overrides": resolved_overrides,
                            "cpu_limit": cpu_limit,
                            "memory_limit": memory_limit,
                        },
                    )
                    task_id = data.get("task_id")
                    app = data.get("app", {})
                    await _remember_context(
                        {
                            "last_completed_task": {
                                "type": "create_database",
                                "project_id": project_id,
                                "app_id": app.get("id"),
                                "app_name": app.get("name") or name,
                                "route_slug": app.get("route_slug") or route_slug_value,
                            }
                        }
                    )
                    return (
                        f"🗄️ Routed `{image}:{tag}` through the Data Layer database flow using template **{template.get('name') or template.get('slug')}**.\n"
                        f"Database queued: **{app.get('name') or name}** (`{app.get('id')}`)\n"
                        f"Task ID: `{task_id}`\n"
                        f"{_fmt_task_hint(task_id)}\n"
                        "This matches the frontend database deployment path, including template-based runtime rendering and database-specific defaults."
                    )

            compute = await _get_compute_summary(project_id=project_id)
            if not compute.get("can_deploy"):
                return (
                    f"Cannot deploy into project `{project_id}` yet: {compute.get('message')} "
                    "Use list_attachable_project_nodes() and attach_node_to_project(), or help the user add compute, then retry."
                )
            payload = {
                "name": name,
                "route_slug": route_slug or None,
                "compute_placement": compute_placement,
                "redeploy_strategy": redeploy_strategy,
                "registry_id": registry_id or None,
                "source": {
                    "type": "image",
                    "image": image,
                    "tag": tag,
                    "ports": ports or [],
                    "env_vars": env_vars or {},
                    "command_args": command_args or [],
                    "replicas": replicas,
                    "cpu_limit": cpu_limit,
                    "memory_limit": memory_limit,
                },
            }
            data = await _client().post(f"/v1/plugin/projects/{project_id}/apps/push-image", payload)
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
            else:
                lines.append("PlugLayer accepted the deployment only after verifying its managed repository is private.")
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
        command_args: list[str] | None = None,
        replicas: int = 1,
        route_slug: str = "",
        cpu_limit: str = "500m",
        memory_limit: str = "512Mi",
        compute_placement: str = "personal",
        redeploy_strategy: str = "recreate",
        registry_id: str = "",
    ) -> str:
        """Upload a locally built Docker/OCI image archive to PlugLayer. If the target app already exists in the project, upload to that app first and redeploy it; otherwise create a new app from the mirrored image."""
        try:
            if not os.path.exists(image_archive_path):
                return f"Image archive not found: {image_archive_path}"
            compute = await _get_compute_summary(project_id=project_id)
            if not compute.get("can_deploy"):
                return (
                    f"Cannot deploy into project `{project_id}` yet: {compute.get('message')} "
                    "Use list_attachable_project_nodes() and attach_node_to_project(), or help the user add compute, then retry."
                )
            project_apps = (await _client().get(f"/v1/plugin/projects/{project_id}/apps")).get("apps", [])
            existing_app = _find_existing_project_app_match(project_apps, name=name, route_slug=route_slug)
            if existing_app and existing_app.get("id"):
                data = await _client().post_multipart(
                    f"/v1/plugin/apps/{existing_app.get('id')}/upload-image-redeploy",
                    form_data={
                        "tag": tag,
                        "registry_id": registry_id or "",
                        "redeploy_strategy": redeploy_strategy,
                        "wait_seconds": "0",
                    },
                    file_field="archive",
                    file_path=image_archive_path,
                    content_type="application/x-tar",
                )
                task_id = data.get("task_id")
                mirrored = data.get("mirrored_image")
                task_check = data.get("task_check") or {}
                failure_reason = _task_failure_reason(task_check)
                if failure_reason:
                    return (
                        "Uploaded image redeploy failed.\n\n"
                        f"Archive: `{image_archive_path}`\n"
                        f"Reason: {failure_reason}"
                    )
                await _remember_context(
                    {
                        "last_completed_task": {
                            "type": "upload_image_archive_and_redeploy_app",
                            "project_id": project_id,
                            "app_id": existing_app.get("id"),
                            "app_name": existing_app.get("name") or name,
                            "route_slug": existing_app.get("route_slug") or route_slug or name,
                        },
                        "projects": {
                            project_id: {
                                "last_app_id": existing_app.get("id"),
                                "last_app_name": existing_app.get("name") or name,
                            }
                        },
                    }
                )
                return (
                    f"🔄 Existing app matched, so MCP used the upload-first redeploy flow for **{existing_app.get('name') or name}**.\n"
                    f"App ID: `{existing_app.get('id')}`\n"
                    f"Slug kept: `{existing_app.get('route_slug') or existing_app.get('name') or name}`\n"
                    f"New image tag: `{tag}`\n"
                    + (f"Mirrored image: `{mirrored}`\n" if mirrored else "")
                    + f"Task ID: `{task_id}`\n"
                    + "This usually takes around 10 minutes. Feel free to keep working and ask me to check status later.\n"
                    + _fmt_task_hint(task_id)
                )
            form_data = {
                "name": name,
                "tag": tag,
                "route_slug": route_slug or "",
                "compute_placement": compute_placement,
                "redeploy_strategy": redeploy_strategy,
                "registry_id": registry_id or "",
                "ports_json": json.dumps(ports or []),
                "env_vars_json": json.dumps(env_vars or {}),
                "command_args_json": json.dumps(command_args or []),
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
            return (
                "Uploaded image deployment failed.\n\n"
                f"Archive: `{image_archive_path}`\n"
                f"Reason: {_render_exception_reason(e)}"
            )

    @mcp.tool()
    async def upload_image_archive_and_redeploy_app(
        app_id: str,
        image_archive_path: str,
        tag: str = "latest",
        registry_id: str = "",
        redeploy_strategy: str = "recreate",
        wait_seconds: int = 0,
    ) -> str:
        """Rebuild flow for existing apps: upload a newly built image archive, push it with a new tag, keep the current slug, and redeploy the existing app."""
        try:
            if not os.path.exists(image_archive_path):
                return f"Image archive not found: {image_archive_path}"
            app_data = await _client().get(f"/v1/plugin/apps/{app_id}")
            app = app_data.get("app", {})
            data = await _client().post_multipart(
                f"/v1/plugin/apps/{app_id}/upload-image-redeploy",
                form_data={
                    "tag": tag,
                    "registry_id": registry_id or "",
                    "redeploy_strategy": redeploy_strategy,
                    "wait_seconds": str(wait_seconds),
                },
                file_field="archive",
                file_path=image_archive_path,
                content_type="application/x-tar",
            )
            task_id = data.get("task_id")
            mirrored = data.get("mirrored_image")
            task_check = data.get("task_check") or {}
            failure_reason = _task_failure_reason(task_check)
            if failure_reason:
                return (
                    "Uploaded image redeploy failed.\n\n"
                    f"Archive: `{image_archive_path}`\n"
                    f"Reason: {failure_reason}"
                )
            return (
                f"🔄 Rebuild + redeploy queued for **{app.get('name') or app_id}**.\n"
                f"Slug kept: `{app.get('route_slug') or app.get('name')}`\n"
                f"New image tag: `{tag}`\n"
                + (f"Mirrored image: `{mirrored}`\n" if mirrored else "")
                + f"Task ID: `{task_id}`\n"
                + (
                    "The backend waited briefly and did not see a final failure yet.\n"
                    if wait_seconds > 0 else ""
                )
                + _fmt_task_hint(task_id)
            )
        except Exception as e:
            return (
                "Uploaded image redeploy failed.\n\n"
                f"Archive: `{image_archive_path}`\n"
                f"Reason: {_render_exception_reason(e)}"
            )
