"""Opt-in disposable upload, Compose, private-template and database-env checks.

Uses basithedev only. Never changes existing apps, buys capacity or publishes a
template. Keeps response values out of its evidence file. Always attempts cleanup.
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pluglayer-mcp'))
from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.credentials import resolve_api_base_url, resolve_api_key


async def run(args):
    client = PlugLayerClient()
    identity = await client.get('/v1/plugin/me')
    assert identity.get('user', identity)['username'] in {'basithedev', 'basithedev@gmail.com'}
    before = (await client.get('/v1/plugin/user-context')).get('data', {})
    prefix = 'zz-paths-' + uuid4().hex[:8]
    records, drafts = [], []
    env = {'PYTHONPATH': str(ROOT/'pluglayer-mcp'), 'PLUGLAYER_API_KEY': resolve_api_key(),
           'PLUGLAYER_API_URL': resolve_api_base_url(), 'PLUGLAYER_CREDENTIALS_FILE': str(ROOT/'.readiness-no-credentials')}
    params = StdioServerParameters(command=sys.executable, args=['-m', 'pluglayer_mcp.server'], env=env)

    def record(tool, status, **details):
        records.append({'tool': tool, 'kind': 'deploy-path', 'status': status, **details})
        args.output.write_text(json.dumps({'account': 'basithedev', 'cases': records}, indent=2)+'\n')
        print(status + ': ' + tool + ' ' + json.dumps(details), flush=True)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, data):
                result = await session.call_tool(tool, data)
                text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                ok = not result.isError
                record(tool, 'PASS' if ok else 'FAIL', is_error=bool(result.isError))
                return text, ok

            async def wait(text):
                tasks = list(dict.fromkeys(re.findall(r'(?:Task IDs?:|task)\s*`([a-f0-9-]{36})`', text)))
                for task in tasks:
                    deadline = time.monotonic()+420
                    while time.monotonic() < deadline:
                        result = await session.call_tool('get_task_status', {'task_id': task})
                        value = '\n'.join(getattr(c, 'text', '') for c in result.content)
                        if result.isError or any('Status: '+s in value for s in ('failed', 'cancelled')):
                            record('get_task_status', 'FAIL', task_id=task)
                            return False
                        if 'Status: completed' in value:
                            record('get_task_status', 'PASS', task_id=task, phase='task-completed')
                            break
                        await asyncio.sleep(5)
                    else:
                        record('get_task_status', 'FAIL', task_id=task, phase='timeout')
                        return False
                return bool(tasks)

            async def owned_apps():
                apps = (await client.get('/v1/plugin/apps', params={'project_id': args.project_id})).get('apps', [])
                return [app for app in apps if app.get('name', '').startswith(prefix)]

            async def cleanup_apps():
                for app in await owned_apps():
                    text, ok = await call('remove_app', {'app_id': app['id']})
                    if ok:
                        await wait(text)
                record('fixture_cleanup', 'PASS' if not await owned_apps() else 'FAIL')

            try:
                plan = await client.post('/v1/plugin/compute/plan', {'project_id': args.project_id,
                    'workloads': [{'id': 'paths', 'name': prefix, 'cpu_cores': 0.1, 'ram_gb': 0.125, 'storage_gb': 0, 'gpu_gb': 0}]})
                if not plan.get('can_deploy_now'):
                    record('deploy_paths', 'BLOCKED', reason='No spare placement for tiny fixture')
                    return
                text, ok = await call('upload_image_archive_and_deploy', {'project_id': args.project_id,
                    'name': prefix+'-upload', 'route_slug': prefix+'-upload', 'image_archive_path': str(args.archive),
                    'ports': [8080], 'cpu_limit': '100m', 'memory_limit': '128Mi'})
                if ok and await wait(text):
                    app = next(a for a in await owned_apps() if a['name']==prefix+'-upload')
                    text, ok = await call('upload_image_archive_and_redeploy_app', {'app_id': app['id'],
                        'image_archive_path': str(args.archive), 'tag': 'readiness-2'})
                    if ok:
                        await wait(text)
                    databases = (await client.get('/v1/plugin/databases', params={'project_id': args.project_id})).get('databases', [])
                    if databases:
                        text, ok = await call('sync_database_env_to_app', {'database_id': databases[0]['id'],
                            'app_id': app['id'], 'add_missing_connection_fields': True})
                        if ok:
                            await wait(text)
                            current = (await client.get('/v1/plugin/apps/'+app['id']))['app'].get('env_vars', {})
                            source = await client.get('/v1/plugin/databases/'+databases[0]['id'])
                            fields = {f['key']: f['value'] for f in source.get('connection_fields', [])}
                            record('database_env_readback', 'PASS' if fields and all(current.get(k)==v for k,v in fields.items()) else 'FAIL')
                await cleanup_apps()
                compose = "services:\n  web:\n    image: nginxinc/nginx-unprivileged:alpine\n    ports: ['8080:8080']\n    deploy:\n      resources:\n        limits:\n          cpus: '0.1'\n          memory: 128M\n"
                text, ok = await call('deploy_compose', {'project_id': args.project_id, 'compose_yaml': compose,
                    'app_name': prefix+'-compose', 'route_slug': prefix+'-compose'})
                if ok:
                    await wait(text)
                await cleanup_apps()
                text, ok = await call('create_template_draft', {'template': {'name': prefix+'-template',
                    'description': 'Disposable private readiness test', 'category': 'tools', 'compose_yaml': compose,
                    'requirements': {'min_cpu_cores': 0.1, 'min_ram_gb': 0.125, 'min_storage_gb': 0}}})
                if ok:
                    tid = json.loads(text)['template']['id']
                    drafts.append(tid)
                    text, ok = await call('deploy_marketplace_template', {'template_id': tid, 'project_id': args.project_id,
                        'app_name': prefix+'-template-app', 'route_slug': prefix+'-template-app',
                        'cpu_limit': '100m', 'memory_limit': '128Mi'})
                    if ok:
                        await wait(text)
                await cleanup_apps()
            finally:
                try:
                    await cleanup_apps()
                finally:
                    for tid in drafts:
                        await call('delete_template_draft', {'template_id': tid, 'confirmation': 'DELETE TEMPLATE '+tid})
                    await call('update_user_context', {'context_patch': before, 'merge': False})
                    after = (await client.get('/v1/plugin/user-context')).get('data', {})
                    record('context_restored', 'PASS' if before==after else 'FAIL')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-disposable-writes', action='store_true', required=True)
    args = parser.parse_args()
    asyncio.run(run(args))

    results = json.loads(args.output.read_text())["cases"]
    raise SystemExit(1 if any(r["status"] not in {"PASS", "NOT_RUN"} for r in results) else 0)
