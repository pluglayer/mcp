"""Identity Projects MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_task_hint, _remember_context, _status_emoji


def _domain_line(domain: dict) -> str:
    hostname = domain.get("domain") or "unknown-domain"
    status = domain.get("status", "unknown")
    mode = domain.get("mode", "single")
    app_id = domain.get("app_id") or "unattached"
    dns = domain.get("dns") or {}
    verified = "yes" if dns.get("verified") else "no"
    return (
        f"- **{hostname}** — status: {status} | mode: {mode} | attached app: `{app_id}` | DNS verified: {verified}"
    )


def register_identity_project_tools(mcp):
    # ── Identity / roles ─────────────────────────────────────────────────────────


    @mcp.tool()
    async def get_current_user() -> str:
        """Show the authenticated PlugLayer user and roles from Authentik."""
        try:
            payload = await _client().get("/v1/plugin/me")
            user = payload.get("user", payload)
            roles = user.get("roles") or []
            return (
                "👤 **Current PlugLayer user**\n"
                f"Email: {user.get('email')}\n"
                f"Username: {user.get('username')}\n"
                f"Roles: {', '.join(roles) if roles else 'none'}"
            )
        except Exception as e:
            return _compact_error("Error loading current user", e)


    # ── Projects ──────────────────────────────────────────────────────────────────


    @mcp.tool()
    async def list_projects() -> str:
        """List the authenticated user's projects."""
        try:
            data = await _client().get("/v1/plugin/projects")
            projects = data.get("projects", [])
            if not projects:
                return "No projects found. Create one with create_project()."
            lines = ["Your projects:\n"]
            for p in projects:
                status = p.get("status", "unknown")
                role = p.get("access_role") or ("owner" if p.get("is_owner", True) else "read")
                scope = "shared with me" if p.get("shared_with_me") else "owned"
                action_hint = "read/write actions allowed" if role in {"owner", "write"} else "read-only"
                lines.append(
                    f"{_status_emoji(status)} **{p.get('name')}** (id: `{p.get('id')}`)\n"
                    f"   Status: {status} | Apps: {p.get('deployment_count', 0)} | Access: {role} ({scope}; {action_hint})\n"
                    f"   Description: {p.get('description') or 'not set'}\n"
                    f"   Namespace: `{p.get('namespace')}`\n"
                    f"   URL pattern: {p.get('base_url', 'N/A')}\n"
                )
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error listing projects", e)


    @mcp.tool()
    async def get_my_projects() -> str:
        """Alias for list_projects() using end-user wording."""
        return await list_projects()


    @mcp.tool()
    async def create_project(name: str, description: str = "", domain_type: str = "pluglayer") -> str:
        """
        Create a PlugLayer project namespace. Project creation only requires authentication.
        Deployment still requires account-level compute; check get_compute_summary before deploying.
        """
        try:
            data = await _client().post("/v1/plugin/projects", {
                "name": name,
                "description": description,
                "domain_type": domain_type,
            })
            project = data.get("project", {})
            task_id = data.get("task_id")
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "create_project",
                        "project_id": project.get("id"),
                        "project_name": project.get("name", name),
                    },
                    "projects": {
                        project.get("id"): {
                            "name": project.get("name", name),
                            "namespace": project.get("namespace"),
                        }
                    },
                }
            )
            return (
                f"✅ Project **{project.get('name', name)}** created.\n"
                f"Project ID: `{project.get('id')}`\n"
                f"Namespace: `{project.get('namespace')}`\n"
                f"Task ID: `{task_id}`\n\n"
                f"⏳ Setting up namespace. {_fmt_task_hint(task_id)}"
            )
        except Exception as e:
            return _compact_error("Error creating project", e)


    @mcp.tool()
    async def rename_project(project_id: str, new_name: str) -> str:
        """
        Rename a PlugLayer project's display name.

        This does not change the project's slug, Kubernetes namespace, or existing app URLs.
        """
        try:
            clean_name = new_name.strip()
            if len(clean_name) < 2 or len(clean_name) > 50:
                return "❌ Project name must be between 2 and 50 characters."
            data = await _client().patch(
                f"/v1/plugin/projects/{project_id}",
                {"name": clean_name},
            )
            project = data.get("project", data)
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "rename_project",
                        "project_id": project_id,
                        "project_name": project.get("name", clean_name),
                    },
                    "projects": {
                        project_id: {
                            "name": project.get("name", clean_name),
                            "namespace": project.get("namespace"),
                        }
                    },
                }
            )
            return (
                f"✅ Project renamed to **{project.get('name', clean_name)}**.\n"
                f"Project ID: `{project_id}`\n"
                f"Slug unchanged: `{project.get('slug', 'unknown')}`\n"
                f"Namespace unchanged: `{project.get('namespace', 'unknown')}`\n\n"
                "Existing app URLs are unchanged."
            )
        except Exception as e:
            return _compact_error("Error renaming project", e)


    @mcp.tool()
    async def update_project_metadata(
        project_id: str,
        name: str = "",
        description: str = "",
        clear_description: bool = False,
    ) -> str:
        """Update a project's display name and/or description.

        The caller must have project write access. Set clear_description=true to remove the
        current description. This never changes the project slug, Kubernetes namespace,
        existing app URLs, or custom-domain routing; use the domain tools for domains.
        """
        clean_project_id = (project_id or "").strip()
        if not clean_project_id:
            return "❌ Project ID is required."

        updates = {}
        if name:
            clean_name = name.strip()
            if len(clean_name) < 2 or len(clean_name) > 50:
                return "❌ Project name must be between 2 and 50 characters."
            updates["name"] = clean_name
        if clear_description and description:
            return "❌ Provide a description or set clear_description=true, not both."
        if clear_description:
            updates["description"] = ""
        elif description:
            clean_description = description.strip()
            if not clean_description:
                return "❌ Use clear_description=true to remove the project description."
            updates["description"] = clean_description
        if not updates:
            return "❌ Provide a project name, description, or clear_description=true."

        try:
            data = await _client().patch(
                f"/v1/plugin/projects/{clean_project_id}",
                updates,
            )
            project = data.get("project", data)
            await _remember_context(
                {
                    "last_completed_task": {
                        "type": "update_project_metadata",
                        "project_id": clean_project_id,
                        "project_name": project.get("name"),
                    },
                    "projects": {
                        clean_project_id: {
                            "name": project.get("name"),
                            "description": project.get("description"),
                            "namespace": project.get("namespace"),
                        }
                    },
                }
            )
            return (
                "✅ Project metadata updated.\n"
                f"Project: **{project.get('name', updates.get('name', 'unknown'))}** (`{clean_project_id}`)\n"
                f"Description: {project.get('description') or 'not set'}\n"
                f"Slug unchanged: `{project.get('slug', 'unknown')}`\n"
                f"Namespace unchanged: `{project.get('namespace', 'unknown')}`\n\n"
                "Existing app URLs and custom-domain routing are unchanged."
            )
        except Exception as e:
            return _compact_error("Error updating project metadata", e)


    @mcp.tool()
    async def get_project(project_id: str) -> str:
        """Get project details for one of the authenticated user's projects."""
        try:
            p = await _client().get(f"/v1/plugin/projects/{project_id}")
            p = p.get("project", p)
            apps_payload = await _client().get(f"/v1/plugin/projects/{project_id}/apps")
            apps = apps_payload.get("apps", [])
            domains_payload = await _client().get(f"/v1/plugin/projects/{project_id}/domains")
            domains = domains_payload.get("domains", [])
            status = p.get("status", "unknown")
            role = p.get("access_role") or ("owner" if p.get("is_owner", True) else "read")
            lines = [
                f"{_status_emoji(status)} **{p.get('name')}**\n"
                f"ID: `{p.get('id')}`\n"
                f"Status: {status}\n"
                f"Access: {role}{' (shared with me)' if p.get('shared_with_me') else ' (owned)'}\n"
                f"Description: {p.get('description') or 'not set'}\n"
                f"Namespace: `{p.get('namespace')}`\n"
                f"URL pattern: {p.get('base_url', 'N/A')}\n"
                f"Apps: {p.get('deployment_count', 0)}"
            ]
            if apps:
                lines.append("\n📦 **Existing Apps**")
                for app in apps:
                    app_status = app.get("status", "unknown")
                    lines.append(
                        f"- {_status_emoji(app_status)} **{app.get('name')}** (`{app.get('id')}`) — status: {app_status} | URL: {app.get('primary_url') or 'not yet available'}"
                    )
                lines.append(
                    "\nBefore deploying another app into this project, check whether the user means to update one of these apps, replace one of them, or add a separate new app."
                )
            else:
                lines.append("\nNo apps are deployed in this project yet.")
            if domains:
                lines.append("\n🌐 **Domains**")
                lines.extend(_domain_line(domain) for domain in domains)
                has_ready_domain = any(domain.get("status") in {"verified", "active"} for domain in domains)
                if has_ready_domain:
                    lines.append(
                        "\nAt least one custom domain is already verified or active, so the user usually does not need to go through domain configuration again unless they want to change domains."
                    )
                else:
                    lines.append(
                        "\nCustom domain records exist, but they are not ready yet. Check the listed status before asking the user to change DNS again."
                    )
            else:
                lines.append("\nNo custom domains are attached to this project yet.")
            lines.append("\nCompute is account-level; use get_compute_summary() for available capacity.")
            return "\n".join(lines)
        except Exception as e:
            return _compact_error("Error getting project", e)

    @mcp.tool()
    async def remove_project(project_id: str) -> str:
        """Remove one of the authenticated user's projects. PlugLayer removes the project's apps first, then tears down the project and archives the record for recovery/history."""
        try:
            data = await _client().delete(f"/v1/plugin/projects/{project_id}")
            await _remember_context({"last_completed_task": {"type": "remove_project", "project_id": project_id}})
            return (
                f"🧹 Project `{project_id}` removed from active use.\n"
                f"Apps removed first: {data.get('apps_removed', data.get('deployments_terminated', 0))}\n"
                f"Domains detached: {data.get('domains_detached', data.get('domains_archived', 0))}\n"
                f"Namespace cleanup requested: {((data.get('cleanup') or {}).get('namespace_deleted'))}"
            )
        except Exception as e:
            return _compact_error("Error removing project", e)

    @mcp.tool()
    async def delete_project(project_id: str) -> str:
        """Alias for remove_project()."""
        return await remove_project(project_id)
