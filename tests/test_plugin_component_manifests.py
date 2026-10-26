import json
import tomllib
from pathlib import Path


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_plugins_declare_hosted_oauth_mcp_components():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"
    codex_mcp = _json(plugins / "pluglayer-codex-plugin" / ".mcp.json")
    assert codex_mcp["mcpServers"]["pluglayer"]["type"] == "http"
    assert codex_mcp["mcpServers"]["pluglayer"]["url"] == "https://mcp.pluglayer.com/mcp"
    assert set(codex_mcp["mcpServers"]["pluglayer"]) == {"type", "url"}
    codex_portable_mcp = _json(plugins / "pluglayer-codex-plugin" / "mcp.json")
    assert codex_portable_mcp["$schema"].endswith("/mcp.schema.json")
    assert codex_portable_mcp["mcpServers"]["pluglayer"]["type"] == "streamable-http"
    # Codex 0.162 rejects server-level extensions before reaching OAuth. Both
    # package formats rely on protected-resource/authorization-server discovery.
    assert set(codex_portable_mcp["mcpServers"]["pluglayer"]) == {"type", "url"}
    assert _json(plugins / "pluglayer-claude-plugin" / ".mcp.json")["pluglayer"] == {"type": "http", "url": "https://mcp.pluglayer.com/mcp"}
    assert _json(plugins / "pluglayer-cursor-plugin" / "mcp.json")["mcpServers"]["pluglayer"] == {"url": "https://mcp.pluglayer.com/mcp"}
    assert _json(plugins / "pluglayer-antigravity-plugin" / "mcp_config.json")["mcpServers"]["pluglayer"] == {"serverUrl": "https://mcp.pluglayer.com/mcp"}


def test_public_plugin_icons_follow_target_manifest_schemas():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"
    icon_url = "https://pluglayer.com/pluglayer-icon.png"

    codex_root = plugins / "pluglayer-codex-plugin"
    codex_portable = _json(codex_root / "plugin.json")
    assert codex_portable["$schema"].endswith("/plugin.schema.json")
    assert codex_portable["extensions"]["com.openai"]["interface"]["composerIcon"] == "./assets/pluglayer-icon.png"
    codex = _json(codex_root / ".codex-plugin" / "plugin.json")
    assert codex["interface"]["composerIcon"] == "./assets/pluglayer-icon.png"
    assert codex["interface"]["logo"] == "./assets/pluglayer-icon.png"
    assert (codex_root / "assets" / "pluglayer-icon.png").is_file()
    for interface in (codex_portable["extensions"]["com.openai"]["interface"], codex["interface"]):
        assert 1 <= len(interface["defaultPrompt"]) <= 3

    cursor = _json(plugins / "pluglayer-cursor-plugin" / ".cursor-plugin" / "plugin.json")
    assert cursor["logo"] == "./assets/pluglayer-icon.png"
    assert (plugins / "pluglayer-cursor-plugin" / cursor["logo"]).is_file()
    assert cursor["mcpServers"] == "./mcp.json"
    assert cursor["hooks"] == "./hooks/hooks.json"

    claude = _json(plugins / "pluglayer-claude-plugin" / ".claude-plugin" / "plugin.json")
    assert "logo" not in claude and "icon" not in claude

    antigravity = _json(plugins / "pluglayer-antigravity-plugin" / "plugin.json")
    assert set(antigravity) == {"name", "description"}

    server = (repo_root / "pluglayer-mcp" / "pluglayer_mcp" / "server.py").read_text()
    assert f'Icon(src="{icon_url}")' in server


def test_every_public_plugin_bundles_marketplace_update_guidance():
    repo_root = Path(__file__).resolve().parents[2]
    for target in ("codex", "claude", "cursor", "antigravity"):
        skill = (
            repo_root
            / "plugins"
            / f"pluglayer-{target}-plugin"
            / "skills"
            / "manage-plugin-updates"
            / "SKILL.md"
        )
        text = skill.read_text(encoding="utf-8")
        assert "marketplace" in text
        assert "shell installer" in text
        assert "API token" in text


def test_codex_bundles_all_public_agent_definitions_and_setup_skill():
    repo_root = Path(__file__).resolve().parents[2]
    root = repo_root / "plugins" / "pluglayer-codex-plugin"
    expected = {
        "pluglayer-deploy.toml",
        "pluglayer-domain-setup.toml",
        "pluglayer-feedback.toml",
        "pluglayer-fix-deploy.toml",
        "pluglayer-security.toml",
        "pluglayer-setup-cicd.toml",
        "pluglayer-templates.toml",
    }
    assert {p.name for p in (root / "agents").glob("*.toml")} == expected
    for path in (root / "agents").glob("*.toml"):
        agent = tomllib.loads(path.read_text(encoding="utf-8"))
        assert set(("name", "description", "developer_instructions")) <= set(agent)
    setup = (root / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    assert "~/.codex/agents/" in setup
    assert "Cloud ChatGPT cannot register local Codex TOML agents" in setup
    router = (root / "skills" / "use-pluglayer" / "SKILL.md").read_text(encoding="utf-8")
    assert "Do not use the browser" in router
    assert "list_projects" in router
    assert "Do not use for projects" in setup


def test_native_agent_packs_are_complete_across_editor_plugins():
    repo_root = Path(__file__).resolve().parents[2]
    expected = {
        "pluglayer-deploy.md",
        "pluglayer-domain-setup.md",
        "pluglayer-feedback.md",
        "pluglayer-fix-deploy.md",
        "pluglayer-security.md",
        "pluglayer-setup-cicd.md",
        "pluglayer-templates.md",
    }
    for target in ("claude", "cursor", "antigravity"):
        root = repo_root / "plugins" / f"pluglayer-{target}-plugin"
        assert {p.name for p in (root / "agents").glob("*.md")} == expected


def test_every_public_plugin_publishes_target_installation_instructions():
    repo_root = Path(__file__).resolve().parents[2]
    expected_version = "1.1.44"
    for target in ("codex", "claude", "cursor", "antigravity"):
        path = repo_root / "plugins" / f"pluglayer-{target}-plugin" / "installation_instruction.md"
        text = path.read_text(encoding="utf-8")
        assert f"Current public release: `{expected_version}`" in text
        assert "https://mcp.pluglayer.com/mcp" in text
        assert "get_current_user" in text and "list_projects" in text
        assert "Never request or print an API token" in text
        assert "Do not ask the user to type terminal commands" in text


def test_all_public_plugin_versions_are_aligned():
    repo_root = Path(__file__).resolve().parents[2]
    expected = "1.1.44"
    versions = {
        "codex-portable": _json(repo_root / "plugins/pluglayer-codex-plugin/plugin.json")["version"],
        "codex-legacy": _json(repo_root / "plugins/pluglayer-codex-plugin/.codex-plugin/plugin.json")["version"],
        "claude": _json(repo_root / "plugins/pluglayer-claude-plugin/.claude-plugin/plugin.json")["version"],
        "cursor": _json(repo_root / "plugins/pluglayer-cursor-plugin/.cursor-plugin/plugin.json")["version"],
        "antigravity": (repo_root / "plugins/pluglayer-antigravity-plugin/VERSION").read_text().strip(),
    }
    assert versions == {name: expected for name in versions}
    import re
    for target in ("codex", "claude", "cursor", "antigravity"):
        changelog = (repo_root / f"plugins/pluglayer-{target}-plugin/CHANGELOG.md").read_text()
        assert re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.M).group(1) == expected


def test_every_plugin_has_setup_and_claude_does_not_override_main_agent():
    root = Path(__file__).resolve().parents[2] / "plugins"
    for target in ("codex", "claude", "cursor", "antigravity"):
        plugin = root / f"pluglayer-{target}-plugin"
        setup = (plugin / "skills/setup/SKILL.md").read_text(encoding="utf-8")
        router = (plugin / "skills/use-pluglayer/SKILL.md").read_text(encoding="utf-8")
        assert "Do not use for projects" in setup
        assert "Do not use the browser" in router
        assert "list_projects" in router
    assert "list_projects" in (root / "pluglayer-cursor-plugin/rules/pluglayer-use.mdc").read_text(encoding="utf-8")
    assert "list_projects" in (root / "pluglayer-antigravity-plugin/rules/pluglayer-use.md").read_text(encoding="utf-8")
    assert not (root / "pluglayer-claude-plugin/settings.json").exists()


def test_awareness_hooks_emit_only_static_context():
    import subprocess
    root = Path(__file__).resolve().parents[2] / "plugins"
    for target in ("claude", "cursor"):
        hooks = _json(root / f"pluglayer-{target}-plugin/hooks/hooks.json")["hooks"]
        command = (hooks["SessionStart"][0]["hooks"][0] if target == "claude" else hooks["sessionStart"][0])["command"]
        assert command.startswith("echo '") and "$" not in command and "`" not in command
        result = subprocess.run(["/bin/sh", "-c", command], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        context = payload["hookSpecificOutput"]["additionalContext"] if target == "claude" else payload["additional_context"]
        assert "Unrelated work keeps the normal agent" in context
        assert "list_projects" in context
        assert "not the browser" in context


def test_public_codex_repository_declares_one_stable_marketplace():
    repo_root = Path(__file__).resolve().parents[2]
    catalog = _json(repo_root / "plugins/pluglayer-codex-plugin/.agents/plugins/marketplace.json")
    assert catalog["name"] == "pluglayer"
    assert [entry["name"] for entry in catalog["plugins"]] == ["pluglayer-codex-plugin"]
    assert catalog["plugins"][0]["source"] == {"source": "url", "url": "https://github.com/pluglayer/codex-plugin"}


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


def test_security_skills_and_target_entrypoints_ship_in_every_public_plugin():
    repo = Path(__file__).resolve().parents[2]
    canonical = repo / "plugins" / "pluglayer-codex-plugin" / "skills"
    for target in ("codex", "claude", "cursor", "antigravity"):
        root = repo / "plugins" / f"pluglayer-{target}-plugin"
        workflow = (repo / ".github/workflows" / f"pluglayer-{target}-plugin-main.yml").read_text()
        for skill in ("check-app-security", "manage-app-access"):
            assert (root / "skills" / skill / "SKILL.md").read_text() == (canonical / skill / "SKILL.md").read_text()
            assert (root / "skills" / skill / "agents/openai.yaml").is_file()
            assert f'root / "skills" / "{skill}" / "SKILL.md"' in workflow
        if target != "codex":
            assert (root / "agents/pluglayer-security.md").is_file()
            assert 'root / "agents" / "pluglayer-security.md"' in workflow
        if target in ("cursor", "antigravity"):
            suffix = "mdc" if target == "cursor" else "md"
            assert (root / "rules" / f"pluglayer-security.{suffix}").is_file()
            assert f'root / "rules" / "pluglayer-security.{suffix}"' in workflow
