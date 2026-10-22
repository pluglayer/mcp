"""Real local stdio knowledge smoke. Credentials stay in memory, injected at runtime.

Default: read-only checks with the user's existing public/Admin credentials.
--isolated: complete mutation cycle against the disposable local feature server,
using real issued plugin tokens and a registered derived Admin credential. Requires
KNOWLEDGE_TEST_MONGO_URL and KNOWLEDGE_TEST_DB, both restricted to local test data.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[2]


def parameters(admin=False, key=None, url=None):
    if admin:
        folder = ROOT / "controlplane-admin/pluglayer-admin/mcp"
        sys.path.insert(0, str(folder))
        from pluglayer_admin_mcp.credentials import resolve_api_key, resolve_api_url
        key, url = key or resolve_api_key(), url or resolve_api_url()
        env = {"PLUGLAYER_ADMIN_API_KEY": key, "PLUGLAYER_ADMIN_API_URL": url,
               "PLUGLAYER_ADMIN_CREDENTIALS_FILE": "/nonexistent/knowledge-test-credentials"}
        module = "pluglayer_admin_mcp.server"
    else:
        folder = ROOT / "pluglayer-mcp"
        sys.path.insert(0, str(folder))
        from pluglayer_mcp.credentials import resolve_api_key, resolve_api_base_url
        key, url = key or resolve_api_key(), url or resolve_api_base_url()
        env = {"PLUGLAYER_API_KEY": key, "PLUGLAYER_API_URL": url,
               "PLUGLAYER_CREDENTIALS_FILE": "/nonexistent/knowledge-test-credentials"}
        module = "pluglayer_mcp.server"
    env["PYTHONPATH"] = str(folder)
    return StdioServerParameters(command=str(ROOT / "pluglayer-mcp/.venv/bin/python"), args=["-m", module], env=env)


async def call(session, name, args=None, fail=False):
    result = await session.call_tool(name, args or {})
    if bool(result.isError) != fail:
        # Never print tool content, which can carry private instructions.
        raise RuntimeError(f"{name}: unexpected {'failure' if result.isError else 'success'} (content withheld)")
    print(f"{name}: {'expected denial PASS' if fail else 'PASS'}")
    if fail:
        return None
    value = result.structuredContent
    if value is None:
        try:
            value = json.loads("".join(item.text for item in result.content if hasattr(item, "text")))
        except (ValueError, TypeError):
            return None
    if isinstance(value, dict) and "result" in value:
        value = value["result"]
    return value.get("data", value) if isinstance(value, dict) else value


async def read_only(admin):
    server = parameters(admin)
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        if admin:
            await call(session, "get_admin_capabilities")
            await call(session, "list_prompt_submissions", {"payload": {"limit": 1}})
        else:
            await call(session, "get_current_user")
            await call(session, "list_my_prompts", {"limit": 1})
            await call(session, "list_marketplace_prompts", {"limit": 1})


async def isolated():
    base = os.getenv("KNOWLEDGE_TEST_API_URL", "http://127.0.0.1:8047")
    mongo = os.environ["KNOWLEDGE_TEST_MONGO_URL"]
    database = os.environ["KNOWLEDGE_TEST_DB"]
    assert urlsplit(base).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(mongo).hostname in {"localhost", "127.0.0.1"} and database.startswith("pluglayer_knowledge_test_")
    sys.path.insert(0, str(ROOT / "app-be-pluglayer"))
    # Reuse the backend's installed Mongo/model dependencies only in this test
    # driver. The actual stdio children run in their regular MCP environment.
    backend_packages = next((ROOT / "app-be-pluglayer/.venv/lib").glob("python*/site-packages"))
    sys.path.append(str(backend_packages))
    from motor.motor_asyncio import AsyncIOMotorClient
    from models.admin_plugin.access import AdminPluginCredential, generate_admin_api_key, hash_admin_secret
    client = AsyncIOMotorClient(mongo)
    async with httpx.AsyncClient(base_url=base) as http:
        async def token(username):
            response = await http.post("/v1/plugin-tokens", headers={"Authorization": f"Bearer dev-{username}"}, json={"name": "Knowledge isolated MCP qualification"})
            response.raise_for_status()
            return response.json()["data"]
        owner, outsider, parent = await token("reviewer"), await token("outsider"), await token("admin")
    key = generate_admin_api_key()
    credential = AdminPluginCredential(parent_token_id=parent["token_meta"]["id"], owner_id="dev-sub-admin", owner_username="admin", owner_email="admin@dev.local", target="codex", token_hash=hash_admin_secret(key), token_prefix=key[:13])
    await client[database].admin_plugin_credentials.insert_one(credential.model_dump())
    slug = "qualification-" + uuid4().hex[:8]
    async with stdio_client(parameters(False, owner["token"], base)) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await call(session, "get_current_user")
        prompt = await call(session, "create_my_prompt", {"slug": slug, "title": "Production readiness", "description": "Review a release before deployment", "content": "Inspect the tests and deployment readiness."})
        launcher = await call(session, "get_prompt_launcher", {"prompt_id": slug})
        assert launcher["text"] == f"@pluglayer prompt:{slug}"
        await call(session, "get_prompt", {"prompt_id": slug})
        await call(session, "apply_prompt", {"prompt_id": slug})
        submission = await call(session, "submit_my_prompt", {"prompt_id": slug, "expected_revision": prompt["revision"]})
        await call(session, "update_my_prompt", {"prompt_id": slug, "expected_revision": prompt["revision"], "title": "Bad", "description": "Stale", "content": "Should fail"}, fail=True)
        head = await call(session, "get_agents_md", {"app_id": "knowledge-app"})
        files = [{"dir_path": "/", "file_name": "AGENTS.md", "content": "Read operations/deployment.md before deploying."}, {"dir_path": "/operations", "file_name": "deployment.md", "content": "Check tests and verify the queued task outcome."}]
        updated = await call(session, "sync_governance", {"app_id": "knowledge-app", "expected_revision": head["revision"], "files": files})
        await call(session, "list_governance_files", {"app_id": "knowledge-app"})
        await call(session, "get_governance", {"app_id": "knowledge-app", "dir_path": "/operations", "file_name": "deployment.md"})
        await call(session, "get_governance", {"app_id": "knowledge-app", "dir_path": "/../", "file_name": "etc"}, fail=True)
        await call(session, "list_governance_revisions", {"app_id": "knowledge-app"})
        await call(session, "restore_governance_revision", {"app_id": "knowledge-app", "version": 1, "expected_revision": updated["revision"]})
    async with stdio_client(parameters(False, outsider["token"], base)) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await call(session, "get_prompt", {"prompt_id": slug}, fail=True)
        await call(session, "get_agents_md", {"app_id": "knowledge-app"}, fail=True)
    async with stdio_client(parameters(True, key, base)) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await call(session, "get_admin_capabilities")
        await call(session, "list_prompt_submissions", {"payload": {}})
        await call(session, "get_prompt_submission", {"payload": {"prompt_id": slug}})
        await call(session, "decide_prompt_submission", {"payload": {"prompt_id": slug, "submission_id": submission["submission"]["id"], "expected_revision": submission["revision"], "decision": "approved"}})
    async with stdio_client(parameters(False, outsider["token"], base)) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await call(session, "apply_prompt", {"prompt_id": slug})
        await call(session, "apply_prompt", {"prompt_id": slug})
        page = await call(session, "list_marketplace_prompts", {"query": slug})
        assert page["prompts"][0]["downloads"] == 1
    # Revoke only this run's local fixture credentials; leave content for browser QA.
    ids = [owner["token_meta"]["id"], outsider["token_meta"]["id"], parent["token_meta"]["id"]]
    await client[database].plugin_api_tokens.update_many({"id": {"$in": ids}}, {"$set": {"is_active": False}})
    await client[database].admin_plugin_credentials.update_one({"id": credential.id}, {"$set": {"is_active": False}})
    client.close()
    print("Full public/Admin stdio lifecycle: PASS (isolated backend, real registered credentials)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    asyncio.run(isolated() if args.isolated else read_only(args.admin))
