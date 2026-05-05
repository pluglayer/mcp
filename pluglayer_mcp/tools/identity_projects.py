"""Identity Projects MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_task_hint, _status_emoji


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
                f"Roles: {', '.join(roles) if roles else 'none'}\n"
                f"Superadmin: {'yes' if user.get('is_superuser') else 'no'}"
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
        """Get project details. Accessible to the project owner or a PlugLayer admin role."""
        try:
            p = await _client().get(f"/v1/plugin/projects/{project_id}")
            p = p.get("project", p)
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
