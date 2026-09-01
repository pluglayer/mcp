"""Low-noise, consent-gated updates for installer-managed public plugins."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx


PluginTarget = Literal["codex", "claude", "cursor", "antigravity"]

_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_GITHUB_API = "https://api.github.com"
_RAW_GITHUB = "https://raw.githubusercontent.com"
_USER_AGENT = "pluglayer-mcp-update-check/1"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?$")

_TARGETS = {
    "codex": {
        "label": "Codex",
        "repo": "codex-plugin",
        "version_path": ".codex-plugin/plugin.json",
        "version_kind": "json",
    },
    "claude": {
        "label": "Claude Code",
        "repo": "claude-plugin",
        "version_path": ".claude-plugin/plugin.json",
        "version_kind": "json",
    },
    "cursor": {
        "label": "Cursor",
        "repo": "cursor-plugin",
        "version_path": ".cursor-plugin/plugin.json",
        "version_kind": "json",
    },
    "antigravity": {
        "label": "Antigravity",
        "repo": "antigravity-plugin",
        "version_path": "VERSION",
        "version_kind": "text",
    },
}


@dataclass(frozen=True)
class ReleaseInfo:
    target: str
    version: str
    commit_sha: str


def _pluglayer_home() -> Path:
    configured = (os.environ.get("PLUGLAYER_HOME") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".pluglayer"


def _state_file(target: str) -> Path:
    return _pluglayer_home() / "state" / f"{target}.env"


def _cache_file() -> Path:
    return _pluglayer_home() / "state" / "plugin-update-check.json"


def _read_installed_version(target: str) -> str:
    path = _state_file(target)
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""

    for line in text.splitlines():
        match = re.fullmatch(r"export PLUGLAYER_PLUGIN_VERSION=([0-9A-Za-z.+-]+)", line.strip())
        if match:
            return match.group(1)
    return ""


def _version_key(version: str) -> tuple[int, int, int, int, str] | None:
    match = _VERSION_RE.fullmatch((version or "").strip())
    if not match:
        return None
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    suffix = match.group(4) or ""
    return major, minor, patch, 1 if not suffix else 0, suffix


def _is_newer(candidate: str, installed: str) -> bool:
    candidate_key = _version_key(candidate)
    installed_key = _version_key(installed)
    return bool(candidate_key and installed_key and candidate_key > installed_key)


def _load_cache() -> dict:
    try:
        payload = json.loads(_cache_file().read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_cache(payload: dict) -> None:
    path = _cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _cached_release(cache: dict, target: str, installed_version: str) -> ReleaseInfo | None:
    entry = cache.get(target)
    if not isinstance(entry, dict):
        return None
    if entry.get("installed_version") != installed_version:
        return None
    checked_at = entry.get("checked_at")
    if not isinstance(checked_at, (int, float)) or time.time() - checked_at >= _CHECK_INTERVAL_SECONDS:
        return None
    version = entry.get("version")
    commit_sha = entry.get("commit_sha")
    if not isinstance(version, str) or not isinstance(commit_sha, str):
        return None
    return ReleaseInfo(target=target, version=version, commit_sha=commit_sha)


async def _fetch_latest_release(target: str) -> ReleaseInfo:
    metadata = _TARGETS[target]
    repo = metadata["repo"]
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as client:
        commit_response = await client.get(f"{_GITHUB_API}/repos/pluglayer/{repo}/commits/main")
        commit_response.raise_for_status()
        commit_sha = str(commit_response.json().get("sha") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise ValueError("the public repository did not return a valid commit")

        version_response = await client.get(
            f"{_RAW_GITHUB}/pluglayer/{repo}/{commit_sha}/{metadata['version_path']}"
        )
        version_response.raise_for_status()
        if metadata["version_kind"] == "json":
            version = str(version_response.json().get("version") or "").strip()
        else:
            version = version_response.text.strip()
        if _version_key(version) is None:
            raise ValueError("the public plugin published an invalid version")

    return ReleaseInfo(target=target, version=version, commit_sha=commit_sha)


async def _release_for_check(
    target: str,
    installed_version: str,
    *,
    force: bool,
) -> ReleaseInfo:
    cache = _load_cache()
    if not force:
        cached = _cached_release(cache, target, installed_version)
        if cached:
            return cached

    release = await _fetch_latest_release(target)
    cache[target] = {
        **asdict(release),
        "installed_version": installed_version,
        "checked_at": time.time(),
    }
    _write_cache(cache)
    return release


async def _run_pinned_installer(release: ReleaseInfo) -> int:
    metadata = _TARGETS[release.target]
    repo = metadata["repo"]
    installer_url = f"{_RAW_GITHUB}/pluglayer/{repo}/{release.commit_sha}/install.sh"
    common_url = f"{_RAW_GITHUB}/pluglayer/{repo}/{release.commit_sha}/install-common.sh"
    archive_url = f"https://github.com/pluglayer/{repo}/archive/{release.commit_sha}.tar.gz"

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": _USER_AGENT}) as client:
        response = await client.get(installer_url)
        response.raise_for_status()
        installer = response.content

    with tempfile.TemporaryDirectory(prefix="pluglayer-plugin-update-") as temporary_dir:
        installer_path = Path(temporary_dir) / "install.sh"
        installer_path.write_bytes(installer)
        installer_path.chmod(0o700)
        environment = os.environ.copy()
        environment.update(
            {
                "PLUGLAYER_QUICK_INSTALL": "1",
                "PLUGLAYER_INSTALL_COMMON_URL": common_url,
                "PLUGLAYER_REPO_ARCHIVE_URL": archive_url,
            }
        )
        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            str(installer_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        try:
            await asyncio.wait_for(process.communicate(), timeout=600)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return 124
        return int(process.returncode or 0)


def register_update_tools(mcp):
    @mcp.tool()
    async def check_plugin_updates(
        target: PluginTarget | None = None,
        installed_version: str = "",
        force: bool = False,
    ) -> str:
        """Check installer-managed public PlugLayer plugins for updates.

        For routine checks, call with no arguments at most once during the first substantive
        PlugLayer workflow in a conversation. The tool caches successful checks for 24 hours.
        Do not mention cached/no-update results or routine failures to the user. Use force only
        when the user explicitly asks to check now. This tool never updates anything.
        """
        if target and target not in _TARGETS:
            return "Update check error: unsupported plugin target."
        if installed_version and not target:
            return "Update check error: target is required when installed_version is provided."

        candidates: list[tuple[str, str]] = []
        if target:
            version = installed_version.strip() or _read_installed_version(target)
            if version:
                candidates.append((target, version))
        else:
            for candidate_target in _TARGETS:
                version = _read_installed_version(candidate_target)
                if version:
                    candidates.append((candidate_target, version))

        if not candidates:
            return (
                "No installer-managed PlugLayer plugin installation was found. "
                "Do not interrupt the user for this routine result."
            )

        updates: list[str] = []
        failures: list[str] = []
        for candidate_target, current_version in candidates:
            if _version_key(current_version) is None:
                failures.append(candidate_target)
                continue
            try:
                release = await _release_for_check(
                    candidate_target,
                    current_version,
                    force=force,
                )
            except Exception:
                failures.append(candidate_target)
                continue
            if _is_newer(release.version, current_version):
                label = _TARGETS[candidate_target]["label"]
                updates.append(
                    f"- {label}: installed `{current_version}`, available `{release.version}` "
                    f"(target `{candidate_target}`)"
                )

        if updates:
            return (
                "PlugLayer plugin update available:\n"
                + "\n".join(updates)
                + "\nInform the user once and ask whether they want the exact target/version updated. "
                "Only after explicit approval call update_plugin with that target, confirmed_version, "
                "and user_approved=true."
            )
        if failures:
            return (
                "The routine PlugLayer plugin update check could not be completed. "
                "Do not interrupt the user unless they explicitly asked for this check."
            )
        return "No PlugLayer plugin update is available. Do not mention this routine result to the user."

    @mcp.tool()
    async def update_plugin(
        target: PluginTarget,
        confirmed_version: str,
        user_approved: bool = False,
    ) -> str:
        """Update one public PlugLayer plugin after exact, explicit user approval.

        Never call speculatively or as part of a routine check. First show the user the target,
        installed version, and available version returned by check_plugin_updates. Call only when
        the user explicitly agrees to that exact target/version, passing user_approved=true.
        The update is pinned to the approved public-repository commit and uses PlugLayer's existing
        installer. It does not expose saved credentials.
        """
        if not user_approved:
            return "Update refused: explicit user approval is required."
        if target not in _TARGETS:
            return "Update refused: unsupported plugin target."
        installed_version = _read_installed_version(target)
        if not installed_version:
            return (
                "Update refused: this target is not tracked by the PlugLayer installer. "
                "Use the target's normal installer in a terminal."
            )
        try:
            release = await _fetch_latest_release(target)
        except Exception:
            return "Update could not verify the public release. No installer was started."
        if release.version != confirmed_version.strip():
            return (
                f"Update paused: the latest {_TARGETS[target]['label']} version is now "
                f"`{release.version}`, not the approved `{confirmed_version}`. Ask for approval again."
            )
        if not _is_newer(release.version, installed_version):
            return f"No update needed: {_TARGETS[target]['label']} is already `{installed_version}`."

        try:
            return_code = await _run_pinned_installer(release)
        except Exception:
            return (
                "The approved plugin update could not start. No credential values were exposed; "
                "run the normal PlugLayer installer in a terminal for diagnostics."
            )
        if return_code != 0:
            return (
                f"The approved {_TARGETS[target]['label']} update did not complete "
                f"(installer exit {return_code}). Re-run the normal installer in a terminal for diagnostics."
            )

        installed_after = _read_installed_version(target)
        if installed_after != release.version:
            return (
                "The installer finished but version verification failed. Restart the target app, "
                "then inspect the PlugLayer installer status before retrying."
            )
        return (
            f"✅ PlugLayer for {_TARGETS[target]['label']} updated from `{installed_version}` "
            f"to `{release.version}`. Restart or reload {_TARGETS[target]['label']} to use the new plugin."
        )

