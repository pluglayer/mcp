import asyncio

from pluglayer_mcp.tools import notifications as notification_tools
from pluglayer_mcp.tools.notifications import register_notification_tools


class FakeMcp:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorate(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorate


def test_notification_tools_list_and_mark_read(monkeypatch):
    class FakeClient:
        async def get(self, path, params=None):
            assert path == "/v1/plugin/notifications"
            assert params == {"unread_only": True, "limit": 100}
            return {
                "unread_count": 1,
                "notifications": [{
                    "id": "notice-1", "title": "Security event contained",
                    "message": "Traffic controls protected your app.",
                    "created_at": "2026-09-04T00:00:00Z", "read_at": None,
                }],
            }

        async def post(self, path, data=None, params=None, timeout=60.0):
            assert path == "/v1/plugin/notifications/notice-1/read"
            return {"notification": {"id": "notice-1"}, "unread_count": 0}

    monkeypatch.setattr(notification_tools, "_client", lambda: FakeClient())
    mcp = FakeMcp()
    register_notification_tools(mcp)

    listed = asyncio.run(mcp.tools["list_my_notifications"](True, 1000))
    marked = asyncio.run(mcp.tools["mark_notification_read"]("notice-1"))
    assert "Security event contained" in listed
    assert "1 unread" in listed
    assert "Unread remaining: 0" in marked


def test_mark_notification_read_requires_id(monkeypatch):
    mcp = FakeMcp()
    register_notification_tools(mcp)
    assert "notification_id is required" in asyncio.run(mcp.tools["mark_notification_read"](""))
