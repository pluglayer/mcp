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

def register_compose_tools(mcp):
    @mcp.tool()
    async def deploy_compose(
        project_id: str,
        compose_yaml: str,
        app_name: str = "",
        route_slug: str = "",
        compute_placement: str = "personal",
        redeploy_strategy: str = "recreate",
        local_image_archives: dict[str, str] | None = None,
    ) -> str:
        """Analyze docker-compose.yml, split it into separate deploy units, provision known databases through Data Layer, and deploy the remaining services as separate apps. If any service uses a local Docker build, provide `local_image_archives` keyed by service name after building and exporting those images."""
        try:
            compute = await _get_compute_summary(project_id=project_id)
            if not compute.get("can_deploy"):
                return (
                    f"Cannot deploy into project `{project_id}` yet: {compute.get('message')} "
                    "Use list_attachable_project_nodes() and attach_node_to_project(), or help the user add compute, then retry."
                )
            plan = await _client().post(
                f"/v1/plugin/projects/{project_id}/apps/compose-plan",
                {"compose_yaml": compose_yaml},
            )
            if len(plan.get("services") or []) == 1:
                service = plan["services"][0]
                if app_name:
                    service["suggested_app_name"] = _slugify(app_name)
                if route_slug:
                    service["suggested_route_slug"] = _slugify(route_slug)
            missing_archives = [
                item.get("service_name")
                for item in (plan.get("services") or [])
                if item.get("strategy") == "local_build_image" and not (local_image_archives or {}).get(item.get("service_name"))
            ]
            if missing_archives:
                return (
                    f"{_format_compose_plan(plan)}\n\n"
                    "Local build services still need image archives before deployment:\n"
                    + "\n".join([f"- `{name}`" for name in missing_archives])
                    + "\n\nRun `get_compose_local_build_commands()` first, follow the test-build and OCI export steps, then call deploy_compose() again with `local_image_archives={\"service\": \"/path/to/service.oci.tar\"}`."
                )

            deployments: list[dict] = []
            database_contexts: dict[str, dict] = {}
            for item in plan.get("services") or []:
                strategy = item.get("strategy")
                if strategy == "database_template":
                    resolved_overrides = _compose_db_env_overrides(item)
                    preview = await _preview_database_runtime(
                        template_id=item.get("marketplace_template_id") or item.get("marketplace_template_slug"),
                        project_id=project_id,
                        app_name=item.get("suggested_app_name"),
                        route_slug=item.get("suggested_route_slug"),
                        env_overrides=resolved_overrides,
                    )
                    preview_maps = _database_preview_maps(preview)
                    preview_maps["app_name"] = item.get("suggested_app_name")
                    preview_maps["route_slug"] = item.get("suggested_route_slug")
                    database_contexts[item.get("service_name")] = preview_maps
                    data = await _client().post(
                        "/v1/plugin/databases",
                        {
                            "template_id": item.get("marketplace_template_id") or item.get("marketplace_template_slug"),
                            "project_id": project_id,
                            "app_name": item.get("suggested_app_name"),
                            "route_slug": item.get("suggested_route_slug"),
                            "compute_placement": compute_placement,
                            "env_overrides": resolved_overrides,
                        },
                    )
                    deployments.append(
                        {
                            "service_name": item.get("service_name"),
                            "strategy": strategy,
                            "task_id": data.get("task_id"),
                            "app": data.get("app", {}),
                        }
                    )
                    continue

                if strategy == "local_build_image":
                    archive_path = (local_image_archives or {}).get(item.get("service_name"))
                    if not archive_path:
                        raise RuntimeError(f"Missing local image archive for service {item.get('service_name')}")
                    resolved_env_vars, rewritten_keys = _patch_compose_env_vars(
                        item.get("env_vars") or {},
                        database_contexts=database_contexts,
                    )
                    form_data = {
                        "name": item.get("suggested_app_name"),
                        "tag": "latest",
                        "route_slug": item.get("suggested_route_slug") or "",
                        "compute_placement": compute_placement,
                        "redeploy_strategy": redeploy_strategy,
                        "registry_id": "",
                        "ports_json": json.dumps(item.get("ports") or []),
                        "env_vars_json": json.dumps(resolved_env_vars),
                        "command_args_json": json.dumps(item.get("command_args") or []),
                        "replicas": "1",
                        "cpu_limit": "500m",
                        "memory_limit": "512Mi",
                    }
                    data = await _client().post_multipart(
                        f"/v1/plugin/projects/{project_id}/apps/upload-image",
                        form_data=form_data,
                        file_field="archive",
                        file_path=archive_path,
                        content_type="application/x-tar",
                    )
                    deployments.append(
                        {
                            "service_name": item.get("service_name"),
                            "strategy": strategy,
                            "task_id": data.get("task_id"),
                            "app": data.get("app", {}),
                            "rewritten_env_keys": rewritten_keys,
                        }
                    )
                    continue

                resolved_env_vars, rewritten_keys = _patch_compose_env_vars(
                    item.get("env_vars") or {},
                    database_contexts=database_contexts,
                )
                compose_yaml_to_deploy = item.get("single_service_compose_yaml") or compose_yaml
                compose_yaml_to_deploy = _rewrite_single_service_compose_env(compose_yaml_to_deploy, resolved_env_vars)
                data = await _client().post(
                    f"/v1/plugin/projects/{project_id}/apps",
                    {
                        "name": item.get("suggested_app_name"),
                        "route_slug": item.get("suggested_route_slug") or None,
                        "compute_placement": compute_placement,
                        "redeploy_strategy": redeploy_strategy,
                        "source": {
                            "type": "compose",
                            "compose_yaml": compose_yaml_to_deploy,
                        },
                    },
                )
                deployments.append(
                    {
                        "service_name": item.get("service_name"),
                        "strategy": strategy,
                        "task_id": data.get("task_id"),
                        "app": data.get("app", {}),
                        "rewritten_env_keys": rewritten_keys,
                    }
                )

            if deployments:
                await _remember_context(
                    {
                        "last_completed_task": {
                            "type": "deploy_compose",
                            "project_id": project_id,
                            "deployments": [
                                {
                                    "service_name": item.get("service_name"),
                                    "app_id": (item.get("app") or {}).get("id"),
                                    "app_name": (item.get("app") or {}).get("name"),
                                    "task_id": item.get("task_id"),
                                }
                                for item in deployments
                            ],
                        }
                    }
                )
            lines = [
                "🚀 Smart compose deployment queued.",
                _format_compose_plan(plan),
                "",
                "Queued services:",
            ]
            lines.extend(
                [
                    (
                        f"- **{item.get('service_name')}** → `{((item.get('app') or {}).get('name') or item.get('service_name'))}`"
                        f" | task `{item.get('task_id')}`"
                        + (
                            f" | env rewired: {', '.join(f'`{key}`' for key in (item.get('rewritten_env_keys') or []))}"
                            if item.get("rewritten_env_keys")
                            else ""
                        )
                    )
                    for item in deployments
                ]
            )
            lines.append("\nThis usually takes around 10 minutes. Feel free to keep working and ask me to check status later.")
            task_ids = [item.get("task_id") for item in deployments if item.get("task_id")]
            if task_ids:
                lines.append("Task IDs: " + ", ".join(f"`{task_id}`" for task_id in task_ids))
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Compose deployment failed", e)

    @mcp.tool()
    async def analyze_compose_deploy_plan(project_id: str, compose_yaml: str) -> str:
        """Analyze a docker-compose.yml and show how PlugLayer will split it into marketplace databases, separate compose services, and local-build services."""
        try:
            plan = await _client().post(
                f"/v1/plugin/projects/{project_id}/apps/compose-plan",
                {"compose_yaml": compose_yaml},
            )
            return _format_compose_plan(plan)
        except Exception as e:
            return _compact_error("Compose analysis failed", e)

    @mcp.tool()
    async def get_compose_local_build_commands(
        project_id: str,
        compose_yaml: str,
        workspace_root: str = ".",
        image_tag_prefix: str = "pluglayer-compose",
    ) -> str:
        """Analyze a docker-compose.yml and return exact docker buildx, smoke-test, and OCI-export commands for any local-build services before they are uploaded to PlugLayer."""
        try:
            plan = await _client().post(
                f"/v1/plugin/projects/{project_id}/apps/compose-plan",
                {"compose_yaml": compose_yaml},
            )
            return _compose_build_commands(plan, workspace_root, image_tag_prefix)
        except Exception as e:
            return _compact_error("Compose local build analysis failed", e)
