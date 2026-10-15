"""Opt-in basithedev lifecycle checks using disposable, uniquely named resources.

Creates/removes a temporary project, private drafts and one tiny app on existing
spare compute. Never resizes existing apps or purchases compute. Restores user
context after tests. Reports only sanitized outcomes and cleanup resource IDs.
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


async def run(output, project_id):
    client = PlugLayerClient()
    identity = await client.get('/v1/plugin/me')
    assert identity.get('user', identity)['username'] in {'basithedev', 'basithedev@gmail.com'}
    before = (await client.get('/v1/plugin/user-context')).get('data', {})
    name = 'zz-readiness-' + uuid4().hex[:8]
    records, drafts = [], []
    temp_project = app_id = None
    env = {'PYTHONPATH': str(ROOT/'pluglayer-mcp'), 'PLUGLAYER_API_KEY': resolve_api_key(),
           'PLUGLAYER_API_URL': resolve_api_base_url(), 'PLUGLAYER_CREDENTIALS_FILE': str(ROOT/'.readiness-no-credentials')}
    parameters = StdioServerParameters(command=sys.executable, args=['-m', 'pluglayer_mcp.server'], env=env)
    def record(tool, status, **details):
        records.append({'tool': tool, 'kind': 'lifecycle', 'status': status, **details})
        output.write_text(json.dumps({'account': 'basithedev', 'cases': records}, indent=2)+'\n')
        print(f'{status}: {tool} '+json.dumps(details), flush=True)
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            async def call(tool, args):
                result = await session.call_tool(tool, args)
                text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                failed = result.isError or text.startswith(('Error', 'Deployment blocked', '❌'))
                record(tool, 'FAIL' if failed else 'PASS', is_error=bool(result.isError))
                return text, not failed
            async def wait(text, label):
                match = re.search(r'Task ID: `([a-f0-9-]{36})`', text)
                if not match:
                    return True
                task = match.group(1)
                deadline = time.monotonic()+360
                while time.monotonic() < deadline:
                    result = await session.call_tool('get_task_status', {'task_id': task})
                    value = '\n'.join(getattr(c, 'text', '') for c in result.content)
                    if result.isError:
                        record(label, 'FAIL', phase='task-read', task_id=task)
                        return False
                    if 'Status: completed' in value:
                        record(label, 'PASS', phase='task-completed', task_id=task)
                        return True
                    if any('Status: '+s in value for s in ('failed','cancelled')):
                        record(label, 'FAIL', phase='task-failed', task_id=task)
                        return False
                    await asyncio.sleep(5)
                record(label, 'FAIL', phase='task-timeout', task_id=task)
                return False
            try:
                text, ok = await call('create_project', {'name': name, 'description': 'Disposable plugin readiness test'})
                if ok:
                    projects = (await client.get('/v1/plugin/projects')).get('projects', [])
                    temp_project = next((p['id'] for p in projects if p['name']==name), None)
                if temp_project:
                    await wait(text, 'create_project')
                    await call('update_project_metadata', {'project_id': temp_project, 'description': 'Readiness metadata roundtrip'})
                    await call('rename_project', {'project_id': temp_project, 'new_name': name+'-renamed'})
                    data = await client.get('/v1/plugin/projects/'+temp_project)
                    record('project_metadata_readback', 'PASS' if data.get('project',{}).get('name')==name+'-renamed' else 'FAIL')
                template = {'name': name, 'description': 'Disposable private plugin readiness draft', 'category': 'tools',
                            'compose_yaml': "services:\n  web:\n    image: nginxinc/nginx-unprivileged:alpine\n    ports: ['8080:8080']\n"}
                text, ok = await call('create_template_draft', {'template': template})
                if ok:
                    tid = json.loads(text)['template']['id'];drafts.append(tid)
                    await call('update_template_draft', {'template_id': tid, 'updates': {'description': 'Updated disposable draft'}})
                    await call('get_template_details', {'template_id': tid})
                    text, ok = await call('clone_template_draft', {'template_id': tid, 'name': name+'-copy'})
                    if ok:drafts.append(json.loads(text)['template']['id'])
                await call('update_user_context', {'context_patch': {'readiness_test': name}})
                # A tiny fixture fits available headroom; no billing/purchase or existing workload change.
                plan = await client.post('/v1/plugin/compute/plan', {'project_id': project_id,
                    'workloads': [{'id': 'readiness', 'name': name, 'cpu_cores': 0.1, 'ram_gb': 0.125, 'storage_gb': 0, 'gpu_gb': 0}]})
                if not plan.get('can_deploy_now'):
                    record('app_lifecycle', 'BLOCKED', reason='backend compute plan denies placement')
                    return
                text, ok = await call('deploy_image', {'project_id': project_id, 'name': name, 'route_slug': name,
                    'image': 'nginxinc/nginx-unprivileged', 'tag': 'alpine', 'ports': [8080],
                    'cpu_limit': '100m', 'memory_limit': '128Mi', 'storage_gb': 0})
                apps = (await client.get('/v1/plugin/apps', params={'project_id': project_id})).get('apps', [])
                app_id = next((a['id'] for a in apps if a['name']==name), None)
                if not ok or not app_id or not await wait(text, 'deploy_image'):
                    record('app_lifecycle', 'BLOCKED', reason='initial deployment did not complete')
                    return
                for tool,args in [
                    ('get_deployment_status', {'deployment_id':app_id}),
                    ('get_app_logs', {'app_id':app_id,'lines':5}),
                    ('exec_app_terminal', {'app_id':app_id,'command':'echo readiness-ok'}),
                    ('apply_app_env_vars', {'app_id':app_id,'env_vars':{'READINESS_PROBE':name},'restart_mode':'none'}),
                ]:await call(tool,args)
                app = (await client.get('/v1/plugin/apps/'+app_id))['app']
                record('env_readback','PASS' if app.get('env_vars',{}).get('READINESS_PROBE')==name else 'FAIL')
                policy=app['access_policy'];http=policy['http_rate_limit']
                await call('update_app_access_policy', {'app_id':app_id,'confirmed_app_name':name,
                    'http_average':http['average'],'http_burst':http['burst'],'http_period_seconds':http['period_seconds'],
                    'tcp_max_connections':policy['tcp_max_connections'],'allowed_cidrs':policy['allowed_cidrs'],
                    'egress_mode':policy.get('egress_mode','allow_all'),'egress_cidrs':policy.get('egress_cidrs',[])})
                current=(await client.get('/v1/plugin/apps/'+app_id))['app']['access_policy']
                record('access_policy_readback','PASS' if current==policy else 'FAIL')
                for tool,args in [
                    ('update_app_domain',{'app_id':app_id,'route_slug':name+'-2'}),
                    ('restart_app',{'app_id':app_id}),
                    ('redeploy',{'deployment_id':app_id,'confirmed_app_name':name}),
                    ('rollback',{'deployment_id':app_id}),
                ]:
                    text,ok=await call(tool,args)
                    if ok:await wait(text,tool)
            finally:
                if app_id:
                    text,ok=await call('remove_app',{'app_id':app_id})
                    if ok:await wait(text,'remove_app')
                    remaining=(await client.get('/v1/plugin/apps',params={'project_id':project_id})).get('apps',[])
                    record('app_cleanup','PASS' if not any(a['id']==app_id for a in remaining) else 'FAIL',app_id=app_id)
                for tid in reversed(drafts):
                    await call('delete_template_draft',{'template_id':tid,'confirmation':'DELETE TEMPLATE '+tid})
                if temp_project:
                    text,ok=await call('remove_project',{'project_id':temp_project})
                    if ok:await wait(text,'remove_project')
                await call('update_user_context',{'context_patch':before,'merge':False})
                after=(await client.get('/v1/plugin/user-context')).get('data',{})
                record('context_restored','PASS' if before==after else 'FAIL')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--run-disposable-writes',action='store_true',required=True)
    args=parser.parse_args()
    asyncio.run(run(args.output,args.project_id))

    results = json.loads(args.output.read_text())["cases"]
    raise SystemExit(1 if any(r["status"] not in {"PASS", "NOT_RUN"} for r in results) else 0)
