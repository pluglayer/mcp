"""Deployment/app MCP tools backed by PlugLayer v1 apps API.

This compatibility module preserves the original import and registration surface while
the implementations live in focused modules capped at 500 lines.
"""

from pluglayer_mcp.tools.deployment.app_operations import register_app_operations_tools
from pluglayer_mcp.tools.deployment.app_read import register_app_read_tools
from pluglayer_mcp.tools.deployment.catalog import register_catalog_tools
from pluglayer_mcp.tools.deployment.compose import register_compose_tools
from pluglayer_mcp.tools.deployment.connection_sync import register_connection_sync_tools
from pluglayer_mcp.tools.deployment.env_import import register_env_import_tools
from pluglayer_mcp.tools.deployment.databases import register_databases_tools
from pluglayer_mcp.tools.deployment.helpers import (
    _compose_build_commands,
    _find_existing_project_app_match,
)
from pluglayer_mcp.tools.deployment.images import register_images_tools
from pluglayer_mcp.tools.deployment.marketplace import register_marketplace_tools


def register_deployment_tools(mcp):
    register_catalog_tools(mcp)
    register_images_tools(mcp)
    register_compose_tools(mcp)
    register_connection_sync_tools(mcp)
    register_env_import_tools(mcp)
    get_logs = register_app_read_tools(mcp)
    register_marketplace_tools(mcp)
    register_databases_tools(mcp)
    register_app_operations_tools(mcp, get_logs)
