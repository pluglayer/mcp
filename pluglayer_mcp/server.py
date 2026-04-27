"""
PlugLayer MCP Server

Exposes PlugLayer project, compute, deployment, CI/CD, and admin tools to AI
assistants through the Model Context Protocol (MCP). The MCP intentionally goes
through the FastAPI backend endpoints so auth, roles, ownership, quotas, compute
checks, k3s orchestration, and admin guards stay in one backend implementation.
"""
import sys

from mcp.server.fastmcp import FastMCP

from pluglayer_mcp.settings import settings

mcp = FastMCP(
    "PlugLayer",
    instructions="""You are the PlugLayer infrastructure operator.
You help users deploy, manage, and monitor applications on PlugLayer.

Current PlugLayer rules:
- Authentik groups are exposed by PlugLayer as user.roles. Do not use groups/permissions fields.
- Admin tools require the user to have pluglayer-admin or pluglayer-superadmin in roles.
- Compute is account-level: personal SSH nodes and shared PlugLayer nodes can be used by all projects the user owns.
- A project is a k3s namespace. A deployment is an app inside a project.
- Custom domains are verified and routed by backend v1 domain endpoints; do not invent DNS or Traefik state.
- Async operations return task IDs; always poll get_task_status until completion.

Deployment workflow:
1. Run get_current_user and get_compute_summary.
2. List or create a project.
3. Ensure can_deploy is true. If false, add a personal SSH node or ask an admin to assign shared compute.
4. Deploy from image or docker-compose.
5. Poll the returned task and report the public URL.

Confirm destructive actions such as delete and rollback before executing them.
""",
)

from pluglayer_mcp.tools.cicd_health import register_cicd_health_tools
from pluglayer_mcp.tools.compute import register_compute_tools
from pluglayer_mcp.tools.deployments import register_deployment_tools
from pluglayer_mcp.tools.domains import register_domain_tools
from pluglayer_mcp.tools.identity_projects import register_identity_project_tools
from pluglayer_mcp.tools.tasks_admin import register_task_admin_tools

register_identity_project_tools(mcp)
register_compute_tools(mcp)
register_deployment_tools(mcp)
register_domain_tools(mcp)
register_task_admin_tools(mcp)
register_cicd_health_tools(mcp)


def main():
    """Entry point for `pluglayer-mcp` command."""
    if not settings.PLUGLAYER_API_KEY:
        print(
            "WARNING: PLUGLAYER_API_KEY not set!\n"
            "Set it as an environment variable:\n"
            "  PLUGLAYER_API_KEY=your-token pluglayer-mcp\n\n"
            "Get your token from: https://portal.pluglayer.com/settings",
            file=sys.stderr,
        )

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
