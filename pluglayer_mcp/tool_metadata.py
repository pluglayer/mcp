"""Public tool hints and request credential binding; backend owns authorization."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pluglayer_mcp.credentials import reset_remote_api_key, set_remote_api_key

# Explicit allowlist: verbs alone are insufficient (estimates save offers and
# DNS verification updates records). New tools default to potentially destructive.
READ_ONLY = frozenset("""
get_current_user list_projects get_my_projects get_project get_user_context
get_compute_summary get_my_available_compute get_my_available_computes
plan_dedicated_compute get_shared_compute_pricing list_nodes
list_attachable_project_nodes list_pluglayer_compute_options list_registries
list_deployments get_apps_by_project check_slug_availability
analyze_compose_deploy_plan get_compose_local_build_commands get_deployment_status
get_logs get_app_connection_env_vars list_marketplace_templates get_marketplace_template
list_database_templates list_user_databases check_database_slug_availability
get_database_connection_details get_database_logs get_app_logs get_app_access_policy
list_project_domains get_domains_by_project detect_custom_domain_provider get_task_status
inspect_local_github_repo generate_github_actions list_my_feedback get_feedback
list_my_notifications get_template_authoring_schema list_template_categories
preview_template_compose list_my_templates get_template_details get_template_agent_context
list_template_launch_sessions
""".split())

ADDITIVE = frozenset("""
create_project estimate_compute request_extra_compute submit_feedback
create_template_draft clone_template_draft
""".split())


def annotations_for(name: str) -> ToolAnnotations:
    read_only = name in READ_ONLY
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=not read_only and name not in ADDITIVE,
        openWorldHint=name != "inspect_local_github_repo",
    )


class PublicFastMCP(FastMCP):
    async def call_tool(self, name: str, arguments: dict):
        # A stateful HTTP session inherits initialization's ContextVars. The
        # SDK request context, however, follows each tools/call HTTP message.
        try:
            request = self.get_context().request_context.request
        except ValueError:
            request = None
        if request is None:
            return await super().call_tool(name, arguments)
        bearer = getattr(request.state, "pluglayer_api_key", None)
        if not bearer:
            raise RuntimeError("Validated PlugLayer request credential is missing")
        context = set_remote_api_key(bearer)
        try:
            return await super().call_tool(name, arguments)
        finally:
            reset_remote_api_key(context)

    def tool(self, *args, **kwargs):
        def decorate(function):
            options = dict(kwargs)
            options.setdefault("annotations", annotations_for(options.get("name") or function.__name__))
            return super(PublicFastMCP, self).tool(*args, **options)(function)
        return decorate
