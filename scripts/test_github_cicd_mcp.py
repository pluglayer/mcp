"""Real local stdio, real HTTP backend, real issued plugin API keys.

Only targets the disposable localhost github_cicd_test_server. No secret output.
Run with CICD_TEST_API_URL set to the local harness origin.
"""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    origin = os.environ['CICD_TEST_API_URL']
    assert urlsplit(origin).hostname in {'127.0.0.1', 'localhost'}
    async with httpx.AsyncClient(base_url=origin) as http:
        async def credential(username):
            response = await http.post('/v1/plugin-tokens', headers={'Authorization': 'Bearer dev-'+username}, json={'name': 'Disposable CI qualification'})
            response.raise_for_status()
            return response.json()['data']
        owner, outsider = await credential('reviewer'), await credential('outsider')
        async def session_calls(record, own):
            params = StdioServerParameters(command=str(ROOT/'.venv/bin/python'), args=['-m', 'pluglayer_mcp.server'], env={
                'PYTHONPATH': str(ROOT), 'PLUGLAYER_API_KEY': record['token'], 'PLUGLAYER_API_URL': origin,
                'PLUGLAYER_CREDENTIALS_FILE': '/nonexistent/cicd-test'})
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                async def call(name, arguments, denied=False):
                    result = await session.call_tool(name, arguments)
                    assert bool(result.isError) == denied, name+' returned unexpected status (content withheld)'
                    print(name+': '+('denial PASS' if denied else 'PASS'))
                    value = ''.join(item.text for item in result.content if hasattr(item, 'text'))
                    return value
                catalog = await session.list_tools()
                annotations = {t.name: t.annotations for t in catalog.tools}
                assert annotations['get_github_deployment'].readOnlyHint
                assert not annotations['configure_github_deployment'].readOnlyHint
                if not own:
                    await call('get_github_deployment', {'app_id': 'cicd-app'}, True)
                    await call('configure_github_deployment', config, True)
                    return
                await call('get_current_user', {})
                initial = json.loads(await call('get_github_deployment', {'app_id': 'cicd-app'}))
                revision = initial['connection']['revision'] if initial['connection'] else None
                await call('configure_github_deployment', {**config, 'expected_revision': revision})
                text = await call('generate_github_actions', {'project_id': 'cicd-project', 'app_id': 'cicd-app'})
                assert 'deploy-oidc@' in text and 'PLUGLAYER_API_KEY' not in text
                await call('configure_github_deployment', {**config, 'branch': 'release'}, True)
                state = json.loads(await call('get_github_deployment', {'app_id': 'cicd-app'}))
                await call('disconnect_github_deployment', {'app_id': 'cicd-app', 'expected_revision': state['connection']['revision']})
                await call('generate_github_actions', {'project_id': 'cicd-project', 'app_id': 'cicd-app'}, True)
        config = dict(app_id='cicd-app', repository='example/qualification', repository_id='123', repository_owner_id='456', branch='main')
        try:
            await session_calls(owner, True)
            await session_calls(outsider, False)
            # API keys cannot authenticate the dedicated CI boundary.
            response = await http.get('/v1/cicd/github/apps/cicd-app/uploads/unknown', headers={'Authorization': 'Bearer '+owner['token']})
            assert response.status_code == 401
            response = await http.post('/v1/cicd/github/token', json={'connection_id': 'cicd-app', 'identity_token': 'not-a-jwt'})
            assert response.status_code == 401
            print('CI API rejects plugin credential and unsigned identity: PASS')
        finally:
            for username, record in [('reviewer', owner), ('outsider', outsider)]:
                response = await http.delete('/v1/plugin-tokens/'+record['token_meta']['id'], headers={'Authorization': 'Bearer dev-'+username})
                response.raise_for_status()
    print('Real local stdio CI setup lifecycle: PASS (isolated MongoDB; registered API keys revoked)')


if __name__ == '__main__':
    asyncio.run(main())
