"""Verify actual FastMCP schemas and HTTP transport for template operations."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from pluglayer_mcp.tools import templates
from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp import client as client_module


def make_server(monkeypatch, client):
    monkeypatch.setattr(templates, '_client', lambda: client)
    mcp = FastMCP('template-tests')
    templates.register_template_tools(mcp)
    return mcp


@pytest.mark.asyncio
async def test_template_roundtrip_uses_plugin_auth_and_preserves_nested_fields(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Bearer test-token'
        return httpx.Response(200, json={'ok': True, 'data': {'template': {'id': 'template-1', 'approval_status': 'draft'}}})
    factory = httpx.AsyncClient
    monkeypatch.setattr(client_module.httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))
    mcp = make_server(monkeypatch, PlugLayerClient(api_key='test-token', base_url='https://api.example.test'))
    payload = {'name': 'Demo', 'description': 'Demo', 'category': 'tools', 'compose_yaml': 'services: {}',
               'exposure_config': {'type': 'internal'}, 'template_env_vars': [{'key': 'PASSWORD', 'value': '{{RANDOM_PASSWORD}}'}]}
    await mcp.call_tool('create_template_draft', {'template': payload, 'save_mode': 'test'})
    await mcp.call_tool('update_template_draft', {'template_id': 'template-1', 'updates': {'tags': []}})
    await mcp.call_tool('submit_template_for_approval', {'template_id': 'template-1', 'test_report': {'compose': 'passed'}, 'notes': 'Please review'})
    await mcp.call_tool('get_template_details', {'template_id': 'template-1'})
    assert [request.method for request in requests] == ['POST', 'PUT', 'POST', 'GET']
    assert requests[0].url.path == '/v1/plugin/templates'
    assert json.loads(requests[0].content) == {'template': payload, 'save_mode': 'test'}
    assert json.loads(requests[1].content) == {'tags': []}
    assert json.loads(requests[2].content)['test_report'] == {'compose': 'passed'}
    assert requests[3].url.path == '/v1/plugin/templates/template-1'


@pytest.mark.asyncio
async def test_all_public_template_tools_are_registered_without_admin_actions(monkeypatch):
    mcp = make_server(monkeypatch, AsyncMock())
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert len(tools) == 16
    assert {'get_template_authoring_schema', 'preview_template_compose', 'clone_template_draft',
            'delete_template_draft', 'submit_template_for_approval', 'list_my_templates',
            'create_template_launch_session', 'list_template_launch_sessions', 'plan_template_launch',
            'run_template_agent', 'update_app_from_template'} <= tools.keys()
    assert not {'decide_template_submission', 'publish_marketplace_template', 'refresh_system_templates'} & tools.keys()
    assert tools['create_template_draft'].inputSchema['properties']['save_mode']['enum'] == ['draft', 'test']
    assert tools['delete_template_draft'].inputSchema['required'] == ['template_id', 'confirmation']


@pytest.mark.asyncio
async def test_backend_rejection_stays_an_mcp_error(monkeypatch):
    client = AsyncMock()
    client.post.side_effect = RuntimeError('409 Conflict: Template is already approved')
    mcp = make_server(monkeypatch, client)
    with pytest.raises(Exception, match='already approved'):
        await mcp.call_tool('submit_template_for_approval', {'template_id': 'template-1'})


@pytest.mark.asyncio
async def test_delete_and_launch_preserve_exact_inputs(monkeypatch):
    client = AsyncMock()
    client.post.return_value = {'task_id': 'task-1'}
    client.get.return_value = {'sessions': []}
    mcp = make_server(monkeypatch, client)
    await mcp.call_tool('delete_template_draft', {'template_id': 'template-1', 'confirmation': 'DELETE TEMPLATE template-1'})
    client.post.assert_awaited_with('/v1/plugin/templates/template-1/delete', {'confirmation': 'DELETE TEMPLATE template-1'})
    await mcp.call_tool('plan_template_launch', {'template_id': 'template-1', 'project_id': 'project-1', 'session_id': 'session-1'})
    assert client.post.call_args.args[1]['session_id'] == 'session-1'
    await mcp.call_tool('update_app_from_template', {'app_id': 'app-1'})
    client.post.assert_awaited_with('/v1/plugin/apps/app-1/template/update')
    await mcp.call_tool('list_template_launch_sessions', {'template_id': 'template-1', 'project_id': 'project-1'})
    client.get.assert_awaited_with('/v1/plugin/templates/sessions', params={'template_id': 'template-1', 'project_id': 'project-1'})


@pytest.mark.asyncio
async def test_template_deploy_preserves_backend_database_binding_resolution(monkeypatch):
    from pluglayer_mcp.tools.deployment import marketplace
    client = AsyncMock()
    client.get.return_value = {'template': {'template_env_vars': [
        {'key': 'DATABASE_PASSWORD', 'value': 'stale-compose-password', 'required': True,
         'sensitive': True, 'database_binding': {'engine': 'postgres', 'key': 'password'}}
    ]}}
    client.post.return_value = {'task_id': 'task-1', 'app': {'id': 'app-1'}}
    monkeypatch.setattr(marketplace, '_client', lambda: client)
    monkeypatch.setattr(marketplace, '_get_compute_summary', AsyncMock(return_value={'can_deploy': True}))
    monkeypatch.setattr(marketplace, '_remember_context', AsyncMock())
    mcp = FastMCP('template-deploy-test')
    marketplace.register_marketplace_tools(mcp)
    await mcp.call_tool('deploy_marketplace_template', {
        'template_id': 'template-1', 'app_name': 'Demo', 'project_id': 'project-1',
        'database_bindings': {'DATABASE_PASSWORD': 'database-1'},
    })
    payload = client.post.call_args.args[1]
    assert payload['database_bindings'] == {'DATABASE_PASSWORD': 'database-1'}
    assert 'DATABASE_PASSWORD' not in payload['env_overrides']
