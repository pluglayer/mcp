"""Verified immutable runtime refresh for native public plugin upgrades."""

import hashlib
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx

from pluglayer_mcp.credentials import resolve_api_base_url


def platform_name() -> str:
    system = {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(sys.platform)
    machine = platform.machine().lower()
    architecture = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if not system or not architecture:
        raise ValueError("Unsupported computer platform")
    return f"{system}-{architecture}"


def unpack_runtime(packed: bytes, destination: Path, *, windows: bool) -> None:
    total = 0
    seen = set()
    def location(name, size):
        nonlocal total
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                or not path.parts or path.parts[0] != "pluglayer-connector" or path in seen):
            raise ValueError("Unsafe connector archive")
        seen.add(path)
        total += size
        if total > 1024 * 1024 * 1024:
            raise ValueError("Connector extracted size is excessive")
        return destination.joinpath(*path.parts)
    if windows:
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            for entry in archive.infolist():
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Connector contains a symbolic link")
                path = location(entry.filename, entry.file_size)
                if entry.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(archive.read(entry))
    else:
        with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as archive:
            for entry in archive:
                if not entry.isfile() and not entry.isdir():
                    raise ValueError("Connector contains an unsupported archive member")
                path = location(entry.name, entry.size)
                if entry.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(archive.extractfile(entry).read())
                    path.chmod(entry.mode & 0o755)


def refresh_connector(current_release: str) -> Path | None:
    base = resolve_api_base_url().rstrip("/")
    if base not in {"https://api.pluglayer.com", "https://api.dev.pluglayer.com"}:
        raise ValueError("Native upgrades require an official PlugLayer API origin")
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        response = client.get(base + "/v1/plugin/install/connector-release")
        response.raise_for_status()
        manifest = response.json()
    release = manifest["release"]
    if not re.fullmatch(r"connector-[a-f0-9]{40}", release) or manifest["schema"] != 1:
        raise ValueError("Invalid connector release")
    if release == current_release:
        return None
    computer = platform_name()
    asset = manifest["assets"][computer]
    parsed = urlsplit(asset["url"])
    extension = "zip" if sys.platform == "win32" else "tar.gz"
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
            or not re.fullmatch(rf"/pluglayer/[a-z0-9-]+/releases/download/{release}/pluglayer-connector-{computer}\.{re.escape(extension)}", parsed.path)
            or not re.fullmatch(r"[a-f0-9]{64}", asset["sha256"])):
        raise ValueError("Untrusted connector asset")
    if sys.platform == "win32" and asset.get("signed") is not True:
        raise ValueError("Unsigned Windows connector")
    if sys.platform == "darwin" and asset.get("notarized") is not True:
        raise ValueError("Unnotarized macOS connector")
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        with client.stream("GET", asset["url"]) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 256 * 1024 * 1024:
                    raise ValueError("Connector download is excessive")
                chunks.append(chunk)
    packed = b"".join(chunks)
    if len(packed) != asset["size"] or hashlib.sha256(packed).hexdigest() != asset["sha256"]:
        raise ValueError("Connector download verification failed")
    parent = Path.home() / ".pluglayer/connectors" / release
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / computer
    with tempfile.TemporaryDirectory(prefix=".pluglayer-runtime-", dir=parent) as temporary:
        unpack_runtime(packed, Path(temporary), windows=sys.platform == "win32")
        staged = Path(temporary) / "pluglayer-connector"
        executable = staged / ("pluglayer-connector.exe" if sys.platform == "win32" else "pluglayer-connector")
        result = subprocess.run([str(executable), "--self-test"], check=True, capture_output=True, text=True, timeout=90)
        if json.loads(result.stdout)["release"] != release:
            raise ValueError("Downloaded connector release does not match")
        if not destination.exists():
            staged.rename(destination)
    return destination / ("pluglayer-connector.exe" if sys.platform == "win32" else "pluglayer-connector")
