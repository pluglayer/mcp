import json
import tomllib
from pathlib import Path


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_plugins_declare_hosted_oauth_mcp_components():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"
    codex_mcp = _json(plugins / "pluglayer-codex-plugin" / ".mcp.json")
    assert codex_mcp["mcpServers"]["pluglayer"] == {"type": "http", "url": "https://mcp.pluglayer.com/mcp", "extensions": {"com.openai": {"auth": {"type": "oauth"}}}}
    assert _json(plugins / "pluglayer-claude-plugin" / ".mcp.json")["pluglayer"] == {"type": "http", "url": "https://mcp.pluglayer.com/mcp"}
    assert _json(plugins / "pluglayer-cursor-plugin" / "mcp.json")["pluglayer"] == {"url": "https://mcp.pluglayer.com/mcp"}
    assert _json(plugins / "pluglayer-antigravity-plugin" / "mcp_config.json")["mcpServers"]["pluglayer"] == {"serverUrl": "https://mcp.pluglayer.com/mcp"}


def test_public_plugin_icons_follow_target_manifest_schemas():
    repo_root = Path(__file__).resolve().parents[2]
    plugins = repo_root / "plugins"
    icon_url = "https://pluglayer.com/pluglayer-icon.png"

    codex_root = plugins / "pluglayer-codex-plugin"
    codex = _json(codex_root / ".codex-plugin" / "plugin.json")
    assert codex["interface"]["composerIcon"] == "./assets/pluglayer-icon.png"
    assert codex["interface"]["logo"] == "./assets/pluglayer-icon.png"
    assert (codex_root / "assets" / "pluglayer-icon.png").is_file()

    cursor = _json(plugins / "pluglayer-cursor-plugin" / ".cursor-plugin" / "plugin.json")
    assert cursor["logo"] == icon_url

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
