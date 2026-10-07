"""One-use public setup client. Credentials never leave this process as output."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import os
import re
import shlex
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx

from pluglayer_mcp.native_files import Transaction, secure_directory, setup_lock
from pluglayer_mcp.native_health import doctor, verify_stdio
from pluglayer_mcp.native_plugins import install_plugin, metadata, preflight


def setup_origin(url: str) -> str:
    parsed = urlsplit(url)
    local = os.environ.get("PLUGLAYER_ALLOW_LOCAL_SETUP") == "1" and parsed.hostname in {"localhost", "127.0.0.1"}
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or not re.fullmatch(r"/v1/plugin/install/plpi_[A-Za-z0-9_-]{20,100}", parsed.path)
            or (not local and (parsed.scheme != "https" or parsed.netloc not in {"api.pluglayer.com", "api.dev.pluglayer.com"}))
            or (local and parsed.scheme not in {"http", "https"})):
        raise ValueError("Setup requires an official PlugLayer URL from the portal")
    return f"{parsed.scheme}://{parsed.netloc}"


def unpack_bundle(encoded: str, digest: str, destination: Path) -> None:
    packed = base64.b64decode(encoded, validate=True)
    if len(packed) > 8 * 1024 * 1024 or hashlib.sha256(packed).hexdigest() != digest:
        raise ValueError("Public plugin bundle verification failed")
    total = 0
    seen = set()
    with zipfile.ZipFile(io.BytesIO(packed)) as bundle:
        for entry in bundle.infolist():
            path = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename
                    or stat.S_ISLNK(mode) or path in seen):
                raise ValueError("Unsafe plugin bundle member")
            seen.add(path)
            total += entry.file_size
            if total > 64 * 1024 * 1024:
                raise ValueError("Public plugin bundle extracted size is excessive")
            target = destination.joinpath(*path.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(entry))


def request_json(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    response = client.request(method, url, **kwargs)
    if response.status_code != 200:
        # Do not include URLs, credential response bodies, or HTTP exceptions.
        raise RuntimeError(f"PlugLayer setup request failed (HTTP {response.status_code}). Copy a new prompt from the portal.")
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Invalid setup response")
    return result


def run_setup(url: str, *, executable: Path, build: dict, home: Path | None = None) -> dict:
    origin = setup_origin(url)
    home = home or Path.home()
    if not re.fullmatch(r"connector-[0-9a-f]{40}", build["release"]):
        raise ValueError("A release-built connector is required for setup")
    tools = build["tools"]
    if not {"get_current_user", "list_projects"}.issubset(tools):
        raise ValueError("Connector release is missing required public tools")
    secure_directory(home / ".pluglayer")
    with setup_lock(home / ".pluglayer"):
        return _install(url, origin=origin, executable=executable, build=build, home=home)


def _install(url: str, *, origin: str, executable: Path, build: dict, home: Path) -> dict:
    tools = build["tools"]
    key = ""
    with httpx.Client(timeout=60, follow_redirects=False) as client, tempfile.TemporaryDirectory(prefix="pluglayer-plugin-") as temporary:
        plan = request_json(client, "GET", url + "/plan")
        if plan["schema"] != 1 or plan["connector_release"] != build["release"]:
            raise ValueError("Connector and portal release do not match")
        target = plan["target"]
        source = Path(temporary)
        unpack_bundle(plan["bundle"], plan["bundle_sha256"], source)
        if metadata(source, target)[1] != plan["plugin_version"]:
            raise ValueError("Plugin version does not match the setup session")
        preflight(home, source, target)
        secure_directory(home / ".pluglayer")
        credentials = home / ".pluglayer/credentials.env"
        if credentials.is_symlink():
            raise ValueError("Credentials must not be stored through a symbolic link")
        result = request_json(client, "POST", url + "/credentials", json={"connector_release": build["release"]})
        key = result["api_key"]
        try:
            if not isinstance(key, str) or not key.startswith("plk_") or any(ord(c) < 32 or ord(c) == 127 for c in key):
                raise ValueError("Invalid setup credential")
            with Transaction() as transaction:
                transaction.write(credentials, f"PLUGLAYER_API_KEY={shlex.quote(key)}\nPLUGLAYER_API_URL={shlex.quote(origin)}\n", private=True)
                install_plugin(transaction, home=home, source=source, target=target, executable=executable, release=build["release"])
                asyncio.run(verify_stdio(executable, credentials, tools))
                request_json(client, "POST", url + "/complete", headers={"Authorization": f"Bearer {key}"})
                transaction.finish()
        except Exception:
            try:
                request_json(client, "POST", url + "/failed", headers={"Authorization": f"Bearer {key}"})
            except Exception:
                pass
            raise
    return {"status": "installed", "target": target, "plugin_version": plan["plugin_version"],
            "connector_verified": True, "agent_activation": "reload_required", "requirements": doctor()}
