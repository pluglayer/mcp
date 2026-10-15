"""Real-backend protocol regression checks without disclosing credentials."""
import asyncio
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'pluglayer-mcp'))
from pluglayer_mcp.credentials import resolve_api_base_url
from pluglayer_mcp.remote import BearerMiddleware, mcp
from pluglayer_mcp.settings import settings


async def main():
    url=resolve_api_base_url()
    params=StdioServerParameters(command=sys.executable,args=['-m','pluglayer_mcp.server'],env={
        'PYTHONPATH':str(ROOT/'pluglayer-mcp'),'PLUGLAYER_API_KEY':'plk_invalid_readiness',
        'PLUGLAYER_API_URL':url,'PLUGLAYER_CREDENTIALS_FILE':str(ROOT/'.readiness-no-credentials')})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            result=await session.call_tool('get_current_user',{})
            text='\n'.join(getattr(c,'text','') for c in result.content)
            assert result.isError and '401' in text
            print('PASS: actual stdio CallToolResult.isError=true for invalid API token')
            tools=(await session.list_tools()).tools
            assert all(t.annotations is not None for t in tools)
            print(f'PASS: annotations present on all {len(tools)} tools')
    settings.PLUGLAYER_API_URL=url
    app=BearerMiddleware(mcp.streamable_http_app())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://local-mcp.test') as client:
        for token in ('','ploa_bogus_readiness'):
            headers={'Authorization':'Bearer '+token} if token else {}
            response=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize'})
            assert response.status_code==401
            assert 'resource_metadata=' in response.headers['WWW-Authenticate']
            print('PASS: local hosted middleware rejects '+('bogus OAuth token against real backend' if token else 'missing bearer')+' before initialize')

if __name__=='__main__':asyncio.run(main())
