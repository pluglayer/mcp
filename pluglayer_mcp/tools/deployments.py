"""Deployment/app MCP tools backed by PlugLayer v1 apps API."""

import json
import os
import re
import secrets

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


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", (value or "").strip().lower()).strip("-")
    return slug or "app"


def _random_secret(length_bytes: int = 24) -> str:
    return secrets.token_hex(length_bytes)


def _resolve_template_value(template_value: str, *, app_name: str, route_slug: str) -> str:
    rendered = (template_value or "").replace("{{APP_NAME}}", app_name).replace("{{ROUTE_SLUG}}", route_slug)
    rendered = re.sub(r"\$\{APP_NAME(?::-([^}]*))?\}", app_name, rendered)
    rendered = re.sub(r"\$\{ROUTE_SLUG(?::-([^}]*))?\}", route_slug, rendered)
    return rendered


def _looks_secret_like(env_var: dict) -> bool:
    key = str(env_var.get("key") or "").lower()
    description = str(env_var.get("description") or "").lower()
    value_type = str(env_var.get("value_type") or "").lower()
    if env_var.get("randomizable") or env_var.get("sensitive"):
        return True
    if value_type in {"password", "secret", "token"}:
        return True
    secret_words = ("password", "secret", "token", "key")
    return any(word in key for word in secret_words) or any(word in description for word in secret_words)


def _build_template_env_overrides(
    template: dict,
    *,
    app_name: str,
    route_slug: str,
    provided_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    overrides = dict(provided_overrides or {})
    env_vars = (
        template.get("template_env_vars")
        or ((template.get("database_config") or {}).get("env_vars"))
        or []
    )
    for env_var in env_vars:
        key = env_var.get("key")
        if not key or overrides.get(key):
            continue
        resolved = _resolve_template_value(str(env_var.get("value") or ""), app_name=app_name, route_slug=route_slug)
        if re.search(r"\{\{RANDOM_[A-Z0-9_]+\}\}", resolved):
            overrides[key] = _random_secret()
            continue
        if re.search(r"\{\{[A-Z0-9_]+\}\}", resolved):
            if _looks_secret_like(env_var):
                overrides[key] = _random_secret()
            elif env_var.get("required"):
                overrides[key] = app_name
            continue
        if env_var.get("required") and not resolved and _looks_secret_like(env_var):
            overrides[key] = _random_secret()
            continue
        if resolved:
            overrides[key] = resolved
    return overrides


def _normalize_compose_env_value(value: str) -> str | None:
    text = (value or "").strip()
    match = re.fullmatch(r"\$\{[A-Z0-9_]+(?::?-([^}]*))?\}", text, flags=re.IGNORECASE)
    if match:
        default = match.group(1)
        return default if default is not None else None
    return text or None


def _compose_db_env_overrides(plan_item: dict) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for key, value in (plan_item.get("env_vars") or {}).items():
        normalized = _normalize_compose_env_value(str(value))
        if normalized is not None:
            overrides[key] = normalized
    return overrides


def _format_compose_plan(plan: dict) -> str:
    services = plan.get("services") or []
    lines = [
        "Smart compose plan:\n",
        f"- Database templates: {plan.get('database_template_count', 0)}",
        f"- Separate compose apps: {plan.get('compose_service_count', 0)}",
        f"- Local builds: {plan.get('local_build_count', 0)}",
    ]
    conflicts = plan.get("name_conflicts") or []
    if conflicts:
        lines.append(f"- Name conflicts: {', '.join(conflicts)}")
    for item in services:
        strategy = item.get("strategy")
        label = {
            "database_template": f"Data Layer ({item.get('marketplace_template_slug') or item.get('marketplace_template_name') or 'template'})",
            "compose_service": "separate compose app",
            "local_build_image": "local build + uploaded image",
        }.get(strategy, strategy or "service")
        lines.append(
            f"- **{item.get('service_name')}** → {label} | app `{item.get('suggested_app_name')}` | slug `{item.get('suggested_route_slug')}`"
        )
    notes = plan.get("notes") or []
    if notes:
        lines.append("\nNotes:")
        lines.extend([f"- {note}" for note in notes])
    return "\n".join(lines)


def _quote_shell(value: str) -> str:
    escaped = value.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def _compose_build_commands(plan: dict, workspace_root: str, image_tag_prefix: str) -> str:
    services = [
        item for item in (plan.get("services") or [])
        if item.get("strategy") == "local_build_image"
    ]
    if not services:
        return "No local-build services were detected in this compose stack."
    root = workspace_root or "."
    prefix = _slugify(image_tag_prefix or "pluglayer-compose")
    lines = [
        "Local build steps for compose services:\n",
        f"Workspace root: `{root}`",
    ]
    for item in services:
        service = item.get("service_name")
        context = item.get("build_context") or "."
        dockerfile = item.get("build_dockerfile")
        tag = f"{prefix}-{_slugify(service)}:latest"
        archive = f".pluglayer/{_slugify(service)}.tar"
        context_path = os.path.join(root, context)
        build_parts = ["docker", "build", "-t", tag]
        if dockerfile:
            build_parts.extend(["-f", os.path.join(context_path, dockerfile)])
        build_parts.append(context_path)
        save_parts = ["docker", "save", tag, "-o", os.path.join(root, archive)]
        lines.append(f"\n- **{service}**")
        lines.append(f"  Build:\n  ```sh\n{' '.join(_quote_shell(part) for part in build_parts)}\n  ```")
        lines.append(f"  Export:\n  ```sh\n{' '.join(_quote_shell(part) for part in save_parts)}\n  ```")
        if item.get("command_args"):
            lines.append(f"  Startup args preserved: `{item.get('command_args')}`")
        lines.append(
            "  Then call `deploy_compose(..., local_image_archives={"
            + f"\"{service}\": \"{os.path.join(root, archive)}\""
            + "})`."
        )
    return "\n".join(lines)


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
                    "command_args": command_args or [],
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
        command_args: list[str] | None = None,
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
        local_image_archives: dict[str, str] | None = None,
    ) -> str:
        """Analyze docker-compose.yml, split it into separate deploy units, provision known databases through Data Layer, and deploy the remaining services as separate apps. If any service uses a local Docker build, provide `local_image_archives` keyed by service name after building and exporting those images."""
        try:
            compute = await _get_compute_summary()
            if not compute.get("can_deploy"):
                return f"Cannot deploy yet: {compute.get('message')}"
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
                    + "\n\nBuild each service image locally, export it with `docker save`, then call deploy_compose() again with `local_image_archives={\"service\": \"/path/to/image.tar\"}`."
                )

            deployments: list[dict] = []
            for item in plan.get("services") or []:
                strategy = item.get("strategy")
                if strategy == "database_template":
                    data = await _client().post(
                        "/v1/plugin/databases",
                        {
                            "template_id": item.get("marketplace_template_id") or item.get("marketplace_template_slug"),
                            "project_id": project_id,
                            "app_name": item.get("suggested_app_name"),
                            "route_slug": item.get("suggested_route_slug"),
                            "compute_placement": compute_placement,
                            "env_overrides": _compose_db_env_overrides(item),
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
                    form_data = {
                        "name": item.get("suggested_app_name"),
                        "tag": "latest",
                        "route_slug": item.get("suggested_route_slug") or "",
                        "compute_placement": compute_placement,
                        "registry_id": "",
                        "ports_json": json.dumps(item.get("ports") or []),
                        "env_vars_json": json.dumps(item.get("env_vars") or {}),
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
                        }
                    )
                    continue

                data = await _client().post(
                    f"/v1/plugin/projects/{project_id}/apps",
                    {
                        "name": item.get("suggested_app_name"),
                        "route_slug": item.get("suggested_route_slug") or None,
                        "compute_placement": compute_placement,
                        "source": {
                            "type": "compose",
                            "compose_yaml": item.get("single_service_compose_yaml") or compose_yaml,
                        },
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
                    f"- **{item.get('service_name')}** → `{((item.get('app') or {}).get('name') or item.get('service_name'))}` | task `{item.get('task_id')}`"
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
        """Analyze a docker-compose.yml and return exact docker build and docker save commands for any local-build services so they can be uploaded as image archives."""
        try:
            plan = await _client().post(
                f"/v1/plugin/projects/{project_id}/apps/compose-plan",
                {"compose_yaml": compose_yaml},
            )
            return _compose_build_commands(plan, workspace_root, image_tag_prefix)
        except Exception as e:
            return _compact_error("Compose local build analysis failed", e)

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
            compute = await _get_compute_summary()
            if not compute.get("can_deploy"):
                return f"Cannot deploy yet: {compute.get('message')}"
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

    @mcp.tool()
    async def delete_app(app_id: str) -> str:
        """Alias for remove_app() using app wording."""
        return await remove_app(app_id)
