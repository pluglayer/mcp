"""Commit-pinned public plugin updates without reinstalling Python or uv."""

import asyncio
import base64
import hashlib
import re
import sys
import tempfile
import subprocess
from pathlib import Path

import httpx

from pluglayer_mcp.native_files import Transaction, setup_lock
from pluglayer_mcp.native_health import build_info, verify_stdio
from pluglayer_mcp.native_plugins import install_plugin, metadata, preflight
from pluglayer_mcp.native_setup import unpack_bundle

REPOSITORIES = {"codex": "codex-plugin", "claude": "claude-plugin", "cursor": "cursor-plugin",
                "antigravity": "antigravity-plugin"}


def upgrade(target: str, version: str, commit: str) -> None:
    if target not in REPOSITORIES or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Invalid approved public release")
    from pluglayer_mcp.native_runtime import refresh_connector
    executable = refresh_connector(build_info()["release"])
    if executable:
        subprocess.run([str(executable), "--upgrade", target, version, commit], check=True, timeout=600)
        return
    actual_target = "claude-code" if target == "claude" else target
    url = f"https://github.com/pluglayer/{REPOSITORIES[target]}/archive/{commit}.zip"
    with tempfile.TemporaryDirectory(prefix="pluglayer-upgrade-") as temporary:
        source = Path(temporary)
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            packed = response.content
        unpack_bundle(base64.b64encode(packed).decode(), hashlib.sha256(packed).hexdigest(), source)
        roots = list(source.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError("Invalid public release archive")
        source = roots[0]
        if metadata(source, actual_target)[1] != version:
            raise ValueError("The public archive does not match the approved version")
        home = Path.home()
        preflight(home, source, actual_target)
        executable = Path(sys.executable).resolve()
        with setup_lock(home / ".pluglayer"), Transaction() as transaction:
            install_plugin(transaction, home=home, source=source, target=actual_target,
                           executable=executable, release=build_info()["release"])
            asyncio.run(verify_stdio(executable, home / ".pluglayer/credentials.env", build_info()["tools"]))
            transaction.finish()
    print("Approved public plugin update verified. Reload the agent to activate it.")
