"""Deployment/app MCP tools backed by PlugLayer v1 apps API."""

import json
import os
import re
import secrets
from copy import deepcopy

import yaml
from pluglayer_mcp.tools.shared import (
    _client,
    _compact_error,
    _fmt_task_hint,
    _get_compute_summary,
    _remember_context,
    _status_emoji,
)


def _render_exception_reason(exc: Exception) -> str:
    text = str(exc).strip()
    if text:
        return text
    return getattr(exc, "message", "") or exc.__class__.__name__ or "Unknown error"


def _task_failure_reason(task_check: dict | None) -> str:
    if not isinstance(task_check, dict):
        return ""
    task = task_check.get("task") or {}
    if (task.get("status") or "").lower() not in {"failed", "cancelled"}:
        return ""
    parts: list[str] = []
    error_message = str(task.get("error_message") or "").strip()
    if error_message:
        parts.append(error_message)
    status_payload = task_check.get("status") or {}
    status_app = (status_payload.get("app") or {}) if isinstance(status_payload, dict) else {}
    app_error = str(status_app.get("error_message") or "").strip()
    if app_error and app_error not in parts:
        parts.append(app_error)
    runtime = (status_payload.get("runtime") or {}) if isinstance(status_payload, dict) else {}
    warnings = runtime.get("warnings") or []
    if warnings:
        parts.append("Warnings: " + " | ".join(str(item) for item in warnings[:3] if item))
    logs = task_check.get("logs") or {}
    log_text = str(logs.get("logs") or "").strip() if isinstance(logs, dict) else ""
    if log_text and log_text != "No pods found for this app":
        parts.append("Logs: " + log_text[:500])
    return "\n".join(parts).strip()


def _database_family_for_image(image: str) -> str | None:
    candidate = ((image or "").split(":")[0].split("/")[-1] or "").strip().lower()
    if not candidate:
        return None
    aliases = {
        "postgresql": "postgres",
        "postgres": "postgres",
        "mongo": "mongodb",
        "mongodb": "mongodb",
        "redis": "redis",
        "valkey": "redis",
        "qdrant": "qdrant",
        "mysql": "mysql",
        "mariadb": "mariadb",
    }
    for alias, canonical in aliases.items():
        if alias in candidate:
            return canonical
    return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", (value or "").strip().lower()).strip("-")
    return slug or "app"


def _find_existing_project_app_match(project_apps: list[dict] | None, *, name: str, route_slug: str) -> dict | None:
    apps = [app for app in (project_apps or []) if isinstance(app, dict)]
    target_name = _slugify(name)
    target_slug = _slugify(route_slug or name)
    if not apps:
        return None

    for app in apps:
        app_slug = _slugify(str(app.get("route_slug") or ""))
        if app_slug and app_slug == target_slug:
            return app

    for app in apps:
        app_name = _slugify(str(app.get("name") or ""))
        if app_name and app_name == target_name:
            return app

    for app in apps:
        app_name = _slugify(str(app.get("name") or ""))
        if app_name and app_name == target_slug:
            return app
    return None


_SHELL_ENV_REFERENCE = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}", re.IGNORECASE)
_WEAK_SECRET_DEFAULTS = frozenset({
    "",
    "change_me",
    "changeme",
    "changeme_at_least_64_chars",
    "password",
    "secret",
    "postgres",
    "admin",
})


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


def _has_unresolved_placeholder(value: str) -> bool:
    return bool(re.search(r"\{\{[A-Z0-9_]+\}\}", value) or _SHELL_ENV_REFERENCE.search(value))


def _is_unresolved_or_weak_secret(value: str, env_var: dict | None = None) -> bool:
    text = (value or "").strip()
    if _has_unresolved_placeholder(text):
        return True
    if env_var is not None and not _looks_secret_like(env_var):
        return not text
    return text.lower() in _WEAK_SECRET_DEFAULTS


def _assign_generated_or_default(overrides: dict[str, str], key: str, fallback: str | None) -> None:
    if not key or overrides.get(key):
        return
    if _looks_secret_like({"key": key}):
        overrides[key] = _random_secret()
        return
    if fallback:
        overrides[key] = fallback


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
        if env_var.get("database_binding"):
            # The backend resolves these against the selected project/database.
            continue
        resolved = _resolve_template_value(str(env_var.get("value") or ""), app_name=app_name, route_slug=route_slug)
        references = list(_SHELL_ENV_REFERENCE.finditer(resolved))
        if references:
            referenced_keys = {match.group(1) for match in references}
            for match in references:
                _assign_generated_or_default(overrides, match.group(1), match.group(2))
            # Drop alias keys such as POSTGRES_PASSWORD=${PG_DATABASE_PASSWORD:-...}
            # so the referenced deploy-time input is what gets generated.
            if key not in referenced_keys:
                continue
        if overrides.get(key):
            continue
        if _looks_secret_like(env_var) and _is_unresolved_or_weak_secret(resolved, env_var):
            overrides[key] = _random_secret()
            continue
        if re.search(r"\{\{RANDOM_[A-Z0-9_]+\}\}", resolved):
            overrides[key] = _random_secret()
            continue
        if re.search(r"\{\{[A-Z0-9_]+\}\}", resolved) or _SHELL_ENV_REFERENCE.search(resolved):
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


def _field_map(fields: list[dict] | None) -> dict[str, str]:
    return {
        str(field.get("key")): str(field.get("value"))
        for field in (fields or [])
        if field.get("key") and field.get("value") is not None
    }


def _database_preview_maps(preview: dict) -> dict[str, dict[str, str] | str]:
    connection_fields = _field_map(preview.get("connection_fields"))
    env_vars = {str(key): str(value) for key, value in (preview.get("env_vars") or {}).items()}
    engine = str((((preview.get("database") or {}).get("database_details")) or {}).get("engine") or "").lower()
    aliases = {
        "postgres": {"url": ["DATABASE_URL"], "host": ["PGHOST"], "port": ["PGPORT"]},
        "mysql": {"url": ["DATABASE_URL"], "host": ["MYSQL_HOST"], "port": ["MYSQL_PORT"]},
        "mariadb": {"url": ["DATABASE_URL"], "host": ["MYSQL_HOST"], "port": ["MYSQL_PORT"]},
        "mongodb": {"url": ["MONGODB_URI"], "host": ["MONGO_HOST"], "port": ["MONGO_PORT"]},
        "redis": {"url": ["REDIS_URL"], "host": ["REDIS_HOST"], "port": ["REDIS_PORT"]},
        "qdrant": {"url": ["QDRANT_URL"], "host": ["QDRANT_HOST"], "port": ["QDRANT_PORT"]},
    }.get(engine, {})

    def pick(keys: list[str]) -> str:
        for key in keys:
            if connection_fields.get(key):
                return connection_fields[key]
            if env_vars.get(key):
                return env_vars[key]
        return ""

    return {
        "engine": engine,
        "connection_fields": connection_fields,
        "env_vars": env_vars,
        "url": pick(aliases.get("url", [])),
        "host": pick(aliases.get("host", [])),
        "port": pick(aliases.get("port", [])),
    }


def _patch_compose_env_vars(
    env_vars: dict[str, str],
    *,
    database_contexts: dict[str, dict],
) -> tuple[dict[str, str], list[str]]:
    if not env_vars or not database_contexts:
        return dict(env_vars or {}), []
    patched = dict(env_vars)
    changed: list[str] = []
    for key, value in list(patched.items()):
        original = value
        upper_key = key.upper()
        for service_name, db_ctx in database_contexts.items():
            field_map = db_ctx.get("connection_fields", {})
            db_env = db_ctx.get("env_vars", {})
            url = str(db_ctx.get("url") or "")
            host = str(db_ctx.get("host") or "")
            port = str(db_ctx.get("port") or "")
            aliases = {
                service_name.lower(),
                str(db_ctx.get("app_name") or "").lower(),
                str(db_ctx.get("route_slug") or "").lower(),
            } - {""}
            if upper_key in field_map:
                patched[key] = field_map[upper_key]
                break
            if upper_key in db_env:
                patched[key] = db_env[upper_key]
                break
            if upper_key.endswith("_URL") or upper_key.endswith("_URI") or upper_key == "DATABASE_URL":
                if url and any(alias in value.lower() for alias in aliases):
                    patched[key] = url
                    break
            if upper_key.endswith("_HOST") and host and any(alias == value.lower() for alias in aliases):
                patched[key] = host
                break
            if upper_key.endswith("_PORT") and port and value.isdigit():
                if any(alias in original.lower() for alias in aliases) or upper_key in field_map or upper_key in db_env:
                    patched[key] = port
                    break
            if url and "://" in value and any(alias in value.lower() for alias in aliases):
                patched[key] = url
                break
            if host and any(alias == value.lower() for alias in aliases):
                patched[key] = host
                break
        if patched[key] != original:
            changed.append(key)
    return patched, changed


def _rewrite_single_service_compose_env(compose_yaml: str, env_vars: dict[str, str]) -> str:
    if not compose_yaml or not env_vars:
        return compose_yaml
    compose_data = yaml.safe_load(compose_yaml) or {}
    services = compose_data.get("services") or {}
    if not services:
        return compose_yaml
    service_name = next(iter(services))
    service = deepcopy(services[service_name])
    service["environment"] = dict(env_vars)
    compose_data["services"][service_name] = service
    return yaml.safe_dump(compose_data, sort_keys=False)


async def _check_database_slug_availability(project_id: str, slug: str, exclude_app_id: str = "") -> dict:
    return await _client().get(
        "/v1/plugin/databases/slug-availability/check",
        params={"project_id": project_id, "slug": slug, "exclude_app_id": exclude_app_id or None},
    )


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
        test_tag = f"{prefix}-{_slugify(service)}:test"
        archive = f".pluglayer/{_slugify(service)}.oci.tar"
        context_path = os.path.join(root, context)
        test_build_parts = ["docker", "buildx", "build", "--platform", "linux/amd64", "--load", "-t", test_tag]
        build_parts = ["docker", "buildx", "build", "--platform", "linux/amd64,linux/arm64", "--output", f"type=oci,dest={os.path.join(root, archive)}", "-t", tag]
        if dockerfile:
            test_build_parts.extend(["-f", os.path.join(context_path, dockerfile)])
            build_parts.extend(["-f", os.path.join(context_path, dockerfile)])
        test_build_parts.append(context_path)
        build_parts.append(context_path)
        test_run_parts = ["docker", "run", "--rm"]
        for key, value in (item.get("env_vars") or {}).items():
            test_run_parts.extend(["-e", f"{key}={value}"])
        ports = item.get("ports") or []
        if ports:
            port = ports[0]
            test_run_parts.extend(["-p", f"127.0.0.1:{port}:{port}"])
        test_run_parts.append(test_tag)
        lines.append(f"\n- **{service}**")
        lines.append("  Test build first on a concrete runtime architecture:")
        lines.append(f"  ```sh\n{' '.join(_quote_shell(part) for part in test_build_parts)}\n  ```")
        lines.append("  Then smoke-test the image locally before uploading it:")
        lines.append(f"  ```sh\n{' '.join(_quote_shell(part) for part in test_run_parts)}\n  ```")
        lines.append("  If the container starts correctly, build an architecture-agnostic OCI archive for PlugLayer:")
        lines.append(f"  ```sh\n{' '.join(_quote_shell(part) for part in build_parts)}\n  ```")
        if item.get("command_args"):
            lines.append(f"  Startup args preserved: `{item.get('command_args')}`")
        lines.append(
            "  Then call `deploy_compose(..., local_image_archives={"
            + f"\"{service}\": \"{os.path.join(root, archive)}\""
            + "})`."
        )
    return "\n".join(lines)


async def _preview_database_runtime(
    *,
    template_id: str,
    project_id: str,
    app_name: str,
    route_slug: str,
    env_overrides: dict[str, str],
) -> dict:
    return await _client().post(
        "/v1/plugin/databases/preview",
        {
            "template_id": template_id,
            "project_id": project_id,
            "app_name": app_name,
            "route_slug": route_slug,
            "env_overrides": env_overrides,
        },
    )


async def _find_database_template_for_family(family: str) -> dict | None:
    templates_data = await _client().get("/v1/plugin/databases/templates")
    templates = templates_data.get("templates", [])
    for template in templates:
        engine = ((template.get("database_config") or {}).get("engine") or "").lower()
        if template.get("slug") == family or engine == family:
            return template
    return None


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
                f"- Your database is deployed as **{app_name}**. I can patch **{other.get('name') or 'another app'}** with the new connection env vars using `sync_database_env_to_app()`."
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
