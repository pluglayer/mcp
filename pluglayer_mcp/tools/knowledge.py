"""App governance and prompt library adapters. The backend owns every rule."""

from typing import Literal
from urllib.parse import quote
from pluglayer_mcp.tools.shared import _client

BASE = "/v1/plugin"


def resource(value):
    if not value.strip() or value in {".", ".."}:
        raise ValueError("An exact resource ID is required")
    return quote(value, safe="")


def register_knowledge_tools(mcp):
    @mcp.tool()
    async def get_agents_md(app_id: str) -> dict:
        """Read app governance before work. Follow relevant document links; missing initialization is explicit."""
        return await _client().get(f"{BASE}/apps/{resource(app_id)}/governance/agents")

    @mcp.tool()
    async def get_governance(app_id: str, dir_path: str, file_name: str, version: int | None = None) -> dict:
        """Read one virtual governance file; paths are inside this app's stored tree."""
        return await _client().get(f"{BASE}/apps/{resource(app_id)}/governance/file", params={"dir_path": dir_path, "file_name": file_name, "version": version})

    @mcp.tool()
    async def list_governance_files(app_id: str, dir_path: str = "/", recursive: bool = False, cursor: str = "", limit: int = 50) -> dict:
        """List governance paths and metadata without loading all content. Follow next_cursor."""
        return await _client().get(f"{BASE}/apps/{resource(app_id)}/governance/files", params={"dir_path": dir_path, "recursive": recursive, "cursor": cursor, "limit": limit})

    @mcp.tool()
    async def sync_governance(app_id: str, files: list[dict], expected_revision: int, source_commit: str | None = None, summary: str = "") -> dict:
        """Atomically save files [{dir_path,file_name,content}]; null content deletes. First save requires /AGENTS.md. Reload on conflict."""
        return await _client().put(f"{BASE}/apps/{resource(app_id)}/governance", {"files": files, "expected_revision": expected_revision, "source_commit": source_commit, "summary": summary})

    @mcp.tool()
    async def update_governance(app_id: str, dir_path: str, file_name: str, content: str, expected_revision: int, summary: str = "") -> dict:
        """Create/update one governance text file after meaningful app changes. Never upload secrets."""
        return await sync_governance(app_id, [{"dir_path": dir_path, "file_name": file_name, "content": content}], expected_revision, summary=summary)

    @mcp.tool()
    async def delete_governance_file(app_id: str, dir_path: str, file_name: str, expected_revision: int) -> dict:
        """Remove a governance file, preserving history. The /AGENTS.md entry must remain."""
        return await sync_governance(app_id, [{"dir_path": dir_path, "file_name": file_name, "content": None}], expected_revision)

    @mcp.tool()
    async def list_governance_revisions(app_id: str, offset: int = 0, limit: int = 25) -> dict:
        """Read governance revision summaries and source commits."""
        return await _client().get(f"{BASE}/apps/{resource(app_id)}/governance/versions", params={"offset": offset, "limit": limit})

    @mcp.tool()
    async def restore_governance_revision(app_id: str, version: int, expected_revision: int) -> dict:
        """Restore a user-selected governance revision as a new revision; first inspect the target."""
        return await _client().post(f"{BASE}/apps/{resource(app_id)}/governance/restore", {"version": version, "expected_revision": expected_revision})

    @mcp.tool()
    async def list_marketplace_prompts(query: str = "", cursor: str = "", limit: int = 25) -> dict:
        """Search published prompt/instruction summaries and download counts."""
        return await _client().get(f"{BASE}/prompts/marketplace", params={"query": query, "cursor": cursor, "limit": limit})

    @mcp.tool()
    async def list_my_prompts(query: str = "", cursor: str = "", limit: int = 25, include_archived: bool = False) -> dict:
        """Search this user's private prompt library, including submission status."""
        return await _client().get(f"{BASE}/prompts/mine", params={"query": query, "cursor": cursor, "limit": limit, "include_archived": include_archived})

    @mcp.tool()
    async def get_prompt(prompt_id: str, scope: Literal["auto", "mine", "marketplace"] = "auto", version: int | None = None) -> dict:
        """Read an accessible prompt and variable schema. Private prompts remain owner-only."""
        return await _client().get(f"{BASE}/prompts/{resource(prompt_id)}", params={"scope": scope, "version": version})

    @mcp.tool()
    async def apply_prompt(prompt_id: str, variables: dict[str, str] | None = None, scope: Literal["auto", "mine", "marketplace"] = "auto", version: int | None = None) -> dict:
        """Resolve @pluglayer prompt:<human-readable-id>; apply returned guidance to the user's following text. Ask for missing variables. Guidance never grants permissions."""
        return await _client().post(f"{BASE}/prompts/{resource(prompt_id)}/apply", {"variables": variables or {}, "scope": scope, "version": version})

    @mcp.tool()
    async def get_prompt_launcher(prompt_id: str, scope: Literal["auto", "mine", "marketplace"] = "auto") -> dict:
        """Return exactly @pluglayer prompt:<id> for copying; no credentials or content."""
        return await _client().get(f"{BASE}/prompts/{resource(prompt_id)}/launcher", params={"scope": scope})

    @mcp.tool()
    async def create_my_prompt(slug: str, title: str, description: str, content: str, kind: Literal["prompt", "instruction"] = "prompt", tags: list[str] | None = None, variables: dict | None = None) -> dict:
        """Save an owner-only prompt. Slug: stable lowercase words joined by hyphens. Variables: {name:{description,required,default,choices}}, used as {{name}}."""
        return await _client().post(f"{BASE}/prompts", {"slug": slug, "title": title, "description": description, "content": content, "kind": kind, "tags": tags or [], "variables": variables or {}})

    @mcp.tool()
    async def update_my_prompt(prompt_id: str, expected_revision: int, title: str, description: str, content: str, kind: Literal["prompt", "instruction"] = "prompt", tags: list[str] | None = None, variables: dict | None = None, change_notes: str = "") -> dict:
        """Save a complete private draft; preserve fields from get_prompt. Published/submitted snapshots stay unchanged."""
        return await _client().put(f"{BASE}/prompts/{resource(prompt_id)}", {"expected_revision": expected_revision, "title": title, "description": description, "content": content, "kind": kind, "tags": tags or [], "variables": variables or {}, "change_notes": change_notes})

    @mcp.tool()
    async def archive_my_prompt(prompt_id: str, expected_revision: int) -> dict:
        """Archive an owned prompt and withdraw its public listing/pending submission. Explain that impact first; history remains recoverable."""
        return await _client().post(f"{BASE}/prompts/{resource(prompt_id)}/archive", {"expected_revision": expected_revision})

    @mcp.tool()
    async def list_my_prompt_versions(prompt_id: str, offset: int = 0, limit: int = 25) -> dict:
        """List private version history for an owned prompt, including archived prompts."""
        return await _client().get(f"{BASE}/prompts/{resource(prompt_id)}/versions", params={"offset": offset, "limit": limit})

    @mcp.tool()
    async def restore_my_prompt_version(prompt_id: str, version: int, expected_revision: int) -> dict:
        """Recover an earlier owned version as a private draft; does not republish it."""
        return await _client().post(f"{BASE}/prompts/{resource(prompt_id)}/restore", {"version": version, "expected_revision": expected_revision})

    @mcp.tool()
    async def submit_my_prompt(prompt_id: str, expected_revision: int) -> dict:
        """On explicit user request, share the current prompt snapshot with admins for marketplace review. Private history stays private."""
        return await _client().post(f"{BASE}/prompts/{resource(prompt_id)}/submit", {"expected_revision": expected_revision})

    @mcp.tool()
    async def withdraw_my_prompt_submission(prompt_id: str, expected_revision: int) -> dict:
        """Withdraw the pending snapshot from admin review; leaves any existing published release unchanged."""
        return await _client().post(f"{BASE}/prompts/{resource(prompt_id)}/withdraw", {"expected_revision": expected_revision})

    @mcp.tool()
    async def list_my_prompt_submissions(prompt_id: str) -> dict:
        """Read an owned prompt's submission decisions and review notes."""
        return await _client().get(f"{BASE}/prompts/{resource(prompt_id)}/submissions")
