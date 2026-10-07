import asyncio
import hashlib
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from pluglayer_mcp import native_runtime
from pluglayer_mcp.tools import updates


@pytest.mark.parametrize("windows", [True, False])
@pytest.mark.parametrize("name", ["../escape", "pluglayer-connector/../escape", "C:/escape", "pluglayer-connector\\escape"])
def test_runtime_rejects_unsafe_archive_paths(tmp_path, windows, name):
    buffer = io.BytesIO()
    if windows:
        with zipfile.ZipFile(buffer, "w") as archive:
            member = zipfile.ZipInfo("unsafe")
            member.filename = name
            archive.writestr(member, b"payload")
    else:
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            member = tarfile.TarInfo(name)
            member.size = 7
            archive.addfile(member, io.BytesIO(b"payload"))
    with pytest.raises(ValueError):
        native_runtime.unpack_runtime(buffer.getvalue(), tmp_path, windows=windows)
    assert not list(tmp_path.rglob("escape"))


def test_runtime_rejects_tar_links(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("pluglayer-connector/executable")
        member.type = tarfile.SYMTYPE
        member.linkname = "/outside"
        archive.addfile(member)
    with pytest.raises(ValueError):
        native_runtime.unpack_runtime(buffer.getvalue(), tmp_path, windows=False)


def test_refresh_checks_exact_download_before_running_code(monkeypatch, tmp_path):
    release = "connector-" + "b" * 40
    asset = {"url": f"https://github.com/pluglayer/mcp/releases/download/{release}/pluglayer-connector-linux-arm64.tar.gz",
             "sha256": hashlib.sha256(b"expected").hexdigest(), "size": 8}
    manifest = {"schema": 1, "release": release, "assets": {"linux-arm64": asset}}
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith("connector-release"):
            return httpx.Response(200, json=manifest)
        return httpx.Response(200, content=b"tampered")
    original = httpx.Client
    monkeypatch.setattr(native_runtime.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(native_runtime, "resolve_api_base_url", lambda: "https://api.pluglayer.com")
    monkeypatch.setattr(native_runtime, "platform_name", lambda: "linux-arm64")
    monkeypatch.setattr(native_runtime.sys, "platform", "linux")
    def execute(*args, **kwargs):
        pytest.fail("Unverified runtime executed")
    monkeypatch.setattr(native_runtime.subprocess, "run", execute)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(ValueError, match="verification"):
        native_runtime.refresh_connector("connector-" + "a" * 40)
    assert len(calls) == 2
    assert not (tmp_path / ".pluglayer").exists()


def test_refresh_rejects_non_official_origin(monkeypatch):
    monkeypatch.setattr(native_runtime, "resolve_api_base_url", lambda: "https://untrusted.example")
    with pytest.raises(ValueError, match="official"):
        native_runtime.refresh_connector("connector-" + "a" * 40)


def test_native_update_invokes_bundled_runtime_with_approved_commit(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    calls = []
    class Process:
        returncode = 0
        async def communicate(self):
            return b"safe summary", b""
    async def start(*args, **kwargs):
        calls.append(args)
        return Process()
    monkeypatch.setattr(updates.asyncio, "create_subprocess_exec", start)
    release = updates.ReleaseInfo(target="cursor", version="1.2.3", commit_sha="a" * 40)
    assert asyncio.run(updates._run_pinned_installer(release)) == 0
    assert calls == [(sys.executable, "--upgrade", "cursor", "1.2.3", "a" * 40)]
