"""Identity Projects MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_task_hint, _status_emoji


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
        """List authenticated user's projects. Normal users see their projects; admins may see admin data via admin tools."""
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
            status = p.get("status", "unknown")
            return (
                f"{_status_emoji(status)} **{p.get('name')}**\n"
                f"ID: `{p.get('id')}`\n"
                f"Status: {status}\n"
                f"Namespace: `{p.get('namespace')}`\n"
                f"URL pattern: {p.get('base_url', 'N/A')}\n"
                f"Apps: {p.get('deployment_count', 0)}\n"
                "Compute is account-level; use get_compute_summary() for available capacity."
            )
        except Exception as e:
            return _compact_error("Error getting project", e)
