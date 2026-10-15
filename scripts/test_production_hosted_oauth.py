"""Production PKCE/browser + hosted MCP smoke. Tokens live only in memory.

Writes an authorization URL for the user's browser, waits for its loopback
callback, checks hosted tools, rotates and revokes only its own test tokens.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP = 'https://mcp.pluglayer.com/mcp'
ISSUER = 'https://api.pluglayer.com/v1/mcp/oauth'


async def run(args):
    rows, captured, tokens = [], {}, []
    done = threading.Event()
    state = secrets.token_urlsafe(24)

    def record(name, ok, **detail):
        rows.append({'tool': name, 'status': 'PASS' if ok else 'FAIL', **detail})
        args.output.write_text(json.dumps({'transport': 'production-hosted-oauth', 'cases': rows}, indent=2)+'\n')
        print(('PASS' if ok else 'FAIL')+': '+name, flush=True)

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            uri = urlparse(self.path)
            data = {k: v[0] for k, v in parse_qs(uri.query).items()}
            if uri.path != '/callback' or data.get('state') != state:
                self.send_response(400)
                self.end_headers()
                return
            captured.update(data)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h3>PlugLayer E2E login received.</h3><script>history.replaceState(null,"","/complete")</script>')
            done.set()

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    redirect = f'http://127.0.0.1:{server.server_port}/callback'
    async with httpx.AsyncClient(timeout=30) as http:
        async def initialize(token=None):
            headers = {'Accept': 'application/json, text/event-stream'}
            if token:
                headers['Authorization'] = 'Bearer '+token
            return await http.post(MCP, headers=headers, json={'jsonrpc': '2.0', 'id': 1,
                'method': 'initialize', 'params': {'protocolVersion': '2025-03-26',
                'capabilities': {}, 'clientInfo': {'name': 'production-e2e', 'version': '1'}}})

        meta = (await http.get('https://mcp.pluglayer.com/.well-known/oauth-protected-resource')).json()
        record('resource_metadata', meta.get('resource') == MCP and ISSUER in meta.get('authorization_servers', []))
        auth = (await http.get('https://api.pluglayer.com/.well-known/oauth-authorization-server/v1/mcp/oauth')).json()
        record('issuer_metadata', auth.get('issuer') == ISSUER)
        for label, token in [('absent_bearer', None), ('bogus_bearer', 'ploa_'+secrets.token_hex(24))]:
            response = await initialize(token)
            record(label, response.status_code == 401, http_status=response.status_code)
        reg = await http.post(auth['registration_endpoint'], json={
            'client_name': 'PlugLayer production E2E read-only test', 'redirect_uris': [redirect],
            'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
            'token_endpoint_auth_method': 'none'})
        reg.raise_for_status()
        client_id = reg.json()['client_id']
        record('dynamic_registration', True)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        args.auth_url.write_text(auth['authorization_endpoint']+'?'+urlencode({
            'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect,
            'code_challenge': challenge, 'code_challenge_method': 'S256', 'scope': 'pluglayer.read',
            'state': state, 'resource': MCP}))
        print('WAITING_FOR_BROWSER', flush=True)
        try:
            got = await asyncio.to_thread(done.wait, 600)
            valid = got and 'code' in captured and captured.get('iss', ISSUER) == ISSUER
            record('pkce_browser_callback', valid)
            if not valid:
                return
            payload = {'grant_type': 'authorization_code', 'code': captured['code'],
                'redirect_uri': redirect, 'client_id': client_id, 'code_verifier': verifier}
            exchanged = await http.post(auth['token_endpoint'], data=payload)
            exchanged.raise_for_status()
            current = exchanged.json()
            tokens.extend([current['access_token'], current['refresh_token']])
            record('code_exchange', current.get('token_type', '').lower() == 'bearer')
            record('token_no_store', exchanged.headers.get('cache-control') == 'no-store')
            replay = await http.post(auth['token_endpoint'], data=payload)
            record('code_replay_rejected', replay.status_code == 400 and replay.json().get('error') == 'invalid_grant')

            async def smoke(token, full=False):
                async with streamablehttp_client(MCP, headers={'Authorization': 'Bearer '+token}) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        init = await session.initialize()
                        record('hosted_initialize', bool(init.serverInfo))
                        result = await session.call_tool('get_current_user', {})
                        value = '\n'.join(getattr(c, 'text', '') for c in result.content)
                        is_target = not result.isError and 'basithedev' in value
                        username = re.search(r'^Username: (.+)$', value, re.M)
                        record('hosted_basithedev_identity', is_target, is_error=bool(result.isError),
                               username=username.group(1) if username else None)
                        if not is_target:
                            return
                        if full:
                            tools = (await session.list_tools()).tools
                            record('hosted_tool_catalog', len(tools) == 95, tool_count=len(tools))
                            record('hosted_tool_annotations', all(t.annotations and all(isinstance(getattr(t.annotations, k), bool)
                                for k in ('readOnlyHint', 'destructiveHint', 'openWorldHint')) for t in tools))
                            for name, data in [('list_projects', {}), ('list_database_templates', {}),
                                ('get_template_authoring_schema', {})]:
                                result = await session.call_tool(name, data)
                                record('hosted_'+name, not result.isError)
                            result = await session.call_tool('get_database_connection_details', {'database_id': '00000000-0000-0000-0000-000000000001'})
                            record('hosted_missing_database_is_error', bool(result.isError))

            await smoke(current['access_token'], True)
            old_refresh = current['refresh_token']
            refreshed = await http.post(auth['token_endpoint'], data={'grant_type': 'refresh_token',
                'refresh_token': old_refresh, 'client_id': client_id})
            refreshed.raise_for_status()
            new = refreshed.json()
            tokens.extend([new['access_token'], new['refresh_token']])
            record('refresh_rotation', new['access_token'] != current['access_token'] and new['refresh_token'] != old_refresh)
            reused = await http.post(auth['token_endpoint'], data={'grant_type': 'refresh_token',
                'refresh_token': old_refresh, 'client_id': client_id})
            record('old_refresh_rejected', reused.status_code == 400)
            await smoke(new['access_token'])
        finally:
            for token in tokens:
                revoked = await http.post(auth['revocation_endpoint'], data={'token': token, 'client_id': client_id})
                record('token_revocation', revoked.status_code == 200)
            if tokens:
                await asyncio.sleep(16)
                revoked = await initialize(tokens[-2])
                record('revoked_access_rejected_at_initialize', revoked.status_code == 401, http_status=revoked.status_code)
                refresh = await http.post(auth['token_endpoint'], data={'grant_type': 'refresh_token',
                    'refresh_token': tokens[-1], 'client_id': client_id})
                record('revoked_refresh_rejected', refresh.status_code == 400)
            server.shutdown()
            server.server_close()
            args.auth_url.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--auth-url', type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        # Exception strings may include request URLs or response bodies.
        print('FAILED_EXCEPTION: '+type(exc).__name__, flush=True)
        raise SystemExit(1)
    raise SystemExit(any(r['status'] != 'PASS' for r in json.loads(args.output.read_text())['cases']))
