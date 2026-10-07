"""Public agent adapters sharing one self-contained stdio executable."""

from __future__ import annotations

import json
import shlex
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import tomlkit

from pluglayer_mcp.native_files import Transaction, read_json

MANIFESTS = {"codex": ".codex-plugin/plugin.json", "claude-code": ".claude-plugin/plugin.json",
             "cursor": ".cursor-plugin/plugin.json", "antigravity": "plugin.json"}


def metadata(source: Path, target: str) -> tuple[str, str]:
    import re
    manifest = read_json(source / MANIFESTS[target], {})
    name = manifest["name"]
    version = (source / "VERSION").read_text().strip() if target == "antigravity" else manifest["version"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        raise ValueError("Invalid public plugin name")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("Invalid plugin version")
    return name, version


def preflight(home: Path, source: Path, target: str) -> None:
    metadata(source, target)
    paths = {"codex": [".agents/plugins/marketplace.json"],
             "claude-code": [".claude/plugins/known_marketplaces.json", ".claude/plugins/installed_plugins.json", ".claude/settings.json"],
             "cursor": [], "antigravity": []}[target]
    for filename in paths:
        value = read_json(home / filename, {})
        if filename.endswith("marketplace.json") and not isinstance(value.get("plugins", []), list):
            raise ValueError("Marketplace plugins must be a list")
        if filename.endswith("installed_plugins.json") and not isinstance(value.get("plugins", {}), dict):
            raise ValueError("Installed plugin registry is malformed")
        if filename.endswith("settings.json") and not isinstance(value.get("enabledPlugins", {}), dict):
            raise ValueError("Existing Claude plugin settings are malformed")
    if target == "codex":
        path = home / ".codex/config.toml"
        if path.is_symlink():
            raise ValueError("Codex settings must not be a symbolic link")
        config = tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()
        if not isinstance(config.get("plugins", {}), dict):
            raise ValueError("Codex plugin settings are malformed")
    # Validate every shipped MCP declaration before credentials are redeemed.
    for filename in (".mcp.json", "mcp.json", "mcp_config.json"):
        if (source / filename).exists():
            config = read_json(source / filename, {})
            if "pluglayer" not in config.get("mcpServers", config):
                raise ValueError("Public plugin has no PlugLayer MCP declaration")


def configure(source: Path, executable: Path, credentials: Path) -> None:
    found = False
    for filename in (".mcp.json", "mcp.json", "mcp_config.json"):
        path = source / filename
        if not path.exists():
            continue
        config = read_json(path, {})
        servers = config.get("mcpServers", config)
        servers["pluglayer"] = {"command": str(executable), "args": [],
                                "env": {"PLUGLAYER_CREDENTIALS_FILE": str(credentials)}}
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        found = True
    if not found:
        raise ValueError("Plugin has no MCP configuration")
    hooks_path = source / "hooks.json"
    if hooks_path.exists():
        hooks = read_json(hooks_path, {})
        arguments = [str(executable), "--command-safety-hook"]
        command = subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
        for event in hooks.get("pluglayer-command-safety", {}).get("PreToolUse", []):
            for hook in event.get("hooks", []):
                if hook.get("command") == "python3 scripts/command_safety_hook.py":
                    hook["command"] = command
        hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")


def install_plugin(transaction: Transaction, *, home: Path, source: Path, target: str,
                   executable: Path, release: str) -> Path:
    name, version = metadata(source, target)
    credentials = home / ".pluglayer/credentials.env"
    destinations = {"codex": home / "plugins" / name,
                    "cursor": home / ".cursor/plugins/local" / name,
                    "antigravity": home / ".gemini/config/plugins" / name,
                    "claude-code": home / ".pluglayer/plugins/claude" / name}
    destination = destinations[target]
    copy = lambda src, dst: transaction.tree(src, dst, lambda staged: configure(staged, executable, credentials))
    copy(source, destination)
    now = datetime.now(timezone.utc).isoformat()
    if target == "codex":
        path = home / ".agents/plugins/marketplace.json"
        market = read_json(path, {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []})
        market.setdefault("name", "personal")
        entry = {"name": name, "source": {"source": "local", "path": f"./plugins/{name}"},
                 "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Developer Tools"}
        market["plugins"] = [item for item in market.get("plugins", []) if item.get("name") != name] + [entry]
        transaction.json(path, market)
        config_path = home / ".codex/config.toml"
        config = tomlkit.parse(config_path.read_text()) if config_path.exists() else tomlkit.document()
        config.setdefault("plugins", {}).setdefault(f"{name}@{market['name']}", {})["enabled"] = True
        transaction.write(config_path, tomlkit.dumps(config))
    elif target == "claude-code":
        market_name = "pluglayer"
        cache = home / ".claude/plugins/cache" / market_name / name / version
        copy(source, cache)
        path = home / ".claude/plugins/known_marketplaces.json"
        known = read_json(path, {})
        known[market_name] = {"source": {"source": "directory", "path": str(destination)},
                              "installLocation": str(destination), "lastUpdated": now}
        transaction.json(path, known)
        path = home / ".claude/plugins/installed_plugins.json"
        installed = read_json(path, {"version": 2, "plugins": {}})
        entries = installed.setdefault("plugins", {}).get(f"{name}@{market_name}", [])
        installed["plugins"][f"{name}@{market_name}"] = [item for item in entries if item.get("scope") != "user"] + [
            {"scope": "user", "installPath": str(cache), "version": version, "installedAt": now, "lastUpdated": now}]
        transaction.json(path, installed)
        path = home / ".claude/settings.json"
        settings = read_json(path, {})
        settings.setdefault("enabledPlugins", {})[f"{name}@{market_name}"] = True
        transaction.json(path, settings)
    elif target == "antigravity":
        copy(source, home / ".gemini/antigravity-cli/plugins" / name)
    tracked_target = "claude" if target == "claude-code" else target
    state = {"PLUGLAYER_TARGET": tracked_target, "PLUGLAYER_PLUGIN_VERSION": version,
             "PLUGLAYER_PLUGIN_DIR": str(destination), "PLUGLAYER_INSTALLED_AT": now,
             "PLUGLAYER_CONNECTOR": str(executable), "PLUGLAYER_CONNECTOR_RELEASE": release}
    transaction.write(home / ".pluglayer/state" / f"{tracked_target}.env",
                      "".join(f"export {key}={shlex.quote(value)}\n" for key, value in state.items()), private=True)
    return destination
