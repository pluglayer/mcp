"""CI/CD MCP tools."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pluglayer_mcp.tools.shared import _client, _compact_error


def _run_git(repo_path: str, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _normalize_github_origin(origin_url: str) -> str | None:
    value = (origin_url or "").strip()
    if value.startswith("https://github.com/"):
        value = value[len("https://github.com/") :]
    elif value.startswith("git@github.com:"):
        value = value[len("git@github.com:") :]
    value = value.removesuffix(".git").strip("/")
    return value if re.fullmatch(r"[^/\s]+/[^/\s]+", value) else None


def _detect_github_repo(repo_path: str = ".") -> dict[str, str | bool]:
    path = Path(repo_path).expanduser().resolve()
    if not path.exists():
        return {"ok": False, "reason": f"Path does not exist: {path}"}
    try:
        inside = _run_git(str(path), "rev-parse", "--is-inside-work-tree")
    except Exception:
        return {"ok": False, "reason": f"Not a git repository: {path}"}
    if inside != "true":
        return {"ok": False, "reason": f"Not a git repository: {path}"}
    try:
        origin_url = _run_git(str(path), "remote", "get-url", "origin")
    except Exception:
        return {"ok": False, "reason": f"Git repo exists at {path}, but no `origin` remote is configured"}
    repo_slug = _normalize_github_origin(origin_url)
    if not repo_slug:
        return {
            "ok": False,
            "reason": f"`origin` is not a GitHub remote: {origin_url}",
            "origin_url": origin_url,
        }
    return {
        "ok": True,
        "repo_path": str(path),
        "origin_url": origin_url,
        "repo_slug": repo_slug,
    }


def register_cicd_health_tools(mcp):
    @mcp.tool()
    async def inspect_local_github_repo(repo_path: str = ".") -> str:
        """Check whether the local repo exists, has git initialized, and points at a GitHub origin."""
        try:
            detected = _detect_github_repo(repo_path)
            if not detected.get("ok"):
                return f"❌ {detected.get('reason')}"
            return (
                "✅ **GitHub repo detected**\n"
                f"- Repo path: `{detected['repo_path']}`\n"
                f"- Origin: `{detected['origin_url']}`\n"
                f"- Repo slug: `{detected['repo_slug']}`"
            )
        except Exception as exc:
            return _compact_error("Error checking local GitHub repo", exc)

    @mcp.tool()
    async def generate_github_actions(
        project_id: str,
        app_id: str,
        repo: str = "",
        repo_path: str = ".",
    ) -> str:
        """Generate an OIDC workflow for an app with a configured GitHub deployment connection. Pass the repository explicitly for hosted MCP; repo_path is a legacy argument."""
        try:
            data = await _client().get(
                "/v1/plugin/cicd/generate/github-actions",
                params={"project_id": project_id, "app_id": app_id, "repo": repo.strip()},
            )
            workflow = data.get("workflow_yaml", "")
            filename = data.get("filename", ".github/workflows/deploy-pluglayer.yml")
            return (
                f"Automatic deployment workflow for app `{data.get('app_id', app_id)}`\n"
                f"Repository: `{data.get('repo', repo)}`\n"
                f"Save as: `{filename}`\n\n```yaml\n{workflow}\n```\n\n"
                "No PlugLayer API-key secret is required. Publish this workflow through the user's "
                "existing GitHub access and verify the first run. Future pushes to its configured "
                "branch authenticate and deploy automatically, even when the editor is closed.\n"
                "Optional application secrets: PLUGLAYER_BUILD_ENV_JSON and PLUGLAYER_ENV_JSON. "
                "Existing runtime variables are retained. Do not report active deployments until "
                "the GitHub run and PlugLayer rollout both succeed."
            )
        except Exception as e:
            return _compact_error("Error generating pipeline", e)
