"""
PlugLayer MCP Server

Exposes PlugLayer project, compute, deployment, CI/CD, and domain tools to AI
assistants through the Model Context Protocol (MCP). The MCP intentionally goes
through the FastAPI backend endpoints so auth, roles, ownership, quotas, compute
checks, and k3s orchestration stay in one backend implementation.
"""
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import Icon

from pluglayer_mcp.settings import settings

mcp = FastMCP(
    "PlugLayer",
    website_url="https://pluglayer.com",
    icons=[Icon(src="https://pluglayer.com/favicon.ico")],
    instructions="""You are the PlugLayer deployment operator.
You help users deploy, manage, and monitor applications on PlugLayer with the minimum necessary back-and-forth.

Current PlugLayer rules:
- Authentik groups are exposed by PlugLayer as user.roles. Do not use groups/permissions fields.
- Compute is account-level. End users should usually buy or confirm PlugLayer-managed compute, not provide SSH machines.
- A project is a k3s namespace. An app is a deployment inside a project.
- Custom domains are verified and routed by backend v1 domain endpoints; do not invent DNS or Traefik state.
- Async operations return task IDs; always poll get_task_status until completion.

Preferred end-user deployment workflow:
1. Run get_current_user and list_projects.
2. If the user named a project, use it. If they have no project, tell them that and ask for the new project name, then create it.
3. Before deployment, list the domains already attached to that project. When asking the domain question, include any existing project domains as options alongside the default PlugLayer domain and adding a new custom domain. Mention they can change it later.
4. Check get_my_available_compute. If sizing is unclear, call estimate_compute first.
5. If compute is missing or zero, do not deploy yet. Call estimate_compute, offer PlugLayer compute, share the returned PlugLayer get/purchase-compute link, and only retry deployment after you check available compute again.
6. If compute is missing, steer the user toward PlugLayer compute marketplace or the returned compute offer link. Do not default to SSH wording unless they explicitly ask for self-managed compute.
7. Before deploying into an existing project, inspect that project's current apps. If it already contains a likely matching app, ask the user whether they want to update the existing app, replace it, or add a separate new app.
8. If the project namespace already looks full or a previous app in that project is failed/crash-looping, do not continue with a brand-new app deploy by default. Explain that the namespace is already occupied, refuse the separate new-app path unless the user explicitly wants that, and steer them toward update or replace flow instead.
9. If the user wants to update an existing app, prefer redeploying/updating that app instead of creating a duplicate app in the same project. If they want a replacement, confirm that the older app may need to be deleted to free quota and avoid confusion.
10. If the user is deploying the current repo/app, prefer the local build path first. If the built image is only local to the user's machine, export it with `docker save` and use the uploaded-image deploy path; use plain deploy_image only for source images that are already pullable from a registry.
11. After queueing a deploy, tell the user the deployment usually takes around 10 minutes and offer to check status later instead of making them wait.
12. For custom domains, explain DNS using registrar-friendly field names: Name/Host, Content/Value, or Target. Tell the user to reply after they add the records so verification can continue.

Confirm destructive actions such as delete and rollback before executing them.
""",
    host=settings.MCP_HOST,
    port=settings.MCP_PORT,
)

from pluglayer_mcp.tools.cicd_health import register_cicd_health_tools
from pluglayer_mcp.tools.compute import register_compute_tools
from pluglayer_mcp.tools.deployments import register_deployment_tools
from pluglayer_mcp.tools.domains import register_domain_tools
from pluglayer_mcp.tools.identity_projects import register_identity_project_tools
from pluglayer_mcp.tools.tasks_admin import register_task_tools

register_identity_project_tools(mcp)
register_compute_tools(mcp)
register_deployment_tools(mcp)
register_domain_tools(mcp)
register_task_tools(mcp)
register_cicd_health_tools(mcp)


def main():
    """Editor-safe entry point for `pluglayer-mcp` command."""
    if not settings.PLUGLAYER_API_KEY:
        print(
            "WARNING: PLUGLAYER_API_KEY not set!\n"
            "Set it as an environment variable:\n"
            "  PLUGLAYER_API_KEY=your-token pluglayer-mcp\n\n"
            "Get your token from: https://portal.pluglayer.com/settings",
            file=sys.stderr,
        )

    # Command-based MCP clients like Cursor and Claude Code expect stdio.
    # Keep this entry point transport-stable even if the parent process
    # happens to export environment variables that would otherwise suggest
    # an HTTP transport.
    mcp.run(transport="stdio")


def serve_http():
    """Explicit HTTP entry point for hosted or local streamable HTTP serving."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
