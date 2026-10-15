"""Opt-in production private template version update and public HTTP verification."""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'pluglayer-mcp'))
from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.credentials import resolve_api_base_url, resolve_api_key


async def run(args):
    client = PlugLayerClient()
    identity = await client.get('/v1/plugin/me')
    assert identity.get('user', identity)['username'] in {'basithedev', 'basithedev@gmail.com'}
    before = (await client.get('/v1/plugin/user-context')).get('data', {})
    rows, drafts = [], []
    prefix = 'zz-update-'+uuid4().hex[:8]
    env = {'PYTHONPATH': str(ROOT/'pluglayer-mcp'), 'PLUGLAYER_API_KEY': resolve_api_key(),
        'PLUGLAYER_API_URL': resolve_api_base_url(), 'PLUGLAYER_CREDENTIALS_FILE': str(ROOT/'.readiness-no-credentials')}

    def record(tool, ok, **details):
        rows.append({'tool': tool, 'status': 'PASS' if ok else 'FAIL', **details})
        args.output.write_text(json.dumps({'account': 'basithedev', 'cases': rows}, indent=2)+'\n')
        print(('PASS' if ok else 'FAIL')+': '+tool, flush=True)

    async def apps():
        data = await client.get('/v1/plugin/apps', params={'project_id': args.project_id})
        return [a for a in data.get('apps', []) if a.get('name') == prefix]

    params = StdioServerParameters(command=sys.executable, args=['-m', 'pluglayer_mcp.server'], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, data, expected_error=False):
                result = await session.call_tool(tool, data)
                text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                record(tool, bool(result.isError) == expected_error, expected_error=expected_error,
                    already_latest='already uses the latest template version' in text)
                return text, not result.isError

            async def wait_task(text):
                try:
                    task = json.loads(text).get('task_id')
                except ValueError:
                    match = re.search(r'Task ID: `([a-f0-9-]{36})`', text)
                    task = match.group(1) if match else None
                if not task:
                    record('task_completed', False, reason='missing task id')
                    return False
                deadline = time.monotonic()+420
                while time.monotonic() < deadline:
                    result = await session.call_tool('get_task_status', {'task_id': task})
                    value = '\n'.join(getattr(c, 'text', '') for c in result.content)
                    if result.isError or re.search(r'Status: (failed|cancelled)', value):
                        record('task_completed', False, task_id=task)
                        return False
                    if 'Status: completed' in value:
                        record('task_completed', True, task_id=task)
                        return True
                    await asyncio.sleep(4)
                record('task_completed', False, task_id=task, reason='timeout')
                return False

            async def public_http(app, phase):
                url = app.get('primary_url')
                if not url:
                    record('public_http_'+phase, False, reason='no primary url')
                    return
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as http:
                    try:
                        response = await http.get(url)
                        record('public_http_'+phase, response.status_code == 200 and 'Welcome to nginx!' in response.text,
                            http_status=response.status_code)
                    except httpx.HTTPError as exc:
                        record('public_http_'+phase, False, error_type=type(exc).__name__)

            try:
                compose = "services:\n  web:\n    image: nginxinc/nginx-unprivileged:alpine\n    ports: ['8080:8080']\n    deploy:\n      resources:\n        limits:\n          cpus: '0.1'\n          memory: 128M\n"
                text, ok = await call('create_template_draft', {'template': {'name': prefix, 'version': '1.0.0',
                    'description': 'Disposable version-update E2E', 'category': 'tools', 'compose_yaml': compose,
                    'requirements': {'min_cpu_cores': 0.1, 'min_ram_gb': 0.125, 'min_storage_gb': 0}}})
                if not ok:
                    return
                tid = json.loads(text)['template']['id']
                drafts.append(tid)
                text, ok = await call('deploy_marketplace_template', {'template_id': tid, 'project_id': args.project_id,
                    'app_name': prefix, 'route_slug': prefix, 'cpu_limit': '100m', 'memory_limit': '128Mi'})
                if not ok or not await wait_task(text):
                    return
                app = (await apps())[0]
                await public_http(app, 'initial')
                await call('update_app_from_template', {'app_id': app['id']}, expected_error=True)
                await call('update_template_draft', {'template_id': tid, 'updates': {'version': '1.0.1'}})
                text, ok = await call('update_app_from_template', {'app_id': app['id']})
                if ok and await wait_task(text):
                    updated = (await apps())[0]
                    record('updated_template_version_readback', updated.get('template_version') == '1.0.1')
                    record('app_identity_and_route_preserved', updated['id'] == app['id'] and updated.get('primary_url') == app.get('primary_url'))
                    await public_http(updated, 'updated')
            finally:
                for app in await apps():
                    text, ok = await call('remove_app', {'app_id': app['id']})
                    if ok:
                        await wait_task(text)
                record('app_cleanup_readback', not await apps())
                for tid in drafts:
                    await call('delete_template_draft', {'template_id': tid, 'confirmation': 'DELETE TEMPLATE '+tid})
                await call('update_user_context', {'context_patch': before, 'merge': False})
                after = (await client.get('/v1/plugin/user-context')).get('data', {})
                record('context_restored', before == after)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-disposable-writes', action='store_true', required=True)
    args = parser.parse_args()
    asyncio.run(run(args))
    raise SystemExit(any(r['status'] != 'PASS' for r in json.loads(args.output.read_text())['cases']))
