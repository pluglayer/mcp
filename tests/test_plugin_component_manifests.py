import json
import subprocess
import tomllib
from pathlib import Path


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_plugins_declare_mcp_components_in_target_native_shape():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"

    codex_root = plugins / "pluglayer-codex-plugin"
    codex_manifest = _json(codex_root / ".codex-plugin" / "plugin.json")
    assert codex_manifest["mcpServers"] == "./.mcp.json"
    assert "pluglayer" in _json(codex_root / ".mcp.json")

    claude_root = plugins / "pluglayer-claude-plugin"
    claude_mcp = _json(claude_root / ".mcp.json")
    assert "mcpServers" not in claude_mcp
    assert "pluglayer" in claude_mcp

    cursor_root = plugins / "pluglayer-cursor-plugin"
    cursor_manifest = _json(cursor_root / ".cursor-plugin" / "plugin.json")
    assert cursor_manifest["mcp"] == "./mcp.json"
    cursor_mcp = _json(cursor_root / "mcp.json")
    assert "pluglayer" in cursor_mcp
    cursor_command = cursor_mcp["pluglayer"]["args"][-1]
    assert cursor_mcp["pluglayer"]["args"][0] == "-c"
    assert "PLUGLAYER_CREDENTIALS_FILE" in cursor_command
    assert "uvx pluglayer-mcp@latest" in cursor_command
    assert ". \"$credential_file\"" not in cursor_command
    assert "exit 78" not in cursor_command

    antigravity_root = plugins / "pluglayer-antigravity-plugin"
    antigravity_mcp = _json(antigravity_root / "mcp_config.json")
    assert "pluglayer" in antigravity_mcp["mcpServers"]


def test_cursor_plugin_starts_without_auth_for_live_tool_discovery(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    cursor_mcp = _json(
        repo_root / "plugins" / "pluglayer-cursor-plugin" / "mcp.json"
    )
    cursor_command = cursor_mcp["pluglayer"]["args"][-1]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uvx = bin_dir / "uvx"
    uvx.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$PLUGLAYER_CREDENTIALS_FILE\" \"$*\"\n",
        encoding="utf-8",
    )
    uvx.chmod(0o755)
    env = {
        "HOME": str(tmp_path),
        "PATH": str(bin_dir),
    }

    result = subprocess.run(
        ["/bin/bash", "-c", cursor_command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        str(tmp_path / ".pluglayer" / "credentials.env"),
        "pluglayer-mcp@latest",
    ]


def test_cursor_installer_warns_about_duplicate_mcp_registration():
    repo_root = Path(__file__).resolve().parents[2]
    installer = (
        repo_root / "plugins" / "pluglayer-cursor-plugin" / "install-common.sh"
    ).read_text(encoding="utf-8")

    assert "warn_cursor_duplicate_mcp" in installer
    assert '${HOME}/.cursor/mcp.json' in installer
    assert '${INVOKED_FROM_DIR}/.cursor/mcp.json' in installer
    assert "different authentication state" in installer


def test_mcp_python_sdk_stays_on_fastmcp_compatible_v1():
    repo_root = Path(__file__).resolve().parents[2]
    with (repo_root / "pluglayer-mcp" / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    mcp_requirement = next(
        dependency
        for dependency in project["dependencies"]
        if dependency.startswith("mcp[")
    )
    assert ">=1.28" in mcp_requirement
    assert "<2" in mcp_requirement


def test_every_plugin_exposes_feedback_intelligence():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"
    roots = [
        plugins / "pluglayer-codex-plugin",
        plugins / "pluglayer-claude-plugin",
        plugins / "pluglayer-cursor-plugin",
        plugins / "pluglayer-antigravity-plugin",
    ]

    for root in roots:
        skill = root / "skills" / "share-feedback" / "SKILL.md"
        assert skill.exists(), f"{root.name} is missing share-feedback"
        text = skill.read_text(encoding="utf-8")
        assert "submit_feedback" in text
        assert "update_my_feedback" in text
        assert "credentials" in text or "tokens" in text
        assert "full logs" in text

    assert (plugins / "pluglayer-claude-plugin" / "agents" / "pluglayer-feedback.md").exists()
    assert (plugins / "pluglayer-cursor-plugin" / "agents" / "pluglayer-feedback.md").exists()
    assert (plugins / "pluglayer-antigravity-plugin" / "agents" / "pluglayer-feedback.md").exists()
    assert (plugins / "pluglayer-cursor-plugin" / "rules" / "pluglayer-feedback.mdc").exists()
    assert (plugins / "pluglayer-antigravity-plugin" / "rules" / "pluglayer-feedback.md").exists()

    workflow_expectations = {
        "pluglayer-codex-plugin-main.yml": ["skills\" / \"share-feedback\" / \"SKILL.md"],
        "pluglayer-claude-plugin-main.yml": [
            "agents\" / \"pluglayer-feedback.md",
            "skills\" / \"share-feedback\" / \"SKILL.md",
        ],
        "pluglayer-cursor-plugin-main.yml": [
            "rules\" / \"pluglayer-feedback.mdc",
            "agents\" / \"pluglayer-feedback.md",
            "skills\" / \"share-feedback\" / \"SKILL.md",
        ],
        "pluglayer-antigravity-plugin-main.yml": [
            "rules\" / \"pluglayer-feedback.md",
            "agents\" / \"pluglayer-feedback.md",
            "skills\" / \"share-feedback\" / \"SKILL.md",
        ],
    }
    workflows = repo_root / ".github" / "workflows"
    for filename, expected_fragments in workflow_expectations.items():
        workflow = (workflows / filename).read_text(encoding="utf-8")
        for fragment in expected_fragments:
            assert fragment in workflow, f"{filename} does not validate {fragment}"


def test_public_plugins_expose_project_metadata_updates():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"
    roots = [
        plugins / "pluglayer-codex-plugin",
        plugins / "pluglayer-claude-plugin",
        plugins / "pluglayer-cursor-plugin",
        plugins / "pluglayer-antigravity-plugin",
    ]

    for root in roots:
        deploy_skill = root / "skills" / "deploy-app" / "SKILL.md"
        text = deploy_skill.read_text(encoding="utf-8")
        assert "update_project_metadata" in text
        assert "description" in text
        assert "custom-domain" in text or "custom domain" in text
