"""Opt-in basithedev private template/session/queued-agent lifecycle check."""
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
    rows, sessions, drafts = [], [], []
    prefix = 'zz-session-'+uuid4().hex[:8]
    env = {'PYTHONPATH': str(ROOT/'pluglayer-mcp'), 'PLUGLAYER_API_KEY': resolve_api_key(),
           'PLUGLAYER_API_URL': resolve_api_base_url(), 'PLUGLAYER_CREDENTIALS_FILE': str(ROOT/'.readiness-no-credentials')}

    def record(tool, ok, **details):
        rows.append({'tool': tool, 'status': 'PASS' if ok else 'FAIL', **details})
        args.output.write_text(json.dumps({'account': 'basithedev', 'transport': 'local-stdio-production-api', 'cases': rows}, indent=2)+'\n')
        print(('PASS' if ok else 'FAIL')+': '+tool, flush=True)

    params = StdioServerParameters(command=sys.executable, args=['-m', 'pluglayer_mcp.server'], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, data, expected_error=False):
                result = await session.call_tool(tool, data)
                text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                record(tool, bool(result.isError) == expected_error, expected_error=expected_error)
                if result.isError:
                    return {'error': True, 'closed': 'closed' in text.lower()}
                try:
                    return json.loads(text)
                except ValueError:
                    return {'text': text}

            async def wait_task(data, kind):
                task = data.get('task_id')
                if not task:
                    record(kind+'_completed', False, reason='no task id')
                    return
                deadline = time.monotonic()+180
                while time.monotonic() < deadline:
                    result = await session.call_tool('get_task_status', {'task_id': task})
                    text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                    if result.isError or re.search(r'Status: (failed|cancelled)', text):
                        record(kind+'_completed', False, task_id=task)
                        return
                    if 'Status: completed' in text:
                        record(kind+'_completed', True, task_id=task)
                        record(kind+'_no_nonexistent_random_key_tool', 'create_random_key' not in text)
                        return
                    await asyncio.sleep(3)
                record(kind+'_completed', False, reason='timeout', task_id=task)

            try:
                draft = {'name': prefix, 'description': 'Disposable private production session test', 'category': 'tools',
                    'compose_yaml': "services:\n  web:\n    image: nginxinc/nginx-unprivileged:alpine\n    ports: ['8080:8080']\n",
                    'requirements': {'min_cpu_cores': 0.1, 'min_ram_gb': 0.125, 'min_storage_gb': 0}}
                created = await call('create_template_draft', {'template': draft})
                tid = created['template']['id']
                drafts.append(tid)
                data = {'template_id': tid, 'project_id': args.project_id}
                created = await call('create_template_launch_session', {**data, 'title': prefix, 'new_session': True})
                sid = created['session']['id']
                sessions.append(sid)
                resumed = await call('create_template_launch_session', {**data, 'title': prefix+' renamed'})
                record('resume_id_and_title', resumed.get('session', {}).get('id') == sid and
                    resumed.get('session', {}).get('title') == prefix+' renamed')
                listed = await call('list_template_launch_sessions', data)
                record('session_active_readback', any(s['id'] == sid for s in listed.get('sessions', [])))
                plan = await call('plan_template_launch', {**data, 'session_id': sid, 'app_name': prefix,
                    'route_slug': prefix, 'message': 'Plan only for a disposable E2E test. Do not deploy.'})
                record('planner_returns_session_id', plan.get('session_id') == sid)
                await wait_task(plan, 'launch_planner')
                run = await call('run_template_agent', {**data, 'session_id': sid,
                    'agent_type': 'use_template_agent', 'message': 'Inspect inputs only; do not deploy.'})
                await wait_task(run, 'launch_agent')
                builder = await call('run_template_agent', {'agent_type': 'template_builder', 'draft': draft,
                    'message': 'Review this supplied private draft without publishing or deploying.'})
                await wait_task(builder, 'builder_agent')
                await call('close_template_launch_session', {'session_id': sid})
                listed = await call('list_template_launch_sessions', data)
                record('closed_session_absent_from_active', not any(s['id'] == sid for s in listed.get('sessions', [])))
                rejected = await call('run_template_agent', {**data, 'session_id': sid,
                    'agent_type': 'use_template_agent', 'message': 'Closed-session rejection test.'}, expected_error=True)
                record('closed_session_specific_rejection', rejected.get('closed', False))
            finally:
                for sid in sessions:
                    await call('close_template_launch_session', {'session_id': sid})
                for tid in drafts:
                    await call('delete_template_draft', {'template_id': tid, 'confirmation': 'DELETE TEMPLATE '+tid})
                mine = await client.get('/v1/plugin/templates/mine')
                record('draft_cleanup_readback', not any(t['id'] in drafts for t in mine.get('templates', [])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-disposable-writes', action='store_true', required=True)
    args = parser.parse_args()
    asyncio.run(run(args))
    raise SystemExit(any(r['status'] != 'PASS' for r in json.loads(args.output.read_text())['cases']))
