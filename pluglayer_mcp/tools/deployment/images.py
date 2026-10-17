"""Deployment MCP tool registrations."""

import asyncio
import hashlib
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
from pluglayer_mcp.credentials import resolve_api_base_url
from pluglayer_mcp.tools.shared import (
    _client,
    _compact_error,
    _fmt_task_hint,
    _get_compute_summary,
    _remember_context,
    _status_emoji,
)

_CHUNKED_UPLOAD_THRESHOLD_BYTES = 16 * 1024 * 1024
_CLIENT_CHUNK_SIZE_BYTES = 4 * 1024 * 1024
_MAX_SERVER_CHUNK_BYTES = 32 * 1024 * 1024


def _transient_chunk_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "timed out",
            "timeout",
            "connection",
            "closed",
            "network error",
            "502 ",
            "503 ",
            "504 ",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        )
    )


async def _upload_existing_app_archive(
    client,
    *,
    app_id: str,
    image_archive_path: str,
    tag: str,
    registry_id: str,
    redeploy_strategy: str,
    wait_seconds: int,
    env_vars: dict[str, str] | None = None,
) -> dict:
    size_bytes = os.path.getsize(image_archive_path)
    if size_bytes <= _CHUNKED_UPLOAD_THRESHOLD_BYTES:
        return await client.post_multipart(
            f"/v1/plugin/apps/{app_id}/upload-image-redeploy",
            form_data={
                "tag": tag,
                "registry_id": registry_id or "",
                "redeploy_strategy": redeploy_strategy,
                "wait_seconds": str(wait_seconds),
                "env_vars_json": json.dumps(env_vars or {}),
            },
            file_field="archive",
            file_path=image_archive_path,
            content_type="application/x-tar",
        )

    return await _upload_chunked_archive(
        client,
        image_archive_path=image_archive_path,
        session_path=f"/v1/plugin/apps/{app_id}/image-upload-sessions",
        complete_action="complete-redeploy",
        complete_payload={
            "tag": tag,
            "registry_id": registry_id or None,
            "redeploy_strategy": redeploy_strategy,
            "wait_seconds": wait_seconds,
            "env_vars": env_vars or {},
        },
    )


async def _upload_chunked_archive(
    client,
    *,
    image_archive_path: str,
    session_path: str,
    complete_action: str,
    complete_payload: dict,
) -> dict:
    size_bytes = os.path.getsize(image_archive_path)
    session = await client.post(
        session_path,
        {"filename": os.path.basename(image_archive_path), "size_bytes": size_bytes},
    )
    upload_id = session.get("upload_id")
    server_chunk_size = int(session.get("chunk_size") or 0)
    if not upload_id or server_chunk_size <= 0 or server_chunk_size > _MAX_SERVER_CHUNK_BYTES:
        raise RuntimeError("PlugLayer returned an invalid large-upload session")
    chunk_size = min(server_chunk_size, _CLIENT_CHUNK_SIZE_BYTES)

    offset = 0
    index = 0
    with open(image_archive_path, "rb") as archive:
        while chunk := archive.read(chunk_size):
            digest = hashlib.sha256(chunk).hexdigest()
            path = f"{session_path}/{upload_id}/chunks/{index}"
            for attempt in range(3):
                try:
                    result = await client.put_bytes(
                        path,
                        chunk,
                        headers={
                            "X-Upload-Offset": str(offset),
                            "X-Chunk-SHA256": digest,
                        },
                    )
                    break
                except Exception as exc:
                    if attempt == 2 or not _transient_chunk_error(exc):
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
            offset = int(result.get("received_bytes") or (offset + len(chunk)))
            index += 1

    if offset != size_bytes:
        raise RuntimeError(f"PlugLayer accepted {offset} of {size_bytes} archive bytes")
    return await client.post(
        f"{session_path}/{upload_id}/{complete_action}",
        complete_payload,
        timeout=1800.0,
    )


def _missing_local_archive(image_archive_path: str) -> ValueError:
    return ValueError(
        f"Image archive not found on the PlugLayer MCP host: {image_archive_path}. "
        "Hosted MCP cannot read files on the user's computer. Call begin_local_image_upload(), "
        "PUT the archive from the local machine with the one-time token, then call "
        "complete_local_image_upload()."
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
        storage_gb: int = 0,
        mount_path: str = "/data",
        health_check_path: str = "",
    ) -> str:
        """Deploy a pullable image after private mirroring and backend non-root identity validation. Named users are resolved automatically; root-start custom images need a compatible non-root USER and writable application paths. Requested persistent storage is writable through the app's own volume group. For a local-only image, use upload_image_archive_and_deploy()."""
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
                    data = await _client().post(
                        "/v1/plugin/databases",
                        {
                            "template_id": template.get("id") or template.get("slug"),
                            "project_id": project_id,
                            "app_name": name,
                            "route_slug": route_slug_value,
                            "compute_placement": compute_placement,
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
                raise ValueError(f"Cannot deploy into project `{project_id}` yet: {compute.get('message')} "
                    "Use list_attachable_project_nodes() and attach_node_to_project(), or help the user add compute, then retry.")
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
                    "storage_gb": storage_gb,
                    "mount_path": mount_path,
                    "health_check_path": health_check_path or None,
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
            lines.append("Deployment is queued; rollout time depends on the image and cluster. Ask me to check status when you want an update.")
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
        storage_gb: int = 1,
        mount_path: str = "/data",
        health_check_path: str = "",
    ) -> str:
        """Upload a Docker/OCI archive that is already on this MCP host. Hosted MCP cannot read a path on the user's computer; use begin_local_image_upload() and complete_local_image_upload() for that case. The backend rejects root-start images early, resolves non-root users before rollout, and grants write access only to app-owned persistent storage. If the target app already exists in the project, upload to that app first and redeploy it; otherwise create a new app from the mirrored image."""
        try:
            if not os.path.exists(image_archive_path):
                raise _missing_local_archive(image_archive_path)
            compute = await _get_compute_summary(project_id=project_id)
            if not compute.get("can_deploy"):
                raise ValueError(f"Cannot deploy into project `{project_id}` yet: {compute.get('message')} "
                    "Use list_attachable_project_nodes() and attach_node_to_project(), or help the user add compute, then retry.")
            project_apps = (await _client().get(f"/v1/plugin/projects/{project_id}/apps")).get("apps", [])
            existing_app = _find_existing_project_app_match(project_apps, name=name, route_slug=route_slug)
            if existing_app and existing_app.get("id"):
                data = await _upload_existing_app_archive(
                    _client(),
                    app_id=existing_app.get("id"),
                    image_archive_path=image_archive_path,
                    tag=tag,
                    registry_id=registry_id,
                    redeploy_strategy=redeploy_strategy,
                    wait_seconds=0,
                    env_vars=env_vars,
                )
                task_id = data.get("task_id")
                mirrored = data.get("mirrored_image")
                task_check = data.get("task_check") or {}
                failure_reason = _task_failure_reason(task_check)
                if failure_reason:
                    raise RuntimeError(failure_reason)
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
                    + "Deployment is queued; rollout time depends on the image and cluster. Ask me to check status when you want an update.\n"
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
                "storage_gb": storage_gb,
                "mount_path": mount_path,
                "health_check_path": health_check_path or "",
            }
            if os.path.getsize(image_archive_path) <= _CHUNKED_UPLOAD_THRESHOLD_BYTES:
                data = await _client().post_multipart(
                    f"/v1/plugin/projects/{project_id}/apps/upload-image",
                    form_data=form_data,
                    file_field="archive",
                    file_path=image_archive_path,
                    content_type="application/x-tar",
                )
            else:
                data = await _upload_chunked_archive(
                    _client(),
                    image_archive_path=image_archive_path,
                    session_path=f"/v1/plugin/projects/{project_id}/apps/image-upload-sessions",
                    complete_action="complete-deploy",
                    complete_payload={
                        "deploy_request": {
                            "name": name,
                            "route_slug": route_slug or None,
                            "compute_placement": compute_placement,
                            "redeploy_strategy": redeploy_strategy,
                            "registry_id": registry_id or None,
                            "source": {
                                "type": "image",
                                "image": "uploaded-archive",
                                "tag": tag,
                                "ports": ports or [],
                                "env_vars": env_vars or {},
                                "command_args": command_args or [],
                                "replicas": replicas,
                                "cpu_limit": cpu_limit,
                                "memory_limit": memory_limit,
                                "storage_gb": storage_gb,
                                "mount_path": mount_path,
                                "health_check_path": health_check_path or None,
                            },
                        },
                        "wait_seconds": 0,
                    },
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
            lines.append("Deployment is queued; rollout time depends on the image and cluster. Ask me to check status when you want an update.")
            lines.append(_fmt_task_hint(task_id))
            lines.extend(_post_deploy_suggestions(app, project_apps))
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Uploaded image deployment failed", e)

    @mcp.tool()
    async def upload_image_archive_and_redeploy_app(
        app_id: str,
        image_archive_path: str,
        tag: str = "latest",
        registry_id: str = "",
        redeploy_strategy: str = "recreate",
        wait_seconds: int = 0,
        env_vars: dict[str, str] | None = None,
    ) -> str:
        """Rebuild flow for existing apps when the archive is already on this MCP host. Hosted MCP cannot read the user's computer; use begin_local_image_upload(app_id=...) and complete_local_image_upload() instead. This pushes a new tag, keeps the current slug, and redeploys the existing app."""
        try:
            if not os.path.exists(image_archive_path):
                raise _missing_local_archive(image_archive_path)
            app_data = await _client().get(f"/v1/plugin/apps/{app_id}")
            app = app_data.get("app", {})
            data = await _upload_existing_app_archive(
                _client(),
                app_id=app_id,
                image_archive_path=image_archive_path,
                tag=tag,
                registry_id=registry_id,
                redeploy_strategy=redeploy_strategy,
                wait_seconds=wait_seconds,
                env_vars=env_vars,
            )
            task_id = data.get("task_id")
            mirrored = data.get("mirrored_image")
            task_check = data.get("task_check") or {}
            failure_reason = _task_failure_reason(task_check)
            if failure_reason:
                raise RuntimeError(failure_reason)
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
            return _compact_error("Uploaded image redeploy failed", e)

    @mcp.tool()
    async def begin_local_image_upload(
        filename: str,
        size_bytes: int,
        project_id: str = "",
        app_id: str = "",
    ) -> str:
        """Start an upload for an image archive that exists only on the user's computer. Returns a one-time chunk token. Do not repeat that token to the user. PUT the bytes locally, then call complete_local_image_upload()."""
        try:
            if bool(project_id) == bool(app_id):
                raise ValueError("Pass exactly one of project_id (new app) or app_id (existing app)")
            if size_bytes < 1 or size_bytes > 20 * 1024 * 1024 * 1024:
                raise ValueError("Archive size must be between 1 byte and 20 GB")
            safe_name = os.path.basename(filename.strip()) or "image.oci.tar"
            if project_id:
                session_path = f"/v1/plugin/projects/{project_id}/apps/image-upload-sessions"
                scope = "project"
                scope_id = project_id
            else:
                session_path = f"/v1/plugin/apps/{app_id}/image-upload-sessions"
                scope = "app"
                scope_id = app_id
            session = await _client().post(
                session_path,
                {
                    "filename": safe_name,
                    "size_bytes": size_bytes,
                    "issue_client_upload_token": True,
                },
            )
            token = session.get("client_upload_token")
            upload_id = session.get("upload_id")
            chunk_size = int(session.get("chunk_size") or 0)
            if not token or not upload_id or chunk_size <= 0:
                raise RuntimeError(
                    "This PlugLayer API did not issue a client upload token. Deploy the current backend "
                    "before using hosted local-image upload, or use GitHub Actions."
                )
            api_base_url = resolve_api_base_url().rstrip("/")
            return "\n".join(
                [
                    "Local image upload session is ready. Upload the archive from the user's machine, then call complete_local_image_upload().",
                    "Do not show client_upload_token to the user or put it on a command line. Pass it only as X-Pluglayer-Upload-Token.",
                    f"api_base_url: {api_base_url}",
                    f"upload_url: {api_base_url}/v1/plugin/image-uploads/{upload_id}/chunks/{{index}}",
                    f"upload_id: {upload_id}",
                    f"scope: {scope}",
                    f"scope_id: {scope_id}",
                    f"filename: {safe_name}",
                    f"size_bytes: {size_bytes}",
                    f"chunk_size: {chunk_size}",
                    f"expires_at: {session.get('expires_at')}",
                    f"client_upload_token: {token}",
                ]
            )
        except Exception as e:
            return _compact_error("Could not start the local image upload", e)

    @mcp.tool()
    async def complete_local_image_upload(
        upload_id: str,
        project_id: str = "",
        app_id: str = "",
        name: str = "",
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
        storage_gb: int = 1,
        mount_path: str = "/data",
        health_check_path: str = "",
        wait_seconds: int = 0,
    ) -> str:
        """Finish a begin_local_image_upload session after every local chunk succeeded. project_id creates an app. app_id redeploys the existing app and keeps its slug."""
        try:
            if bool(project_id) == bool(app_id):
                raise ValueError("Pass exactly one of project_id (new app) or app_id (existing app)")
            if app_id:
                data = await _client().post(
                    f"/v1/plugin/apps/{app_id}/image-upload-sessions/{upload_id}/complete-redeploy",
                    {
                        "tag": tag,
                        "registry_id": registry_id or None,
                        "redeploy_strategy": redeploy_strategy,
                        "wait_seconds": wait_seconds,
                        "env_vars": env_vars or {},
                    },
                    timeout=1800.0,
                )
                task_id = data.get("task_id")
                failure_reason = _task_failure_reason(data.get("task_check") or {})
                if failure_reason:
                    raise RuntimeError(failure_reason)
                mirrored = data.get("mirrored_image")
                return (
                    f"🔄 Uploaded image redeploy queued for app `{app_id}`.\n"
                    f"New image tag: `{tag}`\n"
                    + (f"Mirrored image: `{mirrored}`\n" if mirrored else "")
                    + f"Task ID: `{task_id}`\n"
                    + _fmt_task_hint(task_id)
                )
            if not name.strip():
                raise ValueError("name is required when creating an app from a local image upload")
            data = await _client().post(
                f"/v1/plugin/projects/{project_id}/apps/image-upload-sessions/{upload_id}/complete-deploy",
                {
                    "deploy_request": {
                        "name": name,
                        "route_slug": route_slug or None,
                        "compute_placement": compute_placement,
                        "redeploy_strategy": redeploy_strategy,
                        "registry_id": registry_id or None,
                        "source": {
                            "type": "image",
                            "image": "uploaded-archive",
                            "tag": tag,
                            "ports": ports or [],
                            "env_vars": env_vars or {},
                            "command_args": command_args or [],
                            "replicas": replicas,
                            "cpu_limit": cpu_limit,
                            "memory_limit": memory_limit,
                            "storage_gb": storage_gb,
                            "mount_path": mount_path,
                            "health_check_path": health_check_path or None,
                        },
                    },
                    "wait_seconds": wait_seconds,
                },
                timeout=1800.0,
            )
            task_id = data.get("task_id")
            app = data.get("app", {})
            mirrored = data.get("mirrored_image")
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "complete_local_image_upload",
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
            lines.append(_fmt_task_hint(task_id))
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Local image upload could not be completed", e)
