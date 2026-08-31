import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "pluglayer-codex-plugin"
INSTALLER = PLUGIN_ROOT / "install-common.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_installer(
    tmp_path: Path, *, cli_fails: bool = False
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "uvx", "#!/bin/sh\nexit 0\n")
    _write_executable(
        bin_dir / "codex",
        f"""#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$HOME/codex-calls"
if [ "$1 $2" = "plugin remove" ]; then
  rm -rf "$HOME/.codex/plugins/cache/personal/pluglayer-codex-plugin"
  exit 0
fi
if [ "$1 $2" = "plugin add" ]; then
  {"exit 23" if cli_fails else ":"}
  source_manifest="$HOME/plugins/pluglayer-codex-plugin/.codex-plugin/plugin.json"
  version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"version\"])' "$source_manifest")"
  cache="$HOME/.codex/plugins/cache/personal/pluglayer-codex-plugin/$version"
  mkdir -p "$cache"
  cp -R "$HOME/plugins/pluglayer-codex-plugin/." "$cache/"
  printf 'Installed plugin root: %s\n' "$cache"
  exit 0
fi
exit 2
""",
    )

    # Reproduce the old broken destination with a stale manifest. The fixed
    # installer must never let Codex install from this directory.
    stale_manifest = (
        tmp_path
        / ".agents"
        / "plugins"
        / "plugins"
        / "pluglayer-codex-plugin"
        / ".codex-plugin"
        / "plugin.json"
    )
    stale_manifest.parent.mkdir(parents=True)
    stale_manifest.write_text(
        json.dumps({"name": "pluglayer-codex-plugin", "version": "1.1.7"}),
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PLUGLAYER_API_KEY": "plk_test_only",
        "PLUGLAYER_API_URL": "https://api.pluglayer.test",
        "PLUGLAYER_CODEX_CLI": str(bin_dir / "codex"),
        "PLUGLAYER_INSTALL_TARGET": "codex",
        "PLUGLAYER_PLUGIN_SOURCE_DIR": str(PLUGIN_ROOT),
        "PLUGLAYER_PLUGIN_SOURCE_RELATIVE_PATH": ".",
        "PLUGLAYER_QUICK_INSTALL": "1",
    }
    return subprocess.run(
        ["bash", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_codex_installer_updates_effective_source_and_verified_cache(tmp_path):
    expected_version = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]

    result = _run_installer(tmp_path)

    assert result.returncode == 0, result.stderr
    source_manifest = tmp_path / "plugins" / "pluglayer-codex-plugin"
    source_manifest = source_manifest / ".codex-plugin" / "plugin.json"
    cache_manifest = (
        tmp_path
        / ".codex"
        / "plugins"
        / "cache"
        / "personal"
        / "pluglayer-codex-plugin"
        / expected_version
        / ".codex-plugin"
        / "plugin.json"
    )
    marketplace = json.loads(
        (tmp_path / ".agents" / "plugins" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    entry = next(
        item
        for item in marketplace["plugins"]
        if item["name"] == "pluglayer-codex-plugin"
    )

    assert (
        json.loads(source_manifest.read_text(encoding="utf-8"))["version"]
        == expected_version
    )
    assert (
        json.loads(cache_manifest.read_text(encoding="utf-8"))["version"]
        == expected_version
    )
    assert tmp_path / entry["source"]["path"] == (
        tmp_path / "plugins" / "pluglayer-codex-plugin"
    )
    assert f"Verified Codex installed PlugLayer {expected_version}" in result.stdout
    assert f"Installed version: {expected_version}" in result.stdout


def test_codex_installer_does_not_report_success_when_registration_fails(tmp_path):
    result = _run_installer(tmp_path, cli_fails=True)

    assert result.returncode != 0
    assert "Codex registration failed" in result.stderr
    assert "All set" not in result.stdout
    assert not (tmp_path / ".pluglayer" / "state" / "codex.env").exists()
