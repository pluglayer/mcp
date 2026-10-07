import base64
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import httpx
import pytest
import tomlkit

from pluglayer_mcp import native_setup, native_health
from pluglayer_mcp.native_files import Transaction, read_json, setup_lock
from pluglayer_mcp.native_plugins import install_plugin, metadata, preflight

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "connector-" + "a" * 40
URL = "https://api.pluglayer.com/v1/plugin/install/plpi_" + "a" * 43
SOURCES = {"codex": "codex", "claude-code": "claude", "cursor": "cursor", "antigravity": "antigravity"}


def source_for(target):
    return ROOT / "plugins" / f"pluglayer-{SOURCES[target]}-plugin"


def plan_for(target):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for path in source_for(target).rglob("*"):
            if path.is_file() and not any(part in {"__pycache__", ".venv"} for part in path.parts):
                bundle.write(path, str(path.relative_to(source_for(target))))
    packed = buffer.getvalue()
    return {"schema": 1, "target": target, "connector_release": RELEASE,
            "plugin_version": metadata(source_for(target), target)[1],
            "bundle": base64.b64encode(packed).decode(), "bundle_sha256": hashlib.sha256(packed).hexdigest()}


@pytest.mark.parametrize("target", SOURCES)
def test_all_public_adapters_preserve_components_and_settings(tmp_path, target):
    home = tmp_path / "User with spaces"
    home.mkdir()
    market = home / ".agents/plugins/marketplace.json"
    market.parent.mkdir(parents=True)
    market.write_text(json.dumps({"name": "mine", "plugins": [{"name": "keep-me"}]}))
    settings = home / ".claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"custom": True, "enabledPlugins": {"other@other": True}}))
    config = home / ".codex/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('# my comment\nmodel = "keep-me"\n')
    preflight(home, source_for(target), target)
    executable = home / "runtime with spaces/pluglayer-connector"
    with Transaction() as transaction:
        destination = install_plugin(transaction, home=home, source=source_for(target), target=target,
                                     executable=executable, release=RELEASE)
        transaction.finish()
    for path in source_for(target).rglob("SKILL.md"):
        assert (destination / path.relative_to(source_for(target))).read_bytes() == path.read_bytes()
    config_path = next(destination / name for name in (".mcp.json", "mcp.json", "mcp_config.json") if (destination / name).exists())
    mcp = json.loads(config_path.read_text())
    server = mcp.get("mcpServers", mcp)["pluglayer"]
    assert server["command"] == str(executable)
    assert server["args"] == []
    assert "uvx" not in json.dumps(server)
    assert server["env"]["PLUGLAYER_CREDENTIALS_FILE"] == str(home / ".pluglayer/credentials.env")
    assert read_json(market, {})["plugins"][0]["name"] == "keep-me"
    assert read_json(settings, {})["enabledPlugins"]["other@other"] is True
    assert tomlkit.parse(config.read_text())["model"] == "keep-me"
    assert "# my comment" in config.read_text()
    if target == "antigravity":
        assert (home / ".gemini/antigravity-cli/plugins" / destination.name / "mcp_config.json").exists()


def mock_client(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(native_setup.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.parametrize("failure", ["verify", "complete"])
def test_failure_restores_exact_files_and_revokes_new_credential(monkeypatch, tmp_path, failure):
    home = tmp_path
    credentials = home / ".pluglayer/credentials.env"
    credentials.parent.mkdir()
    previous = b"# retained\r\nPLUGLAYER_API_KEY=plk_previous\r\n"
    credentials.write_bytes(previous)
    credentials.chmod(0o600)
    manifest = home / ".agents/plugins/marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"mine","plugins":[]}')
    before = manifest.read_bytes()
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/plan"):
            return httpx.Response(200, json=plan_for("codex"))
        if request.url.path.endswith("/credentials"):
            return httpx.Response(200, json={"api_key": "plk_new_test_credential"})
        if request.url.path.endswith("/complete") and failure == "complete":
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})
    mock_client(monkeypatch, handler)
    async def verify(*args):
        if failure == "verify":
            raise RuntimeError("Verification failed")
    monkeypatch.setattr(native_setup, "verify_stdio", verify)
    with pytest.raises(RuntimeError):
        native_setup.run_setup(URL, executable=Path(sys.executable), build={"release": RELEASE, "tools": ["get_current_user", "list_projects"]}, home=home)
    assert credentials.read_bytes() == previous
    if os.name != "nt":
        assert credentials.stat().st_mode & 0o777 == 0o600
    assert manifest.read_bytes() == before
    assert not (home / "plugins/pluglayer-codex-plugin").exists()
    failed = next(request for request in calls if request.url.path.endswith("/failed"))
    assert failed.headers["Authorization"] == "Bearer plk_new_test_credential"


def test_bad_existing_configuration_never_redeems_ticket(monkeypatch, tmp_path):
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text("invalid!!!")
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=plan_for("codex"))
    mock_client(monkeypatch, handler)
    with pytest.raises(Exception):
        native_setup.run_setup(URL, executable=Path(sys.executable), build={"release": RELEASE, "tools": ["get_current_user", "list_projects"]}, home=tmp_path)
    assert calls == ["/v1/plugin/install/" + "plpi_" + "a" * 43 + "/plan"]
    assert config.read_text() == "invalid!!!"


@pytest.mark.parametrize("url", ["https://evil.example/v1/plugin/install/plpi_" + "a" * 43,
                                 URL.replace("https:", "http:"), URL + "?key=value",
                                 URL.replace("api.pluglayer.com", "api.pluglayer.com@evil.example")])
def test_setup_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):
        native_setup.setup_origin(url)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "folder\\escape"])
def test_bundle_rejects_unsafe_paths(tmp_path, name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, b"test")
    packed = buffer.getvalue()
    with pytest.raises(ValueError):
        native_setup.unpack_bundle(base64.b64encode(packed).decode(), hashlib.sha256(packed).hexdigest(), tmp_path)


def test_docker_cli_alone_is_not_build_ready(monkeypatch):
    monkeypatch.setattr(native_health.shutil, "which", lambda name: "/tools/" + name)
    monkeypatch.setattr(native_health, "probe", lambda command: command[-1] != "info")
    result = native_health.doctor()
    assert result["docker_cli"] is True
    assert result["docker_daemon"] is False
    assert result["local_build_ready"] is False


def test_transaction_preserves_existing_plugin_on_error(tmp_path):
    destination = tmp_path / "plugin"
    destination.mkdir()
    (destination / "keep").write_text("old")
    source = tmp_path / "source"
    source.mkdir()
    (source / "new").write_text("new")
    with pytest.raises(RuntimeError), Transaction() as transaction:
        transaction.tree(source, destination, lambda staged: None)
        raise RuntimeError("After install")
    assert (destination / "keep").read_text() == "old"
    assert not (destination / "new").exists()


def test_parallel_setup_is_rejected_before_credentials(tmp_path):
    with setup_lock(tmp_path), pytest.raises(OSError):
        with setup_lock(tmp_path):
            pass
