"""Regressions for the October public plugin assessment."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from pluglayer_mcp import remote_auth
from pluglayer_mcp.tools import identity_projects, shared, template_views, templates
from pluglayer_mcp.tools.deployment import app_read, databases


@pytest.mark.asyncio
async def test_backend_error_raises_at_real_fastmcp_boundary(monkeypatch):
    client = AsyncMock()
    client.get.side_effect = RuntimeError("401 Unauthorized: expired token")
    monkeypatch.setattr(identity_projects, "_client", lambda: client)
    server = FastMCP("errors")
    identity_projects.register_identity_project_tools(server)
    with pytest.raises(ToolError, match="401 Unauthorized: expired token"):
        await server.call_tool("get_current_user", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", [
    ("rename_project", {"project_id": "missing", "new_name": "x"}),
    ("update_project_metadata", {"project_id": "missing"}),
    ("apply_app_env_vars", {"app_id": "missing", "merge": False}),
    ("mark_notification_read", {"notification_id": ""}),
    ("update_my_feedback", {"feedback_id": ""}),
    ("deploy_marketplace_template", {"template_id": "missing", "app_name": "test"}),
    ("create_database", {"template_id": "missing", "app_name": "test"}),
    ("upload_image_archive_and_deploy", {"project_id": "missing", "name": "test", "image_archive_path": "/nonexistent/readiness.tar"}),
    ("upload_image_archive_and_redeploy_app", {"app_id": "missing", "image_archive_path": "/nonexistent/readiness.tar"}),
])
async def test_invalid_inputs_fail_at_mcp_boundary(tool, args):
    from pluglayer_mcp.server import mcp
    with pytest.raises(ToolError):
        await mcp.call_tool(tool, args)


@pytest.mark.asyncio
@pytest.mark.parametrize("module,register,tool,arg", [
    (app_read, "register_app_read_tools", "get_app_connection_env_vars", "app_id"),
    (databases, "register_databases_tools", "get_database_connection_details", "database_id"),
])
async def test_connection_values_require_explicit_reveal(monkeypatch, module, register, tool, arg):
    secret = "mongodb://user:never-print-this@host/db"
    values = {"env_vars": {"UNEXPECTED_NAME": secret}, "connection_fields": [{"key": "URI", "value": secret}]}
    client = AsyncMock()
    client.get.return_value = {**values, "app": values, "database": {"name": "test"}}
    monkeypatch.setattr(module, "_client", lambda: client)
    server = FastMCP("secrets")
    getattr(module, register)(server)
    result = await server.call_tool(tool, {arg: "test"})
    assert secret not in str(result)
    assert "[REDACTED]" in str(result)
    revealed = await server.call_tool(tool, {arg: "test", "reveal": True})
    assert secret in str(revealed)
    assert "Warning:" in str(revealed)


@pytest.mark.asyncio
async def test_database_removal_reports_queued_task_not_completed_teardown(monkeypatch):
    client = AsyncMock()
    client.get.return_value = {"database": {"name": "fixture"}}
    client.delete.return_value = {"task_id": "task-123"}
    monkeypatch.setattr(databases, "_client", lambda: client)
    monkeypatch.setattr(databases, "_remember_context", AsyncMock())
    server = FastMCP("database-cleanup")
    databases.register_databases_tools(server)
    result = str(await server.call_tool("remove_database", {"database_id": "fixture"}))
    assert "Removal queued" in result and "task-123" in result
    assert "get_task_status" in result and "were torn down" not in result


def test_legacy_log_failures_are_errors_but_application_text_is_not():
    with pytest.raises(ToolError, match="Internal Server Error"):
        shared._checked_logs({"logs": "=== app-abc (current) ===\nError reading logs: Internal Server Error"})
    assert "Error reading logs:" in shared._checked_logs({"logs": "=== app (current) ===\nstarted\nError reading logs: application message"})


def test_template_discovery_is_bounded_and_preserves_schema_refs():
    schema = {"$ref": "#/$defs/Input", "$defs": {"Input": {"type": "object"}}}
    data = {"schemas": {"create_draft": schema}, "lifecycle": {}}
    assert "schemas" not in template_views.schema_view(data, "summary")
    assert template_views.schema_view(data, "create_draft")["schemas"]["create_draft"] == schema
    with pytest.raises(ValueError):
        template_views.schema_view(data, "missing")
    context = {"templates": [{"id": str(i), "compose_yaml": "x" * 50000} for i in range(20)]}
    result = template_views.context_view(context, "templates", 0, 5)
    assert len(result["templates"]) == 5 and result["next_offset"] == 5
    assert len(json.dumps(result)) < 500


@pytest.mark.asyncio
async def test_close_session_calls_owner_checked_backend(monkeypatch):
    client = AsyncMock()
    client.post.return_value = {"status": "archived"}
    monkeypatch.setattr(templates, "_client", lambda: client)
    server = FastMCP("sessions")
    templates.register_template_tools(server)
    await server.call_tool("close_template_launch_session", {"session_id": "session-1"})
    client.post.assert_awaited_with("/v1/plugin/templates/sessions/session-1/close")


@pytest.mark.asyncio
async def test_hosted_auth_cache_is_bounded_positive_only_and_expires(monkeypatch):
    requests = []
    statuses = iter([401, 401, 200, 200, 403])
    def respond(request):
        requests.append(request)
        return httpx.Response(next(statuses))
    factory = httpx.AsyncClient
    monkeypatch.setattr(remote_auth.httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(respond), **kw))
    clock = [100.0]
    monkeypatch.setattr(remote_auth.time, "monotonic", lambda: clock[0])
    validator = remote_auth.BearerValidator(ttl=15, limit=1)
    assert await validator.validate("ploa_bad") == 401
    assert await validator.validate("ploa_bad") == 401
    assert await validator.validate("ploa_good") == 200
    assert await validator.validate("ploa_good") == 200
    assert len(requests) == 3
    assert await validator.validate("ploa_other") == 200
    assert len(validator.cache) == 1 and "ploa_other" not in str(validator.cache)
    clock[0] += 16
    assert await validator.validate("ploa_other") == 403


@pytest.mark.asyncio
async def test_catalog_annotations_cover_every_tool_and_do_not_call_writes_reads():
    from pluglayer_mcp.server import mcp
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    for tool in tools.values():
        hints = tool.annotations
        assert all(isinstance(getattr(hints, key), bool) for key in ("readOnlyHint", "openWorldHint", "destructiveHint"))
    for name in ("estimate_compute", "verify_custom_domain", "plan_template_launch", "exec_app_terminal", "create_template_launch_session"):
        assert tools[name].annotations.readOnlyHint is False
    assert tools["get_app_logs"].annotations.readOnlyHint is True
    assert tools["remove_database"].annotations.destructiveHint is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 503])
async def test_hosted_invalid_auth_never_reaches_mcp(monkeypatch, status):
    from pluglayer_mcp.remote import BearerMiddleware, BearerValidator
    endpoint = AsyncMock()
    monkeypatch.setattr(BearerValidator, "validate", AsyncMock(return_value=status))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=BearerMiddleware(endpoint)), base_url="https://mcp.example") as client:
        response = await client.post('/mcp', headers={"Authorization": "Bearer ploa_invalid"}, json={"method": "initialize"})
    assert response.status_code == status
    if status == 401:
        assert 'invalid_token' in response.headers['WWW-Authenticate']
    endpoint.assert_not_awaited()
