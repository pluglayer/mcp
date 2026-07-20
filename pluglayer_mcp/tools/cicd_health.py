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
        """Generate a GitHub Actions workflow YAML that builds an OCI archive and uploads it to PlugLayer for the same app."""
        try:
            detected = None
            repo_slug = repo.strip()
            if not repo_slug:
                detected = _detect_github_repo(repo_path)
                if not detected.get("ok"):
                    return (
                        "❌ Could not infer a GitHub repository for CI/CD setup.\n"
                        f"Reason: {detected.get('reason')}\n"
                        "Either fix the local git/origin setup or pass `repo=\"owner/repo\"` explicitly."
                    )
                repo_slug = str(detected["repo_slug"])

            data = await _client().get(
                "/v1/plugin/cicd/generate/github-actions",
                params={
                    "project_id": project_id,
                    "app_id": app_id,
                    "repo": repo_slug,
                },
            )
            workflow = data.get("workflow_yaml", "")
            filename = data.get("filename", ".github/workflows/deploy-pluglayer.yml")
            repo_line = f"- GitHub repo: `{repo_slug}`\n"
            if detected:
                repo_line += f"- Detected from origin: `{detected['origin_url']}`\n"
            return (
                f"📋 **GitHub Actions workflow for PlugLayer app `{data.get('app_id', app_id)}`**\n"
                f"{repo_line}"
                f"- Save as: `{filename}`\n\n"
                f"```yaml\n{workflow}\n```\n\n"
                "Setup steps:\n"
                "1. Create this file in your repo.\n"
                "2. The workflow uses the public reusable actions repo `pluglayer/actions`.\n"
                "3. Add required GitHub secrets:\n"
                "   - `PLUGLAYER_API_KEY`: your PlugLayer API token\n"
                "4. The workflow already includes the resolved PlugLayer app id, so you do not need a `PLUGLAYER_APP_ID` secret.\n"
                "5. Optional GitHub secrets:\n"
                "   - `PLUGLAYER_API_URL`: defaults to `https://api.pluglayer.com`\n"
                "   - `PLUGLAYER_BUILD_ENV_JSON`: JSON object of build-time env vars/build args to inject during image build, for example `{\"NEXT_PUBLIC_API_URL\":\"https://api.example.com\",\"SENTRY_AUTH_TOKEN\":\"...\"}`\n"
                "   - `PLUGLAYER_ENV_JSON`: JSON object of runtime env vars to merge securely before the final restart\n"
                "6. Commit and push to `main` or `master`.\n"
                "7. On each push the workflow will:\n"
                "   - build a multi-arch OCI archive\n"
                "   - upload that image to PlugLayer for the same app id\n"
                "   - inject CI-provided build env vars into the image build if present\n"
                "   - merge optional runtime env vars and restart the app without changing the slug"
            )
        except Exception as e:
            return _compact_error("Error generating pipeline", e)
