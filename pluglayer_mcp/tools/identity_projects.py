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
                lines.append(
                    f"{_status_emoji(status)} **{p.get('name')}** (id: `{p.get('id')}`)\n"
                    f"   Status: {status} | Apps: {p.get('deployment_count', 0)}\n"
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
            lines = [
                f"{_status_emoji(status)} **{p.get('name')}**\n"
                f"ID: `{p.get('id')}`\n"
                f"Status: {status}\n"
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
                f"Domains detached or archived: {data.get('domains_archived', 0)}\n"
                f"Namespace cleanup requested: {((data.get('cleanup') or {}).get('namespace_deleted'))}"
            )
        except Exception as e:
            return _compact_error("Error removing project", e)

    @mcp.tool()
    async def delete_project(project_id: str) -> str:
        """Alias for remove_project()."""
        return await remove_project(project_id)
