"""Per-user memory/context MCP tools."""

import json

from pluglayer_mcp.tools.shared import _client, _compact_error


def _context_update_summary(payload: dict) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    keys = sorted(str(key) for key in payload.keys())
    key_preview = ", ".join(f"`{key}`" for key in keys[:12]) or "none"
    if len(keys) > 12:
        key_preview += f", and {len(keys) - 12} more"
    return (
        "User context updated. "
        f"Stored {len(encoded.encode('utf-8')):,} bytes across {len(keys)} top-level key(s): {key_preview}. "
        "Use get_user_context() when the full stored value is needed."
    )


def register_user_context_tools(mcp):
    @mcp.tool()
    async def get_user_context() -> str:
        """Load the caller's stored PlugLayer user context memory. Use this at the start of a session when prior project/app/domain preferences may matter."""
        try:
            data = await _client().get("/v1/plugin/user-context")
            payload = data.get("data", {})
            if not payload:
                return "No stored user context yet."
            return "Stored user context:\n\n```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```"
        except Exception as e:
            return _compact_error("Error loading user context", e)

    @mcp.tool()
    async def update_user_context(context_patch: dict, merge: bool = True) -> str:
        """Update the caller's stored PlugLayer user context memory. Use this carefully for durable preferences, project/app mappings, prior decisions, and user-specific deployment habits."""
        try:
            data = await _client().patch(f"/v1/plugin/user-context?merge={'true' if merge else 'false'}", context_patch)
            payload = data.get("data", {})
            return _context_update_summary(payload)
        except Exception as e:
            return _compact_error("Error updating user context", e)
