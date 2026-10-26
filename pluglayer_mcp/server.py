"""
PlugLayer MCP Server

Exposes PlugLayer project, compute visibility, deployment, CI/CD, and domain tools to AI
assistants through the Model Context Protocol (MCP). The MCP intentionally goes
through the FastAPI backend endpoints so auth, roles, ownership, quotas, compute
checks, and k3s orchestration stay in one backend implementation.
"""
import sys

from pluglayer_mcp.tool_metadata import PublicFastMCP
from mcp.types import Icon

from pluglayer_mcp.credentials import is_api_key_configured
from pluglayer_mcp.settings import settings

mcp = PublicFastMCP(
    "PlugLayer",
    website_url="https://pluglayer.com",
    icons=[Icon(src="https://pluglayer.com/pluglayer-icon.png")],
    instructions="""Use PlugLayer tools for PlugLayer requests; no browser. Leave unrelated work alone.
list_projects lists projects; get_task_status polls jobs. Run setup only to install, update, or reconnect.
For prompt:<slug>, call apply_prompt with that exact ID and apply it to the user's following task. Before app work read get_agents_md; maintain governance after meaningful changes using manage-knowledge. Use workflow skills. Confirm delete/rollback. No admin tools.
""",
    host=settings.MCP_HOST,
    port=settings.MCP_PORT,
)

from pluglayer_mcp.tools.cicd_health import register_cicd_health_tools
from pluglayer_mcp.tools.github_cicd import register_github_cicd_tools
from pluglayer_mcp.tools.compute import register_compute_tools
from pluglayer_mcp.tools.deployments import register_deployment_tools
from pluglayer_mcp.tools.domains import register_domain_tools
from pluglayer_mcp.tools.feedback import register_feedback_tools
from pluglayer_mcp.tools.notifications import register_notification_tools
from pluglayer_mcp.tools.templates import register_template_tools
from pluglayer_mcp.tools.identity_projects import register_identity_project_tools
from pluglayer_mcp.tools.tasks_admin import register_task_tools
from pluglayer_mcp.tools.user_context import register_user_context_tools
from pluglayer_mcp.tools.knowledge import register_knowledge_tools

register_identity_project_tools(mcp)
register_user_context_tools(mcp)
register_knowledge_tools(mcp)
register_compute_tools(mcp)
register_deployment_tools(mcp)
register_domain_tools(mcp)
register_task_tools(mcp)
register_cicd_health_tools(mcp)
register_github_cicd_tools(mcp)
register_feedback_tools(mcp)
register_notification_tools(mcp)
register_template_tools(mcp)


def main():
    """Editor-safe entry point for `pluglayer-mcp` command."""
    if not is_api_key_configured():
        print(
            "WARNING: PlugLayer authentication is not configured.\n"
            "Save PLUGLAYER_API_KEY in ~/.pluglayer/credentials.env or set it "
            "in the MCP server environment.\n"
            "The server will stay available and read saved credentials on the "
            "next tool call; no reload is required.\n"
            "Client OAuth/mcp_auth actions do not configure local stdio auth.\n\n"
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
    from pluglayer_mcp.remote import serve
    serve()


if __name__ == "__main__":
    main()
