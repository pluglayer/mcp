"""End-user PlugLayer Inbox MCP tools."""

from __future__ import annotations

from pluglayer_mcp.tools.shared import _client, _compact_error


def _notification_line(item: dict) -> str:
    state = "read" if item.get("read_at") else "unread"
    created = item.get("created_at") or "unknown time"
    return (
        f"- **{item.get('title', 'PlugLayer message')}** — {state} · {created} "
        f"· id: `{item.get('id', 'unknown')}`\n  {item.get('message', '')}"
    )


def register_notification_tools(mcp):
    @mcp.tool()
    async def list_my_notifications(unread_only: bool = False, limit: int = 20) -> str:
        """List the authenticated user's PlugLayer portal Inbox messages.

        This includes user-safe security incident/containment/resolution messages and
        normal project or feedback messages. It never returns operator evidence.
        """
        try:
            payload = await _client().get(
                "/v1/plugin/notifications",
                params={"unread_only": unread_only, "limit": min(max(limit, 1), 100)},
            )
            items = payload.get("notifications", [])
            if not items:
                qualifier = " unread" if unread_only else ""
                return f"No{qualifier} PlugLayer Inbox messages found."
            return (
                f"Your PlugLayer Inbox ({payload.get('unread_count', 0)} unread):\n\n"
                + "\n".join(_notification_line(item) for item in items)
            )
        except Exception as exc:
            return _compact_error("Error listing PlugLayer Inbox messages", exc)

    @mcp.tool()
    async def mark_notification_read(notification_id: str) -> str:
        """Mark one authenticated-user PlugLayer Inbox message as read."""
        cleaned_id = (notification_id or "").strip()
        if not cleaned_id:
            return "Error marking PlugLayer Inbox message read: notification_id is required."
        try:
            payload = await _client().post(f"/v1/plugin/notifications/{cleaned_id}/read")
            item = payload.get("notification", payload)
            return (
                "✅ PlugLayer Inbox message marked read.\n"
                f"Message: `{item.get('id', cleaned_id)}`\n"
                f"Unread remaining: {payload.get('unread_count', 'unknown')}"
            )
        except Exception as exc:
            return _compact_error("Error marking PlugLayer Inbox message read", exc)
