"""Opt-in basithedev database lifecycle test with capacity preflight and cleanup."""
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
sys.path.insert(0, str(ROOT/'pluglayer-mcp'))
from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.credentials import resolve_api_base_url, resolve_api_key


async def run(args):
    client = PlugLayerClient()
    identity = await client.get('/v1/plugin/me')
    assert identity.get('user', identity)['username'] in {'basithedev', 'basithedev@gmail.com'}
    before = (await client.get('/v1/plugin/user-context')).get('data', {})
    records = []
    prefix = 'zz-dbtest-'+uuid4().hex[:8]
    env = {'PYTHONPATH': str(ROOT/'pluglayer-mcp'), 'PLUGLAYER_API_KEY': resolve_api_key(),
           'PLUGLAYER_API_URL': resolve_api_base_url(), 'PLUGLAYER_CREDENTIALS_FILE': str(ROOT/'.readiness-no-credentials')}
    params = StdioServerParameters(command=sys.executable, args=['-m', 'pluglayer_mcp.server'], env=env)

    def record(tool, status, **details):
        records.append({'tool': tool, 'kind': 'database-path', 'status': status, **details})
        args.output.write_text(json.dumps({'account': 'basithedev', 'cases': records}, indent=2)+'\n')
        print(status+': '+tool+' '+json.dumps(details), flush=True)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, data):
                result = await session.call_tool(tool, data)
                text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                reason = None
                if result.isError:
                    reason = 'root-image-rejected' if 'root' in text.lower() else 'backend-rejected'
                record(tool, 'FAIL' if result.isError else 'PASS', reason=reason)
                return text, not result.isError

            async def wait(text):
                match = re.search(r'Task ID: `([a-f0-9-]{36})`', text)
                if not match:
                    return False
                deadline = time.monotonic()+420
                while time.monotonic() < deadline:
                    result = await session.call_tool('get_task_status', {'task_id': match.group(1)})
                    value = '\n'.join(getattr(c, 'text', '') for c in result.content)
                    if result.isError or any('Status: '+s in value for s in ('failed', 'cancelled')):
                        record('get_task_status', 'FAIL', task_id=match.group(1), reason='root-image-rejected' if 'non-root' in value.lower() else 'task-failed')
                        return False
                    if 'Status: completed' in value:
                        record('get_task_status', 'PASS', task_id=match.group(1))
                        return True
                    await asyncio.sleep(5)
                record('get_task_status', 'FAIL', reason='timeout')
                return False

            async def fixtures():
                apps = (await client.get('/v1/plugin/apps', params={'project_id': args.project_id})).get('apps', [])
                return [a for a in apps if a.get('name', '').startswith(prefix)]

            try:
                templates = (await client.get('/v1/plugin/databases/templates')).get('templates', [])
                for engine in ('Redis', 'PostgreSQL'):
                    template = next((t for t in templates if t.get('name')==engine), None)
                    if template is None:
                        record('create_database', 'BLOCKED', engine=engine, reason='No template')
                        continue
                    needs = template['requirements']
                    plan = await client.post('/v1/plugin/compute/plan', {'project_id': args.project_id,
                        'workloads': [{'id': 'database', 'name': prefix, 'cpu_cores': needs['min_cpu_cores'],
                            'ram_gb': needs['min_ram_gb'], 'storage_gb': needs['min_storage_gb'], 'gpu_gb': 0}]})
                    if not plan.get('can_deploy_now'):
                        record('create_database', 'BLOCKED', engine=engine, reason='Insufficient eligible capacity')
                        continue
                    try:
                        text, ok = await call('create_database', {'template_id': template['id'],
                            'project_id': args.project_id, 'app_name': prefix+'-'+engine.lower(),
                            'cpu_limit': str(needs['min_cpu_cores']), 'memory_limit': str(needs['min_ram_gb']*1024)+'Mi',
                            'storage_gb': int(needs['min_storage_gb']), 'tcp_allowed_cidrs': ['127.0.0.1/32']})
                        if ok and await wait(text):
                            app = next(iter(await fixtures()))
                            await call('get_database_connection_details', {'database_id': app['id']})
                            await call('update_database_access', {'database_id': app['id'], 'tcp_allowed_cidrs': ['127.0.0.1/32']})
                            text, ok = await call('restart_database', {'database_id': app['id']})
                            if ok:
                                await wait(text)
                    finally:
                        for app in await fixtures():
                            text, ok = await call('remove_database', {'database_id': app['id']})
                            if ok:
                                await wait(text)
                        record('database_cleanup', 'PASS' if not await fixtures() else 'FAIL')
            finally:
                await call('update_user_context', {'context_patch': before, 'merge': False})
                after = (await client.get('/v1/plugin/user-context')).get('data', {})
                record('context_restored', 'PASS' if before==after else 'FAIL')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-disposable-writes', action='store_true', required=True)
    args = parser.parse_args()
    asyncio.run(run(args))

    results = json.loads(args.output.read_text())["cases"]
    raise SystemExit(1 if any(r["status"] not in {"PASS", "NOT_RUN"} for r in results) else 0)
