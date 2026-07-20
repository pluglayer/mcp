"""Secure environment import MCP tool."""

from __future__ import annotations

from pluglayer_mcp.tools.shared import _client, _compact_error, _fmt_task_hint


def register_env_import_tools(mcp):
    @mcp.tool()
    async def apply_app_env_vars(
        app_id: str,
        env_content: str = "",
        env_vars: dict[str, str | int | float | bool | None] | None = None,
        input_format: str = "auto",
        merge: bool = True,
        restart_mode: str = "restart",
        redeploy_strategy: str = "",
    ) -> str:
        """Import runtime env vars into an existing app from dotenv/KEY=VALUE, JSON, YAML text, or a direct key/value object, then optionally restart it. Pass file content, never a local/server file path. Values are not returned."""
        try:
            if env_content and env_vars is not None:
                return "❌ Provide either `env_content` or `env_vars`, not both."
            if not merge and not env_content and env_vars is None:
                return "❌ Replace mode requires an explicit source; pass `env_vars={}` only when you intend to clear every environment variable."
            if input_format not in {"auto", "dotenv", "json", "yaml"}:
                return "❌ `input_format` must be one of `auto`, `dotenv`, `json`, or `yaml`."
            if restart_mode not in {"restart", "redeploy", "none"}:
                return "❌ `restart_mode` must be one of `restart`, `redeploy`, or `none`."
            if redeploy_strategy and redeploy_strategy not in {"recreate", "rolling"}:
                return "❌ `redeploy_strategy` must be `recreate`, `rolling`, or empty."

            payload = {
                "merge": merge,
                "restart_mode": restart_mode,
                "input_format": input_format,
            }
            if env_content:
                payload["content"] = env_content
            else:
                payload["env_vars"] = env_vars or {}
            if redeploy_strategy:
                payload["redeploy_strategy"] = redeploy_strategy

            data = await _client().post(f"/v1/plugin/apps/{app_id}/env/import", payload)
            keys = data.get("imported_keys") or []
            task_id = data.get("task_id")
            key_text = ", ".join(f"`{key}`" for key in keys) if keys else "none"
            task_text = f"\nTask ID: `{task_id}`\n{_fmt_task_hint(task_id)}" if task_id else "\nNo restart/redeploy task was queued."
            return (
                f"🔐 Applied {data.get('imported_count', len(keys))} environment variable(s) to "
                f"**{data.get('app_name') or app_id}** without returning their values.\n"
                f"Keys: {key_text}\n"
                f"Mode: `{'merge' if data.get('merge', merge) else 'replace'}`; restart: `{data.get('restart_mode', restart_mode)}`"
                f"{task_text}"
            )
        except Exception as exc:
            return _compact_error("Error applying app environment variables", exc)
