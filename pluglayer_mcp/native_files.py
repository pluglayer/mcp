"""Recoverable user-owned configuration writes for native public plugin setup."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


def secure_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("Setup directory must not be a symbolic link")
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        identity = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader(io.StringIO(identity.strip())))[1]
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        path.chmod(0o700)


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    if path.is_symlink():
        raise ValueError("Plugin configuration must not be a symbolic link")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Plugin configuration must contain a JSON object")
    return value


@contextmanager
def setup_lock(root: Path):
    """Serialize public setup/update so shared credentials cannot be interleaved."""
    path = root / "setup.lock"
    if path.is_symlink():
        raise ValueError("Setup lock must not be a symbolic link")
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Transaction:
    """Retain previous bytes/permissions and trees until verification succeeds."""

    def __init__(self):
        self.files: dict[Path, tuple[bytes, int] | None] = {}
        self.trees: list[tuple[Path, Path | None]] = []
        self.committed = False

    def write(self, path: Path, content: str | bytes, *, private: bool = False) -> None:
        if path.is_symlink():
            raise ValueError("Refusing to overwrite a symbolic link")
        if path not in self.files:
            self.files[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".pluglayer-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(content.encode("utf-8") if isinstance(content, str) else content)
            temporary.chmod(0o600 if private else (self.files[path][1] if self.files[path] else 0o600))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def json(self, path: Path, content: dict) -> None:
        self.write(path, json.dumps(content, indent=2) + "\n")

    def tree(self, source: Path, destination: Path, configure) -> None:
        if destination.is_symlink():
            raise ValueError("Refusing to replace a linked plugin directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=".pluglayer-stage-", dir=destination.parent))
        backup = None
        try:
            shutil.copytree(source, staged, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
            configure(staged)
            if destination.exists():
                backup = Path(tempfile.mkdtemp(prefix=".pluglayer-backup-", dir=destination.parent))
                backup.rmdir()
                destination.rename(backup)
            try:
                staged.rename(destination)
            except Exception:
                if backup:
                    backup.rename(destination)
                raise
            self.trees.append((destination, backup))
        finally:
            if staged.exists():
                shutil.rmtree(staged)

    def finish(self) -> None:
        self.committed = True
        for _destination, backup in self.trees:
            if backup:
                shutil.rmtree(backup, ignore_errors=True)

    def rollback(self) -> None:
        if self.committed:
            return
        for path, previous in reversed(list(self.files.items())):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                self.write(path, previous[0])
                path.chmod(previous[1])
        for destination, backup in reversed(self.trees):
            shutil.rmtree(destination)
            if backup:
                backup.rename(destination)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if not self.committed:
            self.rollback()
