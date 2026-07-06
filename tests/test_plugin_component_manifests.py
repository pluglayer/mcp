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
