"""Read-only real template smoke through the local public or Admin MCP over stdio.

Credentials are resolved from each surface's existing environment/private file and
injected into the child at runtime. No tokens, template content, or reports are printed.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_TOOLS = {
    'get_template_authoring_schema', 'list_template_categories', 'preview_template_compose',
    'list_my_templates', 'get_template_details', 'create_template_draft', 'update_template_draft',
    'clone_template_draft', 'delete_template_draft', 'submit_template_for_approval',
    'get_template_agent_context', 'run_template_agent', 'plan_template_launch',
    'create_template_launch_session', 'list_template_launch_sessions', 'update_app_from_template',
    'deploy_marketplace_template',
}
ADMIN_TOOLS = {
    'get_template_authoring_schema', 'list_marketplace_templates', 'get_marketplace_template',
    'preview_template_compose', 'create_marketplace_template', 'update_marketplace_template',
    'clone_marketplace_template', 'publish_marketplace_template', 'delete_marketplace_template',
    'refresh_system_templates', 'list_template_submissions', 'decide_template_submission',
}


def parameters(admin: bool) -> StdioServerParameters:
    if admin:
        folder = ROOT / 'pluglayer-admin/mcp'
        sys.path.insert(0, str(folder))
        from pluglayer_admin_mcp.credentials import resolve_api_key, resolve_api_url
        key, url = resolve_api_key(), resolve_api_url()
        env = {'PLUGLAYER_ADMIN_API_KEY': key, 'PLUGLAYER_ADMIN_API_URL': url}
        module = 'pluglayer_admin_mcp.server'
    else:
        folder = ROOT / 'pluglayer-mcp'
        sys.path.insert(0, str(folder))
        from pluglayer_mcp.credentials import resolve_api_key, resolve_api_base_url
        key, url = resolve_api_key(), resolve_api_base_url()
        env = {'PLUGLAYER_API_KEY': key, 'PLUGLAYER_API_URL': url}
        module = 'pluglayer_mcp.server'
    env['PYTHONPATH'] = str(folder)
    return StdioServerParameters(command=sys.executable, args=['-m', module], env=env)


async def run(admin: bool) -> int:
    failures = []
    server = parameters(admin)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            missing = (ADMIN_TOOLS if admin else PUBLIC_TOOLS) - names
            if missing:
                print(f'Missing tools: {sorted(missing)}')
                return 1
            print(f'Template tool registration: PASS ({len(names)} total tools)')
            calls = (
                [('get_admin_capabilities', {}), ('list_template_submissions', {'payload': {}}),
                 ('list_marketplace_templates', {'payload': {'limit': 1}}), ('get_template_authoring_schema', {'payload': {}})]
                if admin else
                [('get_current_user', {}), ('get_template_authoring_schema', {}),
                 ('list_my_templates', {}), ('list_template_categories', {})]
            )
            for name, payload in calls:
                result = await session.call_tool(name, payload)
                content = '\n'.join(item.text for item in result.content if hasattr(item, 'text'))
                failed = bool(result.isError) or content.lower().startswith('error ')
                if failed:
                    failures.append(name)
                    # Do not print backend payloads, which can contain private template data.
                    status = next((str(code) for code in (401,403,404,409,422,500,502,503) if str(code) in content), 'unknown')
                    print(f'{name}: FAIL (status {status}; backend response withheld)')
                else:
                    print(f'{name}: PASS')
            return 1 if failures else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin', action='store_true')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.admin)))
