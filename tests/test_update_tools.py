import asyncio
from pathlib import Path

from pluglayer_mcp.tools import updates as update_tools
from pluglayer_mcp.tools.updates import ReleaseInfo, register_update_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register


def _write_install_state(home: Path, target: str, version: str) -> None:
    state = home / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / f"{target}.env").write_text(
        f"export PLUGLAYER_PLUGIN_VERSION={version}\n",
        encoding="utf-8",
    )


def test_routine_update_check_is_cached_and_reports_only_newer_versions(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGLAYER_HOME", str(tmp_path))
    _write_install_state(tmp_path, "codex", "1.2.3")
    calls = []

    async def fake_fetch(target):
        calls.append(target)
        return ReleaseInfo(target=target, version="1.2.4", commit_sha="a" * 40)

    monkeypatch.setattr(update_tools, "_fetch_latest_release", fake_fetch)
    mcp = FakeMCP()
    register_update_tools(mcp)

    first = asyncio.run(mcp.tools["check_plugin_updates"]())
    second = asyncio.run(mcp.tools["check_plugin_updates"]())

    assert "installed `1.2.3`, available `1.2.4`" in first
    assert "user_approved=true" in first
    assert "available `1.2.4`" in second
    assert calls == ["codex"]
    assert (tmp_path / "state" / "plugin-update-check.json").stat().st_mode & 0o777 == 0o600


def test_routine_update_check_stays_silent_when_current(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGLAYER_HOME", str(tmp_path))
    _write_install_state(tmp_path, "cursor", "2.0.0")

    async def fake_fetch(target):
        return ReleaseInfo(target=target, version="2.0.0", commit_sha="b" * 40)

    monkeypatch.setattr(update_tools, "_fetch_latest_release", fake_fetch)
    mcp = FakeMCP()
    register_update_tools(mcp)

    result = asyncio.run(mcp.tools["check_plugin_updates"]())

    assert "Do not mention" in result
    assert "PlugLayer plugin update available:" not in result


def test_update_requires_consent_and_exact_fresh_version(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGLAYER_HOME", str(tmp_path))
    _write_install_state(tmp_path, "claude", "1.0.0")

    async def fake_fetch(target):
        return ReleaseInfo(target=target, version="1.1.0", commit_sha="c" * 40)

    monkeypatch.setattr(update_tools, "_fetch_latest_release", fake_fetch)
    mcp = FakeMCP()
    register_update_tools(mcp)

    refused = asyncio.run(mcp.tools["update_plugin"]("claude", "1.1.0"))
    changed = asyncio.run(mcp.tools["update_plugin"]("claude", "1.2.0", True))

    assert "explicit user approval" in refused
    assert "latest Claude Code version is now `1.1.0`" in changed


def test_approved_update_runs_pinned_installer_and_verifies(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGLAYER_HOME", str(tmp_path))
    _write_install_state(tmp_path, "antigravity", "1.0.0")
    release = ReleaseInfo(target="antigravity", version="1.1.0", commit_sha="d" * 40)

    async def fake_fetch(target):
        return release

    async def fake_installer(received):
        assert received == release
        _write_install_state(tmp_path, "antigravity", "1.1.0")
        return 0

    monkeypatch.setattr(update_tools, "_fetch_latest_release", fake_fetch)
    monkeypatch.setattr(update_tools, "_run_pinned_installer", fake_installer)
    mcp = FakeMCP()
    register_update_tools(mcp)

    result = asyncio.run(mcp.tools["update_plugin"]("antigravity", "1.1.0", True))

    assert "updated from `1.0.0` to `1.1.0`" in result
    assert "Restart or reload Antigravity" in result
