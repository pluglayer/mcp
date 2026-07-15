import json
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
    assert "pluglayer" in _json(cursor_root / "mcp.json")

    antigravity_root = plugins / "pluglayer-antigravity-plugin"
    antigravity_mcp = _json(antigravity_root / "mcp_config.json")
    assert "pluglayer" in antigravity_mcp["mcpServers"]


def test_every_plugin_exposes_feedback_intelligence():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"
    roots = [
        plugins / "pluglayer-codex-plugin",
        plugins / "pluglayer-claude-plugin",
        plugins / "pluglayer-cursor-plugin",
        plugins / "pluglayer-antigravity-plugin",
        plugins / "pluglayer-codex-ops-plugin",
    ]

    for root in roots:
        skill = root / "skills" / "share-feedback" / "SKILL.md"
        assert skill.exists(), f"{root.name} is missing share-feedback"
        text = skill.read_text(encoding="utf-8")
        assert "submit_feedback" in text
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
